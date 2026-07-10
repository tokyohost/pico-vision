"""验证 Linux 安装清单覆盖入口模块的全部顶层本地依赖。"""

import ast
import unittest
from pathlib import Path


MONITOR_ROOT = Path(__file__).resolve().parents[1]


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


if __name__ == "__main__":
    unittest.main()
