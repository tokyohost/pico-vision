"""提供驱动公共翻译入口，语言资源由 Python 导入机制纳入冻结包。"""

from locales.zh_cn import MESSAGES as CHINESE
from locales.en_us import MESSAGES as ENGLISH

SUPPORTED_LOCALES = ("zh-CN", "en-US")
_locale = "zh-CN"


class TranslatedText(str):
    """标记已国际化业务提示，区分第三方异常的原始详情。"""

    def format(self, *args, **kwargs):
        """保留格式化后的翻译标记，兼容旧调用方的占位符写法。"""
        return TranslatedText(super().format(*args, **kwargs))


def set_locale(locale):
    """设置进程内用户界面语言，无效配置回退到中文。"""
    global _locale
    _locale = locale if locale in SUPPORTED_LOCALES else "zh-CN"


def get_locale():
    """返回当前界面语言。"""
    return _locale


def t(key, params=None, locale=None):
    """按语义键翻译并插入命名参数，缺失时依次回退中文和键名。"""
    language = _locale if locale is None else locale
    messages = ENGLISH if language == "en-US" else CHINESE
    text = TranslatedText(messages.get(key, CHINESE.get(key, key)))
    if params is not None:
        try:
            return text.format(**params)
        except (KeyError, ValueError, IndexError):
            return text
    return text


def error_response(error):
    """业务提示直接显示，第三方异常保留原文详情并使用通用译文。"""
    message = str(error)
    translated = bool(error.args) and isinstance(error.args[0], TranslatedText)
    if translated or _locale == "zh-CN":
        result = {"ok": False, "message": message or t("error.unexpected")}
    else:
        result = {"ok": False, "message": t("error.unexpected"), "details": message}
    if isinstance(error, FileExistsError):
        # 界面依据稳定错误码决定是否提示覆盖，不匹配任何语言的错误正文。
        result["code"] = "file_exists"
    return result
