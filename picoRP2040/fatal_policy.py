"""定义固件致命异常的自动重启策略。"""


CANVAS_CAPACITY_ERROR = "脏矩形超过画布容量"


def should_restart_after_fatal(error):
    """判断致命异常是否需要通过硬复位恢复 Pico。"""
    if isinstance(error, MemoryError):
        return True
    return isinstance(error, ValueError) and str(error) == CANVAS_CAPACITY_ERROR
