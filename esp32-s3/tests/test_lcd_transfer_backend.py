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

    def __init__(self, api_version=1, init_error=None):
        """保存接口版本、初始化异常和调用记录。"""
        self._api_version = api_version
        self._init_error = init_error
        self.initialized = []
        self.writes = []

    def api_version(self):
        """返回测试指定的原生模块接口版本。"""
        return self._api_version

    def init(self, chunk_size):
        """记录 DMA 容量，或抛出测试指定的初始化异常。"""
        if self._init_error is not None:
            raise self._init_error
        self.initialized.append(chunk_size)
        return min(4092, chunk_size)

    def write(self, spi, pixels):
        """记录原生后端收到的 SPI 对象和像素数据。"""
        self.writes.append((spi, bytes(pixels)))
        return len(pixels)

    def stats(self):
        """返回与固件原生模块一致的累计统计结构。"""
        return {
            "chunk_size": 4092,
            "write_count": len(self.writes),
            "byte_count": sum(len(item[1]) for item in self.writes),
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
        """原生后端必须初始化双缓冲并转交同一个 SPI 对象。"""
        spi = FakeSpi()
        native = FakeNativeLcd()
        backend = transfer_backend.create_lcd_transfer_backend(
            "native_dma", 4092, native
        )

        self.assertEqual(backend.write(spi, b"\xAB\xCD"), 2)
        self.assertEqual(native.initialized, [4092])
        self.assertEqual(native.writes, [(spi, b"\xAB\xCD")])
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
            "auto", native_module=native
        )

        self.assertEqual(backend.name, "legacy")

    def test_explicit_native_backend_rejects_incompatible_api(self):
        """显式原生模式必须暴露固件版本不匹配，不能静默降级。"""
        with self.assertRaisesRegex(RuntimeError, "API 版本不兼容"):
            transfer_backend.create_lcd_transfer_backend(
                "native_dma", native_module=FakeNativeLcd(api_version=2)
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
        self.assertIn("MALLOC_CAP_INTERNAL", dma_source)
        self.assertIn("MALLOC_CAP_DMA", dma_source)
        self.assertIn("spi_device_queue_trans", dma_source)
        self.assertNotIn("MP_THREAD_GIL_EXIT", dma_source)


if __name__ == "__main__":
    unittest.main()
