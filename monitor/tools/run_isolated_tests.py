"""逐个文件独立运行 monitor 测试，隔离桌面与 MicroPython 固件的同名模块。"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


MONITOR_ROOT = Path(__file__).resolve().parents[1]
WINDOWS_NATIVE_TESTS = {"test_windows_autostart.py", "test_windows_power_resume.py"}


def main(arguments=None):
    """保留每个测试文件的全部用例和退出码，任何适用模块失败都使验证失败。"""
    parser = argparse.ArgumentParser(description="独立进程执行完整 monitor 回归")
    parser.add_argument("--pattern", default="test_*.py")
    parser.add_argument("--report", type=Path)
    options = parser.parse_args(arguments)
    tests = sorted((MONITOR_ROOT / "tests").glob(options.pattern))
    if not tests:
        raise RuntimeError("没有匹配的测试文件")
    records = []
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    for test in tests:
        if test.name in WINDOWS_NATIVE_TESTS and sys.platform != "win32":
            # 注册表用例必须在 Windows 原生回归中执行，不能在 Mac 伪造 winreg。
            record = {"file": test.name, "skipped": "需要 Windows 原生注册表 API"}
            print(json.dumps(record, ensure_ascii=False), flush=True)
            records.append(record)
            continue
        print("运行测试文件：{}".format(test.name), flush=True)
        try:
            result = subprocess.run(
                [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-p", test.name, "-v"],
                cwd=MONITOR_ROOT, env=environment, timeout=180,
            )
            record = {"file": test.name, "exit_code": result.returncode}
        except subprocess.TimeoutExpired:
            record = {"file": test.name, "exit_code": 1, "error": "测试超时"}
        records.append(record)
    report = {"platform": sys.platform, "files": records,
              "failed": sum(item.get("exit_code", 0) != 0 for item in records),
              "skipped_files": sum("skipped" in item for item in records)}
    if options.report is not None:
        options.report.parent.mkdir(parents=True, exist_ok=True)
        options.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
