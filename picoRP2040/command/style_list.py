"""实现设备全部屏幕样式清单查询命令。"""

import os

from command.base import CommandStrategy


class StyleListCommand(CommandStrategy):
    """返回 Pico 当前可识别的全部样式元数据。"""

    name = "style.list"

    def execute(self, params, context):
        """扫描全部样式，按样式名去重后返回当前样式及 Pico Flash 空间。"""
        del params
        from styles.style_plugins import style_catalog
        renderer = context.service("renderer", required=False)
        style_map = {}
        for item in style_catalog():
            if not isinstance(item, dict):
                continue
            style_name = item.get("name")
            if style_name and style_name not in style_map:
                style_map[style_name] = item
        return {
            "styles": list(style_map.values()),
            "flash": self._flash_space(),
            "active_style": renderer.style_name() if renderer is not None else "",
        }

    @staticmethod
    def _flash_space():
        """读取样式所在文件系统的可用字节数和总字节数。"""
        try:
            statistics = os.statvfs("/")
        except OSError:
            statistics = os.statvfs(".")
        block_size = statistics[0]
        return {
            "free_bytes": block_size * statistics[3],
            "total_bytes": block_size * statistics[2],
        }


COMMAND_STRATEGY = StyleListCommand()
