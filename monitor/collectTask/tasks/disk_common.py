"""磁盘采集任务共享的快照合并工具。"""

import threading


DISK_CAPACITY_HEALTH_FIELDS = (
    "devices",
    "mountpoints",
    "filesystems",
    "used_bytes",
    "total_bytes",
    "percent",
    "health",
)
DISK_TEMPERATURE_FIELDS = ("temperature_c",)
DISK_RATE_FIELDS = ("read_bps", "write_bps", "read_history", "write_history")


def disk_task_lock(collector):
    """获取磁盘任务共享锁，保证并行子任务不会互相覆盖快照。"""
    lock = getattr(collector, "_disk_task_lock", None)
    if lock is None:
        lock = threading.RLock()
        collector._disk_task_lock = lock
    return lock


def disk_snapshot(collector):
    """读取磁盘任务共享快照，没有采集结果时返回空结构。"""
    return getattr(
        collector,
        "_disk_task_snapshot",
        {"disk": {"percent": 0, "used_bytes": 0, "total_bytes": 0}, "disks": [], "physical_disks": []},
    )


def disk_snapshot_disks(collector):
    """复制当前磁盘明细，供读写速率任务计算实时速度。"""
    with disk_task_lock(collector):
        return [dict(item) for item in disk_snapshot(collector).get("disks", ())]


def publish_disk_snapshot(
    collector,
    disk=None,
    disks=None,
    physical_disks=None,
    disk_fields=(),
    physical_fields=(),
    replace_disks=False,
    replace_physical_disks=False,
):
    """把单个磁盘子任务的字段合并为完整磁盘快照片段。"""
    with disk_task_lock(collector):
        snapshot = disk_snapshot(collector)
        merged = {
            "disk": dict(snapshot.get("disk", {})),
            "disks": _merge_items(snapshot.get("disks", ()), disks, disk_fields, replace_disks),
            "physical_disks": _merge_items(
                snapshot.get("physical_disks", ()),
                physical_disks,
                physical_fields,
                replace_physical_disks,
            ),
        }
        if disk is not None:
            merged["disk"].update(disk)
        collector._disk_task_snapshot = merged
        return {
            "disk": dict(merged["disk"]),
            "disks": [dict(item) for item in merged["disks"]],
            "physical_disks": [dict(item) for item in merged["physical_disks"]],
        }


def _merge_items(current_items, update_items, fields, replace=False):
    """按磁盘名称合并指定字段，并保留其他任务已经发布的数据。"""
    merged = {item.get("name"): dict(item) for item in current_items if item.get("name")}
    update_names = [item.get("name") for item in update_items or () if item.get("name")]
    order = update_names if replace else [item.get("name") for item in current_items if item.get("name")]
    if replace:
        merged = {name: merged[name] for name in update_names if name in merged}
    for update in update_items or ():
        name = update.get("name")
        if not name:
            continue
        item = merged.get(name)
        if item is None:
            item = {"name": name}
            merged[name] = item
            order.append(name)
        for field in fields:
            if field in update:
                item[field] = update[field]
    return [merged[name] for name in order if name in merged]
