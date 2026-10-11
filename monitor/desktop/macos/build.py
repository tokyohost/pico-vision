"""构建双架构 macOS 应用、验证插件运行时并制作签名公证发行包。"""

import argparse
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


MONITOR_ROOT = Path(__file__).resolve().parents[2]
MACHO_MAGICS = {b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
                b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"}


def run(command, **options):
    """执行参数化构建命令，任何失败都终止发行包生成。"""
    return subprocess.run([str(value) for value in command], check=True, **options)


def macho_files(directory):
    """根据文件魔数识别原生二进制，跳过链接并避免重复签名。"""
    for path in Path(directory).rglob("*"):
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as stream:
                if stream.read(4) in MACHO_MAGICS:
                    yield path


def deployment_versions(output):
    """只提取 Mach-O 部署版本，不把 SDK、源码或 dylib 版本当成系统要求。"""
    versions = []
    for block in re.split(r"Load command \d+", output):
        if not re.search(r"cmd (?:LC_BUILD_VERSION|LC_VERSION_MIN_MACOSX)\b", block):
            continue
        matched = re.search(r"^\s*(?:minos|version) (\d+(?:\.\d+)*)\s*$", block, re.MULTILINE)
        if matched:
            versions.append(tuple(int(value) for value in matched.group(1).split(".")))
    return versions


def copy_plugin_runtime(source, destination):
    """创建应用私有运行时副本，保留原 uv 环境的管理标记与全部文件。"""
    # 副本交由应用构建器管理，不再是 uv 的安装目录；不携带原管理器的
    # PEP 668 标记，才能在暂存副本中离线初始化 pip。原环境绝不改动，
    # 最终插件仍使用独立 venv，不向系统 Python 或签名后的应用写依赖。
    shutil.copytree(Path(source).resolve(), destination, symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "EXTERNALLY-MANAGED"))


def audit_native_dependencies(directory, architecture, minimum=(12, 0)):
    """拒绝架构不匹配或最低系统高于 macOS 12 的任何原生依赖。"""
    binaries = list(macho_files(directory))
    if not binaries:
        raise RuntimeError("构建产物中没有原生程序")
    for path in binaries:
        result = run(["/usr/bin/lipo", "-archs", path], capture_output=True, text=True)
        if architecture not in result.stdout.split():
            raise RuntimeError("原生依赖架构不匹配：{}".format(path))
        result = run(["/usr/bin/otool", "-arch", architecture, "-l", path], capture_output=True, text=True)
        versions = deployment_versions(result.stdout)
        if not versions or any((version + (0, 0))[:2] > minimum for version in versions):
            raise RuntimeError("原生依赖不能声明兼容 macOS 12：{}，部署版本 {}".format(path, versions))


def validate_runtime(runtime, expected_architecture=None, initialize_pip=False):
    """验证完整 Python、pip、虚拟环境及安装位置可迁移性，不把冻结入口当 Python。"""
    runtime = Path(runtime).resolve()
    python = runtime / "bin" / "python3"
    environment_variables = {key: value for key, value in os.environ.items() if key not in ("PYTHONHOME", "PYTHONPATH")}
    environment_variables.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
    if not python.is_file():
        raise RuntimeError("插件运行时缺少 bin/python3")
    result = run([python, "-B", "-I", "-c", "import json,platform,sys; print(json.dumps({'prefix':sys.prefix,'architecture':platform.machine()}))"], capture_output=True, text=True, env=environment_variables)
    values = json.loads(result.stdout)
    prefixes = {runtime}
    if runtime.parent.name in ("Resources", "Frameworks") and runtime.parent.parent.name == "Contents":
        # PyInstaller 混合代码/数据目录会在 Resources 与 Frameworks 中交叉链接。
        other = "Frameworks" if runtime.parent.name == "Resources" else "Resources"
        prefixes.add((runtime.parent.parent / other / runtime.name).resolve())
    if Path(values["prefix"]).resolve() not in prefixes:
        raise RuntimeError("Python Runtime 不是可迁移的完整安装，sys.prefix 指向外部目录")
    if expected_architecture and values["architecture"] != expected_architecture:
        raise RuntimeError("插件 Python 架构与应用不一致")
    if initialize_pip:
        # 只初始化构建暂存副本；签名完成后的 .app 必须保持只读。
        run([python, "-B", "-s", "-m", "ensurepip", "--upgrade"], capture_output=True, env=environment_variables)
    run([python, "-B", "-I", "-m", "pip", "--version"], capture_output=True, env=environment_variables)
    with tempfile.TemporaryDirectory(prefix="omniwatch-runtime-check-") as directory:
        environment = Path(directory) / "environment"
        # venv 默认用不带 -B 的隔离子进程调用 ensurepip，可能写入共享的签名标准库。
        # 拆开创建和 pip 初始化，让每一层 Python 都明确禁止缓存，pip 只写临时环境。
        run([python, "-B", "-I", "-m", "venv", "--without-pip", environment], capture_output=True, env=environment_variables)
        # ensurepip 会传播 -I 却不会传播 -B，子进程因此忽略缓存禁用环境变量。
        # 仅此引导步骤改用 -s，并清除 PYTHONHOME/PYTHONPATH，兼顾隔离和只读运行时。
        run([environment / "bin/python", "-B", "-s", "-m", "ensurepip", "--upgrade"], capture_output=True, env=environment_variables)
        run([environment / "bin/python", "-B", "-I", "-m", "pip", "--version"], capture_output=True, env=environment_variables)


def sign_plugin_runtime(application, identity):
    """逐层签名完整插件运行时，开发包使用 adhoc，正式发行保持安全签名。"""
    entitlements = MONITOR_ROOT / "desktop/macos/plugin-entitlements.plist"
    signing_options = [] if identity == "-" else ["--options", "runtime", "--timestamp"]
    for path in macho_files(application):
        if "plugin-runtime" not in path.parts:
            continue
        command = ["/usr/bin/codesign", "--force", *signing_options, "--sign", identity]
        if "bin" in path.parts:
            command.extend(["--entitlements", entitlements])
        run([*command, path], capture_output=True)
    run(["/usr/bin/codesign", "--force", *signing_options, "--sign", identity,
         "--entitlements", MONITOR_ROOT / "desktop/macos/entitlements.plist", application], capture_output=True)
    run(["/usr/bin/codesign", "--verify", "--deep", "--strict", application], capture_output=True)


def notarize(path, profile, keychain=None):
    """通过预存凭据公证，只有 Accepted 状态才继续，不打印账户密码。"""
    command = ["xcrun", "notarytool", "submit", path, "--keychain-profile", profile,
               "--wait", "--output-format", "json"]
    if keychain:
        command.extend(["--keychain", keychain])
    result = run(command, capture_output=True, text=True, timeout=1800)
    values = json.loads(result.stdout)
    if values.get("status") != "Accepted":
        raise RuntimeError("公证失败：{}，提交编号 {}".format(values.get("status"), values.get("id")))


def zip_application(application, output):
    """使用 ditto 保留 macOS 应用链接、权限和签名元数据。"""
    run(["/usr/bin/ditto", "-c", "-k", "--keepParent", application, output], capture_output=True)


def verify_dmg_signature(dmg):
    """只读挂载最终 DMG 并检查应用签名，失败时仍卸载本次创建的挂载卷。"""
    run(["/usr/bin/hdiutil", "verify", dmg], capture_output=True)
    attachment = run(["/usr/bin/hdiutil", "attach", "-readonly", "-nobrowse", "-plist", dmg], capture_output=True)
    mounts = [Path(item["mount-point"]) for item in plistlib.loads(attachment.stdout)["system-entities"]
              if "mount-point" in item]
    try:
        if len(mounts) != 1:
            raise RuntimeError("最终 DMG 没有唯一挂载卷")
        run(["/usr/bin/codesign", "--verify", "--deep", "--strict", mounts[0] / "OmniWatch.app"], capture_output=True)
    finally:
        for mount in mounts:
            run(["/usr/bin/hdiutil", "detach", mount], capture_output=True)


def build(options):
    """执行构建、依赖审计、运行时验证、签名、公证和 DMG 生成。"""
    if sys.platform != "darwin" or platform.machine() != options.architecture:
        raise RuntimeError("必须在对应架构的 macOS 原生构建环境运行")
    identity = os.environ.get("MONITOR_MAC_SIGNING_IDENTITY")
    if not options.unsigned and (not identity or not options.notary_profile):
        raise RuntimeError("正式发行必须提供 Developer ID 签名和公证凭据；开发验证可显式使用 --unsigned")
    if not (MONITOR_ROOT / "win/ui-web/dist/index.html").is_file():
        raise RuntimeError("请先构建 Vue 界面：npm run build --prefix win/ui-web")
    output_root = Path(options.output).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="omniwatch-macos-build-") as temporary:
        temporary = Path(temporary)
        runtime = temporary / "plugin-runtime"
        copy_plugin_runtime(options.runtime, runtime)
        validate_runtime(runtime, options.architecture, initialize_pip=True)
        environment = os.environ.copy()
        environment.update({"MONITOR_MAC_ARCH": options.architecture,
                            "MONITOR_MAC_PLUGIN_RUNTIME": str(runtime),
                            "MONITOR_MAC_SIGNING_IDENTITY": "" if options.unsigned else identity,
                            "MACOSX_DEPLOYMENT_TARGET": "12.0",
                            "PYINSTALLER_STRICT_BUNDLE_CODESIGN_ERROR": "1"})
        run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "--workpath", temporary / "work",
             "--distpath", temporary / "dist", MONITOR_ROOT / "pico_monitor_macos.spec"], cwd=MONITOR_ROOT, env=environment)
        application = temporary / "dist/OmniWatch.app"
        # 私有解释器保留已验证的相对动态库布局；不进入 PyInstaller 二进制路径改写。
        # 复制完成后仍审计所有原生文件、重新签名外层应用并验证完整运行时。
        bundle_runtime = application / "Contents/Resources/plugin-runtime"
        copy_plugin_runtime(runtime, bundle_runtime)
        audit_native_dependencies(application, options.architecture)
        sign_plugin_runtime(application, "-" if options.unsigned else identity)
        validate_runtime(bundle_runtime, options.architecture)
        executable = application / "Contents/MacOS/pico-monitor"
        run([executable, "--help"], capture_output=True, env={**environment, "PYINSTALLER_RESET_ENVIRONMENT": "1"})
        result = run([executable, "--version"], capture_output=True, text=True,
                     env={**environment, "PYINSTALLER_RESET_ENVIRONMENT": "1"})
        if "pico-monitor" not in result.stdout:
            raise RuntimeError("冻结程序标准输出验证失败")
        # 所有运行检查结束后再次验证，不能仅相信检查前的签名成功。
        run(["/usr/bin/codesign", "--verify", "--deep", "--strict", application], capture_output=True)
        from build_info import MONITOR_VERSION
        if not options.unsigned:
            notarization_zip = temporary / "notarization.zip"
            zip_application(application, notarization_zip)
            notarize(notarization_zip, options.notary_profile, options.notary_keychain)
            run(["xcrun", "stapler", "staple", application], capture_output=True)
            run(["/usr/sbin/spctl", "--assess", "--type", "execute", application], capture_output=True)
        # 未公证的开发包使用不同文件名，自动更新器绝不把它当正式发行包。
        suffix = "-dev" if options.unsigned else ""
        name = "OmniWatch-macos-{}{}-v{}".format(options.architecture, suffix, MONITOR_VERSION)
        zip_application(application, output_root / (name + ".zip"))
        volume = temporary / "volume"
        volume.mkdir()
        run(["/usr/bin/ditto", application, volume / "OmniWatch.app"], capture_output=True)
        (volume / "Applications").symlink_to("/Applications", target_is_directory=True)
        dmg = output_root / (name + ".dmg")
        run(["/usr/bin/hdiutil", "create", "-volname", "OmniWatch", "-srcfolder", volume,
             "-ov", "-format", "UDZO", dmg], capture_output=True)
        verify_dmg_signature(dmg)
        if not options.unsigned:
            run(["/usr/bin/codesign", "--sign", identity, "--timestamp", dmg], capture_output=True)
            notarize(dmg, options.notary_profile, options.notary_keychain)
            run(["xcrun", "stapler", "staple", dmg], capture_output=True)
        return output_root


def main(arguments=None):
    """解析构建参数，插件运行时必须显式提供，避免依赖构建机系统 Python。"""
    parser = argparse.ArgumentParser(description="OmniWatch macOS 构建与公证")
    parser.add_argument("--architecture", choices=("x86_64", "arm64"), required=True)
    parser.add_argument("--runtime", required=True, help="可迁移完整 Python 根目录，例如 uv 管理的 standalone Python")
    parser.add_argument("--output", default=str(MONITOR_ROOT / "dist/macos"))
    parser.add_argument("--unsigned", action="store_true", help="仅生成开发验证包，不用于正式发行或自动更新")
    parser.add_argument("--notary-profile", default=os.environ.get("MONITOR_MAC_NOTARY_PROFILE"))
    parser.add_argument("--notary-keychain", default=os.environ.get("MONITOR_MAC_NOTARY_KEYCHAIN"))
    build(parser.parse_args(arguments))
    return 0


if __name__ == "__main__":
    # 模块方式运行保证 build_info 与项目公共模块从同一源码目录加载。
    raise SystemExit(main())
