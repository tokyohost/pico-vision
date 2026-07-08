"""控制台编码、版本输出和日志配置工具。"""

import argparse
import atexit
import io
import logging
import logging.handlers
import os
import queue
import sys

from build_info import MONITOR_VERSION

LOGGER = logging.getLogger("pico-monitor")
_LOG_LISTENER = None


def _normalize_log_level(level_name):
    """把配置中的日志级别名称转换为 logging 可识别的整数级别。"""
    if isinstance(level_name, int):
        return level_name
    normalized = str(level_name or "INFO").strip().upper()
    level = getattr(logging, normalized, None)
    if not isinstance(level, int):
        raise SystemExit("日志级别无效：{}，可选 DEBUG、INFO、WARNING、ERROR、CRITICAL".format(level_name))
    return level


def _stop_log_listener():
    """停止异步日志监听器，确保进程退出前刷完队列中的日志。"""
    global _LOG_LISTENER
    listener = _LOG_LISTENER
    if listener is None:
        return
    _LOG_LISTENER = None
    listener.stop()

def _ensure_utf8_text_stream(stream):
    """确保日志输出流使用 UTF-8 编码，避免 Windows 打包后中文日志乱码。"""
    if stream is None:
        return None
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
        return stream
    except (AttributeError, OSError, ValueError):
        buffer = getattr(stream, "buffer", None)
        if buffer is None:
            return stream
        return io.TextIOWrapper(
            buffer,
            encoding="utf-8",
            errors="replace",
            line_buffering=True,
            write_through=True,
        )


def _open_inherited_text_stream(file_descriptor):
    """在 Windows 无控制台 EXE 中重新打开继承的标准管道。"""
    try:
        return os.fdopen(
            os.dup(file_descriptor),
            "w",
            encoding="utf-8",
            errors="replace",
            buffering=1,
        )
    except OSError:
        return None


def _configure_standard_streams():
    """统一修正标准输出和错误输出的编码，并返回日志应写入的文本流。"""
    stdout = _ensure_utf8_text_stream(getattr(sys, "stdout", None))
    stderr = _ensure_utf8_text_stream(getattr(sys, "stderr", None))
    if stdout is None:
        stdout = _open_inherited_text_stream(1)
        sys.stdout = stdout
    if stderr is None:
        stderr = _open_inherited_text_stream(2)
        sys.stderr = stderr
    return stderr or stdout or open(os.devnull, "w", encoding="utf-8")


def _write_version_to_console(version_text):
    """向当前命令行输出版本，并兼容 Windows 无控制台打包程序。"""
    output = getattr(sys, "stdout", None)
    if output is None and sys.platform == "win32" and getattr(sys, "frozen", False):
        try:
            import ctypes

            ctypes.windll.kernel32.AttachConsole(-1)
            output = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        except (OSError, AttributeError):
            output = None
    if output is not None:
        output.write(version_text + "\n")
        output.flush()


class MonitorVersionAction(argparse.Action):
    """输出 Monitor 构建版本后立即结束命令行程序。"""

    def __call__(self, parser, namespace, values, option_string=None):
        """打印统一构建版本，并以成功状态退出参数解析。"""
        del namespace, values, option_string
        _write_version_to_console("pico-monitor {}".format(MONITOR_VERSION))
        parser.exit()



def configure_logging(level_name="INFO"):
    """配置适合终端、systemd 和 Windows 托盘收集的异步日志格式。"""
    global _LOG_LISTENER
    _stop_log_listener()
    log_level = _normalize_log_level(level_name)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    stream_handler = logging.StreamHandler(_configure_standard_streams())
    stream_handler.setLevel(log_level)
    stream_handler.setFormatter(formatter)
    target_handlers = [stream_handler]
    error_log_path = str(os.getenv("PICO_MONITOR_ERROR_LOG_PATH") or "").strip()
    if error_log_path:
        error_handler = logging.FileHandler(
            error_log_path,
            encoding="utf-8",
            delay=True,
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)
        target_handlers.append(error_handler)
    log_queue = queue.Queue()
    queue_handler = logging.handlers.QueueHandler(log_queue)
    queue_handler.setLevel(log_level)
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log_level)
    root_logger.addHandler(queue_handler)
    _LOG_LISTENER = logging.handlers.QueueListener(
        log_queue,
        *target_handlers,
        respect_handler_level=True,
    )
    _LOG_LISTENER.start()
    atexit.register(_stop_log_listener)


def log_monitor_version():
    """在服务启动阶段记录当前 Monitor 构建版本。"""
    LOGGER.info("Pico Monitor 启动：版本=%s", MONITOR_VERSION)

