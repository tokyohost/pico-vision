"""GPU 各字段的默认解析策略。"""

from ..base import ContextFieldStrategy, integer, number


DEFAULT_GPU_STRATEGIES = {
    "name": (ContextFieldStrategy("gpu", "name", default=""),),
    "percent": (ContextFieldStrategy("gpu", "percent", number),),
    "temperature_c": (ContextFieldStrategy("gpu", "temperature_c", number),),
    "core_clock_mhz": (ContextFieldStrategy("gpu", "core_clock_mhz", number),),
    "memory_clock_mhz": (ContextFieldStrategy("gpu", "memory_clock_mhz", number),),
    "power_watts": (ContextFieldStrategy("gpu", "power_watts", number),),
    "dedicated_memory_used_bytes": (
        ContextFieldStrategy("gpu", "dedicated_memory_used_bytes", integer),
    ),
    "dedicated_memory_total_bytes": (
        ContextFieldStrategy("gpu", "dedicated_memory_total_bytes", integer),
    ),
}
