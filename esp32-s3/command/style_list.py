"""实现自定义屏幕样式清单查询命令。"""

import os

from command.base import CommandStrategy


class StyleListCommand(CommandStrategy):
    """返回设备当前可识别的自定义样式元数据。"""

    name = "style.list"

    def execute(self, params, context):
        """扫描自定义样式，并返回当前样式及设备 Flash 空间。"""
        del params
        from styles.style_plugins import custom_style_catalog
        renderer = context.service("renderer", required=False)
        return {
            "styles": custom_style_catalog(),
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
