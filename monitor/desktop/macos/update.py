"""macOS 签名应用更新：校验、独立助手、同目录原子替换与回滚。"""

import argparse
import json
import logging
import os
import platform
import plistlib
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

from desktop.common.platform import data_directory
from desktop.common.release import ReleaseUpdater


BUNDLE_IDENTIFIER = "com.omniwatch.monitor"
APP_NAME = "OmniWatch.app"
EXECUTABLE_NAME = "pico-monitor"
LOGGER = logging.getLogger("pico-monitor.macos.update")


def current_architecture():
    """按当前进程架构选择发布包，不以物理 CPU 推测 Rosetta 进程架构。"""
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    raise RuntimeError("不支持的 macOS 架构：{}".format(machine))


class MacOsReleaseUpdater(ReleaseUpdater):
    """选择可直接原子替换的签名 ZIP，DMG 仅用于首次人工安装。"""

    def select_monitor_asset(self, assets, version):
        """通过完整版本与架构文件名选择唯一应用更新资源。"""
        name = "OmniWatch-macos-{}-v{}.zip".format(current_architecture(), version)
        matches = [asset for asset in assets if asset.get("name") == name]
        if len(matches) != 1:
            raise RuntimeError("发布中缺少唯一的 macOS 应用资源：{}".format(name))
        return matches[0]

    def download(self, asset, suffix, progress_callback=None):
        """应用包必须有 GitHub SHA-256 摘要，设备资源保留原有下载规则。"""
        if str(asset.get("name", "")).startswith("OmniWatch-macos-"):
            if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", str(asset.get("digest") or "")):
                raise RuntimeError("应用更新资源缺少可信 SHA-256 摘要，拒绝自动安装")
        return super().download(asset, suffix, progress_callback=progress_callback)


def application_bundle(executable=None):
    """由冻结程序位置定位真实 .app，源码或临时裸程序不允许自动替换。"""
    executable = Path(executable or sys.executable).resolve()
    bundle = executable.parent.parent.parent
    if executable.parent.name != "MacOS" or executable.parent.parent.name != "Contents" or bundle.suffix != ".app":
        raise RuntimeError("自动更新仅支持已安装的签名 .app；源码模式请手动更新")
    return bundle


def _bundle_identity(bundle):
    """读取 codesign 标识和团队，不接受开发用 ad-hoc 签名。"""
    result = subprocess.run(["/usr/bin/codesign", "-dv", "--verbose=4", str(bundle)],
                            capture_output=True, text=True, check=True, timeout=30)
    output = result.stdout + result.stderr
    identity = re.search(r"^Identifier=(.+)$", output, re.MULTILINE)
    team = re.search(r"^TeamIdentifier=([A-Z0-9]{10})$", output, re.MULTILINE)
    if identity is None or identity.group(1).strip() != BUNDLE_IDENTIFIER or team is None:
        raise RuntimeError("应用必须有匹配 Bundle ID 的 Developer ID 团队签名")
    return team.group(1)


def verify_bundle(bundle, expected_team=None, expected_version=None, architecture=None):
    """同时验证签名、Gatekeeper、公证信任、版本和目标 CPU 架构。"""
    bundle = Path(bundle)
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(bundle)],
                   capture_output=True, check=True, timeout=60)
    subprocess.run(["/usr/sbin/spctl", "--assess", "--type", "execute", str(bundle)],
                   capture_output=True, check=True, timeout=60)
    team = _bundle_identity(bundle)
    if expected_team is not None and team != expected_team:
        raise RuntimeError("更新包签名团队与已安装应用不一致")
    values = plistlib.loads((bundle / "Contents" / "Info.plist").read_bytes())
    if values.get("CFBundleIdentifier") != BUNDLE_IDENTIFIER or values.get("CFBundleExecutable") != EXECUTABLE_NAME:
        raise RuntimeError("更新包应用标识或可执行程序不匹配")
    if expected_version is not None and str(values.get("OmniWatchReleaseVersion", values.get("CFBundleShortVersionString", ""))) != str(expected_version):
        raise RuntimeError("更新包版本与 Release 声明不一致")
    result = subprocess.run(["/usr/bin/lipo", "-archs", str(bundle / "Contents" / "MacOS" / EXECUTABLE_NAME)],
                            capture_output=True, text=True, check=True, timeout=15)
    if (architecture or current_architecture()) not in result.stdout.split():
        raise RuntimeError("更新包不支持当前应用进程架构")
    return team


def validate_archive(package):
    """拒绝路径穿越、包外符号链接及超大 ZIP，允许 .app 内部相对链接。"""
    with zipfile.ZipFile(package) as archive:
        files = archive.infolist()
        if len(files) > 30000 or sum(item.file_size for item in files) > 2 * 1024 ** 3:
            raise RuntimeError("更新包解压大小或文件数超限")
        seen = set()
        for item in files:
            name = item.orig_filename.rstrip("/")
            normalized = posixpath.normpath(name)
            metadata = name in ("__MACOSX", "__MACOSX/._" + APP_NAME, "__MACOSX/" + APP_NAME) or name.startswith("__MACOSX/" + APP_NAME + "/")
            application = name == APP_NAME or name.startswith(APP_NAME + "/")
            if "\\" in name or name.startswith("/") or normalized != name or not (metadata or application):
                raise RuntimeError("更新包包含非法路径：{}".format(item.filename))
            if name in seen:
                raise RuntimeError("更新包包含重复路径")
            seen.add(name)
            if stat.S_ISLNK(item.external_attr >> 16):
                if metadata:
                    raise RuntimeError("更新包元数据不能包含符号链接")
                if item.file_size > 8192:
                    raise RuntimeError("更新包符号链接过长")
                target = archive.read(item).decode("utf-8")
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
                if target.startswith("/") or "\\" in target or not (resolved == APP_NAME or resolved.startswith(APP_NAME + "/")):
                    raise RuntimeError("更新包符号链接指向应用外部")


def prepare_update(package, expected_version=None):
    """校验更新包并从新包启动助手，主程序退出前不覆盖当前应用。"""
    if sys.platform != "darwin":
        raise RuntimeError("macOS 更新只能在 macOS 上执行")
    installed = application_bundle()
    if installed.is_symlink() or not os.access(installed.parent, os.W_OK):
        raise RuntimeError("应用安装目录不可写，请通过 DMG 手动更新或安装到用户 Applications")
    team = verify_bundle(installed)
    validate_archive(package)
    update_root = data_directory() / "updates"
    update_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="omniwatch-macos-update-", dir=update_root))
    stage.chmod(0o700)
    try:
        subprocess.run(["/usr/bin/ditto", "-x", "-k", str(package), str(stage)], check=True, capture_output=True, timeout=120)
        source = stage / APP_NAME
        verify_bundle(source, team, expected_version)
        manifest = {"source": str(source), "target": str(installed), "parent_pid": os.getpid(),
                    "team": team, "version": expected_version, "architecture": current_architecture()}
        manifest_path = stage / "update.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        manifest_path.chmod(0o600)
        environment = os.environ.copy()
        # 更新助手必须加载新应用自己的冻结资源，而不是继承旧应用的 _MEIPASS。
        environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        subprocess.Popen([str(source / "Contents" / "MacOS" / EXECUTABLE_NAME), "--apply-macos-update", str(manifest_path)],
                         env=environment, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        shutil.rmtree(stage)
        raise
    Path(package).unlink(missing_ok=True)
    return stage


def _wait_for_parent(pid, timeout=120):
    """等待主程序退出；超时不替换正在运行的应用。"""
    if pid <= 1 or pid == os.getpid():
        raise ValueError("更新助手父进程编号无效")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.25)
    raise RuntimeError("等待主程序退出超时，应用未替换")


def apply_update(manifest_path):
    """同目录构造新副本、原子替换并保留旧 .app；失败时自动恢复。"""
    manifest_path = Path(manifest_path).resolve()
    stage = manifest_path.parent
    if not stage.name.startswith("omniwatch-macos-update-"):
        raise ValueError("更新暂存目录无效")
    values = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = Path(values["source"]).resolve()
    target = Path(values["target"]).resolve()
    if source != stage / APP_NAME or target.suffix != ".app" or source == target:
        raise ValueError("更新源或安装目标无效")
    verify_bundle(target, values["team"], architecture=values["architecture"])
    verify_bundle(source, values["team"], values["version"], values["architecture"])
    _wait_for_parent(int(values["parent_pid"]))
    token = uuid.uuid4().hex
    replacement = target.parent / (".omniwatch-new-" + token + ".app")
    backup = target.parent / (".omniwatch-backup-" + token + ".app")
    replaced = False
    moved = False
    try:
        shutil.copytree(source, replacement, symlinks=True)
        verify_bundle(replacement, values["team"], values["version"], values["architecture"])
        target.rename(backup)
        moved = True
        replacement.rename(target)
        replaced = True
        subprocess.run(["/usr/bin/open", str(target)], capture_output=True, check=True, timeout=30)
    except Exception:
        if moved:
            if replaced:
                target.rename(replacement)
            backup.rename(target)
        raise
    finally:
        if replacement.exists():
            shutil.rmtree(replacement)
    # 启动成功即完成提交；状态文件失败不能回滚一个已经启动的新应用。
    result = {"ok": True, "backup": str(backup), "version": values["version"]}
    try:
        (stage.parent / "last-update.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    except OSError:
        LOGGER.exception("应用更新成功，但更新记录写入失败；旧应用保留在 %s", backup)
    shutil.rmtree(stage)


def run_update_helper(arguments):
    """执行冻结应用专用助手入口，错误状态写入暂存目录供排障。"""
    parser = argparse.ArgumentParser(description="macOS 应用更新助手")
    parser.add_argument("manifest")
    options = parser.parse_args(arguments)
    if sys.platform != "darwin":
        raise RuntimeError("更新助手只能运行在 macOS")
    try:
        apply_update(options.manifest)
        return 0
    except Exception as error:
        LOGGER.exception("macOS 应用更新失败")
        manifest = Path(options.manifest).resolve()
        if manifest.parent.name.startswith("omniwatch-macos-update-") and manifest.parent.is_dir():
            (manifest.parent / "error.log").write_text(str(error), encoding="utf-8")
        return 1
