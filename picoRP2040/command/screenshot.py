"""实现 LCD 当前显示内容的分块截图命令。"""

import binascii
import os

from command.base import CommandStrategy


class ScreenshotCommand(CommandStrategy):
    """把当前 LCD 画面以大端 RGB565 条带连续返回给 Monitor。"""

    name = "screenshot"
    temporary_path = ".screenshot.rgb565.tmp"

    def execute(self, params, context):
        """借助 Flash 暂存画面，再以单行小块发送并清理临时文件。"""
        renderer = context.service("renderer")

        try:
            with open(self.temporary_path, "wb") as temporary_file:
                def cache_chunk(sequence, y, height, pixels):
                    """把渲染条带直接写入 Flash，不在堆中拼接完整帧。"""
                    del sequence, y, height
                    temporary_file.write(pixels)

                metadata = renderer.capture_screen(
                    cache_chunk,
                    params.get("rows_per_chunk", 8),
                )

            width = int(metadata["width"])
            height = int(metadata["height"])
            row_size = width * 2
            with open(self.temporary_path, "rb") as temporary_file:
                for sequence in range(height):
                    pixels = temporary_file.read(row_size)
                    if len(pixels) != row_size:
                        raise ValueError("SCREENSHOT_CACHE_INCOMPLETE")
                    context.respond(
                        "chunk",
                        self.name,
                        {
                            "sequence": sequence,
                            "y": sequence,
                            "height": 1,
                            "pixels": binascii.b2a_base64(pixels).strip().decode("ascii"),
                        },
                        context.request_id,
                    )
            metadata["chunks"] = height
            return metadata
        finally:
            try:
                os.remove(self.temporary_path)
            except OSError:
                pass


COMMAND_STRATEGY = ScreenshotCommand()
