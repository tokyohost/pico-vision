"""验证 Linux 安装清单覆盖入口模块的全部顶层本地依赖。"""

import ast
import importlib.util
import json
import tarfile
import tempfile
import unittest
from pathlib import Path


MONITOR_ROOT = Path(__file__).resolve().parents[1]
NAS_PACKAGER_PATH = MONITOR_ROOT / "tools" / "package_nas_release.py"
NAS_PACKAGER_SPEC = importlib.util.spec_from_file_location(
    "package_nas_release",
    NAS_PACKAGER_PATH,
)
NAS_PACKAGER = importlib.util.module_from_spec(NAS_PACKAGER_SPEC)
NAS_PACKAGER_SPEC.loader.exec_module(NAS_PACKAGER)


def _top_level_local_imports(path, local_modules):
    """返回指定源码在模块顶层直接导入的本地单文件模块名。"""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    imports = set()
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            names = (alias.name for alias in statement.names)
        elif isinstance(statement, ast.ImportFrom) and statement.level == 0 and statement.module:
            names = (statement.module,)
        else:
            continue
        for name in names:
            root_name = name.split(".", 1)[0]
            if root_name in local_modules:
                imports.add(root_name)
    return imports


def _linux_runtime_module_files():
    """计算 Linux 入口及已安装包目录引用的顶层本地模块文件。"""
    local_modules = {path.stem for path in MONITOR_ROOT.glob("*.py")}
    source_files = [MONITOR_ROOT / "pico_monitor.py"]
    source_files.extend((MONITOR_ROOT / "monitor_core").rglob("*.py"))
    source_files.extend((MONITOR_ROOT / "collectTask").rglob("*.py"))
    pending = list(source_files)
    discovered = set()
    while pending:
        source_path = pending.pop()
        for module_name in _top_level_local_imports(source_path, local_modules):
            if module_name in discovered:
                continue
            discovered.add(module_name)
            pending.append(MONITOR_ROOT / (module_name + ".py"))
    return {module_name + ".py" for module_name in discovered}


class LinuxPackagingTest(unittest.TestCase):
    """确认 Debian 与通用 Linux 安装方式不会遗漏本地运行模块。"""

    def test_debian_manifest_contains_runtime_module_closure(self):
        """确认 Debian 安装清单包含完整的顶层本地模块闭包。"""
        manifest_sources = {
            line.split()[0]
            for line in (MONITOR_ROOT / "debian" / "install").read_text(
                encoding="utf-8-sig"
            ).splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        missing = sorted(_linux_runtime_module_files() - manifest_sources)
        self.assertEqual([], missing, "Debian 安装清单缺少运行模块：{}".format("、".join(missing)))

    def test_generic_installer_contains_runtime_module_closure(self):
        """确认通用安装脚本逐一安装完整的顶层本地模块闭包。"""
        installer = (MONITOR_ROOT / "install-linux.sh").read_text(encoding="utf-8-sig")
        missing = sorted(
            filename
            for filename in _linux_runtime_module_files()
            if '"$script_directory/{}"'.format(filename) not in installer
        )
        self.assertEqual([], missing, "通用安装脚本缺少运行模块：{}".format("、".join(missing)))

    def test_systemd_services_provide_writable_state_directory(self):
        """确认两种 Linux 服务均把运行数据指向 systemd 可写状态目录。"""
        service_paths = (
            MONITOR_ROOT / "debian" / "pico-monitor.service",
            MONITOR_ROOT / "packaging" / "pico-monitor-generic.service",
        )
        for service_path in service_paths:
            with self.subTest(service=service_path.name):
                content = service_path.read_text(encoding="utf-8-sig")
                self.assertIn("StateDirectory=pico-monitor", content)
                self.assertIn("Environment=HOME=/var/lib/pico-monitor", content)
                self.assertIn(
                    "Environment=PICO_MONITOR_DATA_ROOT=/var/lib/pico-monitor",
                    content,
                )
                self.assertIn(
                    "Environment=PICO_MONITOR_SCREENSHOT_DIR=/var/lib/pico-monitor/screenshot",
                    content,
                )

    def test_generic_installer_contains_all_nas_strategy_directories(self):
        """确认通用安装脚本会安装全部 NAS 策略目录。"""
        installer = (MONITOR_ROOT / "install-linux.sh").read_text(encoding="utf-8-sig")
        for target in ("synology", "qnap", "truenas"):
            with self.subTest(target=target):
                self.assertIn('collectTask/tasks/{}"'.format(target), installer)

    def test_linux_installers_include_runtime_package_directories(self):
        """确认 DEB 与通用脚本安装自定义数据和网络运行包。"""
        installer = (MONITOR_ROOT / "install-linux.sh").read_text(encoding="utf-8-sig")
        manifest = (MONITOR_ROOT / "debian" / "install").read_text(encoding="utf-8-sig")
        for package_name in ("custom_data", "net"):
            with self.subTest(package=package_name):
                self.assertIn('"$INSTALL_ROOT/{}"'.format(package_name), installer)
                self.assertIn(
                    "{} usr/lib/pico-monitor".format(package_name),
                    manifest,
                )

    def test_nas_release_packages_contain_version_and_all_strategies(self):
        """确认每种 NAS 发布包包含版本清单和完整系统策略。"""
        with tempfile.TemporaryDirectory() as directory:
            for target in ("synology", "qnap", "truenas"):
                with self.subTest(target=target):
                    output_path = NAS_PACKAGER.build_package(
                        MONITOR_ROOT,
                        directory,
                        target,
                        "1.2.3",
                    )
                    with tarfile.open(output_path, "r:gz") as archive:
                        names = set(archive.getnames())
                        root_name = output_path.name[:-7]
                        manifest = json.loads(
                            archive.extractfile(
                                "{}/nas-package.json".format(root_name)
                            ).read().decode("utf-8")
                        )
                        build_info = archive.extractfile(
                            "{}/build_info.py".format(root_name)
                        ).read().decode("utf-8")
                    self.assertEqual(manifest["version"], "1.2.3")
                    self.assertEqual(manifest["target"], target)
                    self.assertIn('MONITOR_VERSION = "1.2.3"', build_info)
                    for strategy_target in ("synology", "qnap", "truenas"):
                        self.assertIn(
                            "{}/collectTask/tasks/{}/system_strategy.py".format(
                                root_name,
                                strategy_target,
                            ),
                            names,
                        )


if __name__ == "__main__":
    unittest.main()
