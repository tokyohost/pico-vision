"""封装 macOS 原生命令与严格的指标数值校验。"""

import math
import os
import plistlib
import subprocess
from xml.parsers.expat import ExpatError


def number(value, minimum=0, maximum=None):
    """读取有限数值并过滤布尔值、越界值和无效传感器读数。"""
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(result) or result < minimum or (maximum is not None and result > maximum):
        return None
    return result


def run_command(command, timeout=3):
    """有界执行只读命令，不启动 shell、不交互提权并固定英文输出。"""
    environment = dict(os.environ, LC_ALL="C", LANG="C")
    try:
        return subprocess.run(command, capture_output=True, timeout=timeout, check=False, env=environment)
    except (OSError, subprocess.TimeoutExpired):
        return None


def read_plist(command, timeout=3):
    """执行 plist 输出命令，失败或结构损坏时返回空值。"""
    result = run_command(command, timeout)
    if result is None or result.returncode != 0:
        return None
    try:
        return plistlib.loads(result.stdout)
    except (ValueError, TypeError, OverflowError, plistlib.InvalidFileException, ExpatError):
        return None


def plist_samples(data):
    """提取 powermetrics 的 NUL 分隔 plist，忽略未写完的末尾样本。"""
    samples = []
    # XML plist 可能夹带工具提示，不能把提示文字交给 XML 解析器。
    for part in data.split(b"\0"):
        start = part.find(b"<?xml")
        end = part.rfind(b"</plist>")
        if start < 0 or end < start:
            continue
        try:
            payload = plistlib.loads(part[start:end + len(b"</plist>")])
        except (ValueError, TypeError, OverflowError, plistlib.InvalidFileException, ExpatError):
            continue
        if isinstance(payload, dict):
            samples.append(payload)
    return samples
