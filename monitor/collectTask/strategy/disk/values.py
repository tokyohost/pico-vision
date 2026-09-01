"""磁盘各字段的默认解析策略。"""

from ..base import ContextFieldStrategy, SensorValueStrategy, integer, number


class DiskHealthLevelStrategy(SensorValueStrategy):
    """把健康剩余百分比映射为项目统一的健康等级。"""

    def parse(self, raw_data, context):
        """按旧版阈值返回 1 至 5 的健康等级。"""
        value = number((context.get("disk") or {}).get("health_percent"))
        if value is None:
            return None
        if value <= 0:
            return 5
        if value < 10:
            return 4
        if value < 25:
            return 3
        if value < 60:
            return 2
        return 1


DEFAULT_DISK_STRATEGIES = {
    "name": (ContextFieldStrategy("disk", "name", default=""),),
    "temperature_c": (ContextFieldStrategy("disk", "temperature_c", number),),
    "percent": (ContextFieldStrategy("disk", "used_space_percent", number),),
    "health": (DiskHealthLevelStrategy(),),
    "read_bps": (ContextFieldStrategy("disk", "read_bytes_per_second", integer),),
    "write_bps": (ContextFieldStrategy("disk", "write_bytes_per_second", integer),),
}
