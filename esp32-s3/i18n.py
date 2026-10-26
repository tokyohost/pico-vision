"""小屏轻量翻译与语言持久化，不依赖桌面框架。"""

import json
import os

from locales.zh_cn import MESSAGES as CHINESE
from locales.en_us import MESSAGES as ENGLISH

SUPPORTED_LOCALES = ("zh-CN", "en-US")
_locale = "zh-CN"
_path = "locale.json"


def load_locale(path="locale.json"):
    """首次绘制前读取语言，缺失或损坏的文件回退中文。"""
    global _locale, _path
    _path = path
    _locale = "zh-CN"
    try:
        with open(path, "r") as source:
            payload = json.load(source)
        value = payload.get("locale") if isinstance(payload, dict) else None
        if value in SUPPORTED_LOCALES:
            _locale = value
    except (OSError, ValueError, TypeError):
        pass
    return _locale


def get_locale():
    """返回已加载的当前语言，不在逐帧绘制时访问文件。"""
    return _locale


def set_locale(locale):
    """仅在合法语言变化时写入一次，保存失败仍允许当前会话使用。"""
    global _locale
    if locale not in SUPPORTED_LOCALES or locale == _locale:
        return False
    _locale = locale
    temporary = _path + ".tmp"
    try:
        with open(temporary, "w") as target:
            target.write(json.dumps({"locale": locale}))
        # ESP32 的文件系统支持同目录替换；失败时保留旧文件，不先删除。
        os.rename(temporary, _path)
    except OSError:
        try:
            os.remove(temporary)
        except OSError:
            pass
    return True


def t(key, params=None):
    """按语义键翻译，缺失时回退中文和键名，并支持命名占位符。"""
    messages = ENGLISH if _locale == "en-US" else CHINESE
    text = messages.get(key, CHINESE.get(key, key))
    if params is not None:
        try:
            return text.format(**params)
        except (KeyError, ValueError, IndexError):
            return text
    return text
