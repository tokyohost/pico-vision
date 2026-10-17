"""只读验证 Linux 实机上 issue #3 的修复前后容量及快照发布结果。"""

import argparse
import json
import platform
from pathlib import Path
import subprocess
import sys


def main():
    """对照 sysfs 与 blockdev 检查未挂载磁盘，不修改分区、文件系统或挂载状态。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--expect", choices=("broken", "fixed"), default="fixed")
    options = parser.parse_args()
    if platform.system() != "Linux":
        parser.error("此验证需要具有未挂载物理盘的真实 Linux 环境")
    sys.path.insert(0, str(options.source.resolve() / "monitor"))
    from collectTask.tasks.disk_capacity_health import DiskCapacityHealthTask
    from monitor_core.collectors.disk import DiskMetricsMixin

    collector = DiskMetricsMixin()
    collector.disk_temperature_time = 0.0
    collector.disk_temperature_cache = {}
    snapshot = DiskCapacityHealthTask(collector).collect()
    physical = {item["name"]: item for item in snapshot["physical_disks"]}
    checks = []
    errors = []
    for disk in snapshot["disks"]:
        if disk["mountpoints"]:
            continue
        name = disk["name"]
        size_file = Path("/sys/class/block") / name / "size"
        if not size_file.exists():
            continue
        expected_bytes = int(size_file.read_text(encoding="ascii").strip()) * 512
        if expected_bytes <= 0:
            continue
        # 使用独立系统命令交叉核对容量；实机验证需具备只读块设备权限。
        blockdev_bytes = int(subprocess.check_output(["blockdev", "--getsize64", "/dev/" + name], text=True).strip())
        expected_snapshot_bytes = expected_bytes if options.expect == "fixed" else 0
        valid = (
            blockdev_bytes == expected_bytes
            and disk["total_bytes"] == expected_snapshot_bytes
            and physical[name]["total_bytes"] == expected_snapshot_bytes
            and disk["used_bytes"] == disk.get("free_bytes", 0) == disk["percent"] == 0
        )
        checks.append({"name": name, "sysfs_bytes": expected_bytes, "blockdev_bytes": blockdev_bytes,
                       "disks_bytes": disk["total_bytes"], "physical_disks_bytes": physical[name]["total_bytes"],
                       "valid": valid})
        if not valid:
            errors.append("磁盘容量不符合预期：" + name)
    if not checks:
        errors.append("测试环境必须至少有一块可读且未挂载的物理盘")
    mounted = [item for item in snapshot["disks"] if item["mountpoints"]]
    total_bytes = sum(item["total_bytes"] for item in mounted)
    used_bytes = sum(item["used_bytes"] for item in mounted)
    expected_overview = {"total_bytes": total_bytes, "used_bytes": used_bytes,
                         "percent": round(used_bytes * 100 / total_bytes, 1) if total_bytes else 0}
    if snapshot["disk"] != expected_overview:
        errors.append("总览包含未挂载设备容量或重复累计 LVM/RAID 容量")
    print(json.dumps({"expect": options.expect, "hostname": platform.node(), "kernel": platform.release(),
                      "checks": checks, "snapshot": snapshot, "errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
