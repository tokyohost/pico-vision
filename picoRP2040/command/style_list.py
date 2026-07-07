"""实现自定义屏幕样式清单查询命令。"""

from command.base import CommandStrategy


class StyleListCommand(CommandStrategy):
    """返回 Pico 当前可识别的自定义样式元数据。"""

    name = "style.list"

    def execute(self, params, context):
        """扫描 customStyles 目录并返回 type 为 custom 的样式。"""
        del params, context
        from styles.style_plugins import custom_style_catalog
        return {"styles": custom_style_catalog()}


COMMAND_STRATEGY = StyleListCommand()
