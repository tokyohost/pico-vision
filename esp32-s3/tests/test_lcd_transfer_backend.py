"""验证 ESP32-S3 LCD 兼容 SPI 与原生 DMA 传输后端。"""

import sys
import unittest
from pathlib import Path
from unittest import mock


ESP32_ROOT = Path(__file__).resolve().parents[1]
LCD_ROOT = ESP32_ROOT / "lcd"
if str(LCD_ROOT) not in sys.path:
    sys.path.insert(0, str(LCD_ROOT))

import transfer_backend


class FakeSpi:
    """记录兼容后端提交的数据，模拟 ``machine.SPI``。"""

    def __init__(self):
        """创建空的 SPI 写入记录。"""
        self.writes = []

    def write(self, data):
        """保存一次兼容 SPI 写入的数据副本。"""
        self.writes.append(bytes(data))


class FakeNativeLcd:
    """模拟接口版本正确的 fn_lcd 原生模块。"""

    def __init__(self, api_version=2, init_error=None):
        """保存接口版本、初始化异常和调用记录。"""
        self._api_version = api_version
        self._init_error = init_error
        self.initialized = []
        self.writes = []
        self.pending_regions = [(0, 0, 2, 1)]
        self.committed = 0
        self.discarded = 0

    def api_version(self):
        """返回测试指定的原生模块接口版本。"""
        return self._api_version

    def init(self, configuration):
        """记录屏幕与脚位配置，或抛出测试指定的初始化异常。"""
        if self._init_error is not None:
            raise self._init_error
        self.initialized.append(dict(configuration))
        return min(4092, configuration["dma_chunk_size"])

    def dirty_regions(self, frame, force=False):
        """记录完整画布检测请求并返回模拟脏矩形。"""
        self.last_scan = (bytes(frame), bool(force))
        return list(self.pending_regions)

    def write(self, spi, pixels):
        """记录兼容局部刷新接口收到的连续像素。"""
        return len(pixels)

    def write_region(self, spi, frame, x, y, width, height):
        """记录 C 固件从完整画布提取并发送的脏矩形。"""
        self.writes.append((spi, bytes(frame), x, y, width, height))
        return width * height * 2

    def commit_frame(self):
        """记录成功帧哈希基线提交次数。"""
        self.committed += 1

    def discard_frame(self):
        """记录失败帧被放弃的次数。"""
        self.discarded += 1

    def stats(self):
        """返回与固件原生模块一致的累计统计结构。"""
        return {
            "chunk_size": 4092,
            "write_count": len(self.writes),
            "byte_count": sum(item[4] * item[5] * 2 for item in self.writes),
            "transaction_count": len(self.writes),
        }


class LcdTransferBackendTest(unittest.TestCase):
    """确认旧后端可回退，新后端不改变上层像素缓冲接口。"""

    def test_legacy_backend_uses_machine_spi_write(self):
        """兼容后端必须保留原有 ``machine.SPI.write`` 行为。"""
        spi = FakeSpi()
        backend = transfer_backend.create_lcd_transfer_backend("legacy")

        self.assertEqual(backend.write(spi, b"\x12\x34"), 2)
        self.assertEqual(spi.writes, [b"\x12\x34"])
        self.assertEqual(backend.name, "legacy")

    def test_native_dma_backend_delegates_to_fn_lcd(self):
        """原生后端必须传递硬件方案并按脏矩形发送完整画布。"""
        spi = FakeSpi()
        native = FakeNativeLcd()
        configuration = {
            "width": 2,
            "height": 1,
            "spi_id": 2,
            "sck": 12,
            "mosi": 11,
            "cs": 10,
            "dc": 9,
            "rst": 14,
            "backlight": 13,
            "baudrate": 40_000_000,
            "dma_chunk_size": 4092,
        }
        backend = transfer_backend.create_lcd_transfer_backend(
            "native_dma", configuration, native
        )

        frame = b"\xAB\xCD\x12\x34"
        self.assertEqual(backend.dirty_regions(frame), [(0, 0, 2, 1)])
        self.assertEqual(backend.write_region(spi, frame, 0, 0, 2, 1), 4)
        backend.commit_frame()
        self.assertEqual(native.initialized, [configuration])
        self.assertEqual(native.writes, [(spi, frame, 0, 0, 2, 1)])
        self.assertEqual(native.committed, 1)
        self.assertEqual(backend.stats()["backend"], "native_dma")

    def test_auto_backend_falls_back_when_native_module_is_missing(self):
        """自动模式在旧固件没有 fn_lcd 时必须安全回退。"""
        with mock.patch.object(
            transfer_backend,
            "_load_native_dma_module",
            side_effect=ImportError("missing"),
        ):
            backend = transfer_backend.create_lcd_transfer_backend("auto")

        self.assertEqual(backend.name, "legacy")

    def test_auto_backend_falls_back_when_dma_allocation_fails(self):
        """自动模式在内部 DMA RAM 不足时必须使用兼容后端。"""
        native = FakeNativeLcd(init_error=OSError("no dma memory"))
        backend = transfer_backend.create_lcd_transfer_backend(
            "auto", {"dma_chunk_size": 4092}, native_module=native
        )

        self.assertEqual(backend.name, "legacy")

    def test_explicit_native_backend_rejects_incompatible_api(self):
        """显式原生模式必须暴露固件版本不匹配，不能静默降级。"""
        with self.assertRaisesRegex(RuntimeError, "API 版本不兼容"):
            transfer_backend.create_lcd_transfer_backend(
                "native_dma", native_module=FakeNativeLcd(api_version=1)
            )

    def test_unknown_backend_is_rejected(self):
        """未知后端名称必须在 LCD 初始化前给出明确错误。"""
        with self.assertRaisesRegex(ValueError, "未知 LCD 传输后端"):
            transfer_backend.create_lcd_transfer_backend("fastest")

    def test_native_source_uses_two_internal_dma_buffers(self):
        """原生实现必须使用内部 DMA RAM，且不得在事务间释放 GIL。"""
        repository_root = ESP32_ROOT.parents[1]
        dma_source = (
            repository_root
            / "micropython/ports/esp32/usermod/fn_lcd/fn_lcd_dma.c"
        ).read_text(encoding="utf-8")
        dma_header = (
            repository_root
            / "micropython/ports/esp32/usermod/fn_lcd/fn_lcd_dma.h"
        ).read_text(encoding="utf-8")

        self.assertIn("FN_LCD_DMA_BUFFER_COUNT (2)", dma_header)
        self.assertIn("FN_LCD_STRIP_BUFFER_COUNT (2)", dma_header)
        self.assertIn("MALLOC_CAP_INTERNAL", dma_source)
        self.assertIn("MALLOC_CAP_DMA", dma_source)
        self.assertIn("spi_device_queue_trans", dma_source)
        self.assertIn("fn_lcd_dma_scan_dirty", dma_source)
        self.assertIn("context->next_strip_buffer", dma_source)
        self.assertNotIn("MP_THREAD_GIL_EXIT", dma_source)


if __name__ == "__main__":
    unittest.main()
