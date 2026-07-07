"""验证 Pico LCD 截图命令的分块传输行为。"""

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_ROOT = PROJECT_ROOT / "picoRP2040"
sys.path.insert(0, str(FIRMWARE_ROOT))

from command.screenshot import ScreenshotCommand


class FakeRenderer:
    """模拟渲染器按两块输出固定 RGB565 像素。"""

    def capture_screen(self, writer, rows_per_chunk):
        """记录条带高度并发送两块测试像素。"""
        self.rows_per_chunk = rows_per_chunk
        writer(0, 0, 1, b"\xF8\x00\x07\xE0")
        writer(1, 1, 1, b"\x00\x1F\xFF\xFF")
        return {"width": 2, "height": 2, "pixel_format": "RGB565_BE", "chunks": 2}


class FakeContext:
    """模拟命令上下文并收集主动分块响应。"""

    request_id = "shot-1"

    def __init__(self, renderer):
        """保存渲染器和响应列表。"""
        self.renderer = renderer
        self.responses = []

    def service(self, name):
        """返回测试所需的渲染器服务。"""
        self.assert_service_name = name
        return self.renderer

    def respond(self, status, command, data, request_id):
        """记录截图命令发出的分块响应。"""
        self.responses.append((status, command, data, request_id))


class ScreenshotCommandTest(unittest.TestCase):
    """验证截图策略不会在 Pico 内存中拼接完整帧。"""

    def test_command_streams_base64_chunks_and_returns_metadata(self):
        """确认条带顺序、请求编号、编码内容和最终元数据均正确。"""
        renderer = FakeRenderer()
        context = FakeContext(renderer)

        result = ScreenshotCommand().execute({"rows_per_chunk": 4}, context)

        self.assertEqual("renderer", context.assert_service_name)
        self.assertEqual(4, renderer.rows_per_chunk)
        self.assertEqual(2, len(context.responses))
        self.assertEqual(("chunk", "screenshot"), context.responses[0][:2])
        self.assertEqual("shot-1", context.responses[0][3])
        self.assertEqual("+AAH4A==", context.responses[0][2]["pixels"])
        self.assertEqual(2, result["chunks"])
        self.assertEqual("RGB565_BE", result["pixel_format"])


if __name__ == "__main__":
    unittest.main()
