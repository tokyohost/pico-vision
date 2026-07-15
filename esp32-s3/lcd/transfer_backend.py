#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.
#
#  Any project, software, or derivative work that uses, modifies, links to,
#  or incorporates this software must make its complete source code publicly
#  available under the same license.
#
#  This software is provided "as is", without warranty of any kind.


"""提供可切换的兼容 SPI 与原生 DMA LCD 像素传输后端。"""


LCD_TRANSFER_BACKEND_AUTO = "auto"
LCD_TRANSFER_BACKEND_LEGACY = "legacy"
LCD_TRANSFER_BACKEND_NATIVE_DMA = "native_dma"
LCD_TRANSFER_BACKENDS = (
    LCD_TRANSFER_BACKEND_AUTO,
    LCD_TRANSFER_BACKEND_LEGACY,
    LCD_TRANSFER_BACKEND_NATIVE_DMA,
)
NATIVE_DMA_API_VERSION = 1
DEFAULT_DMA_CHUNK_SIZE = 4092


def normalize_lcd_transfer_backend(backend):
    """规范化 LCD 传输后端名称，并拒绝未知配置。"""
    normalized = str(backend or LCD_TRANSFER_BACKEND_AUTO).strip().lower()
    if normalized not in LCD_TRANSFER_BACKENDS:
        raise ValueError("未知 LCD 传输后端：{}".format(backend))
    return normalized


def _load_native_dma_module():
    """延迟导入固件原生 DMA 模块，允许旧固件继续使用兼容后端。"""
    return __import__("fn_lcd")


class LegacySpiTransferBackend:
    """使用 ``machine.SPI.write`` 保留升级前的 LCD 像素传输行为。"""

    name = LCD_TRANSFER_BACKEND_LEGACY

    def write(self, spi, pixels):
        """通过 MicroPython 标准 SPI 接口同步写入像素缓冲区。"""
        spi.write(pixels)
        return len(pixels)

    def stats(self):
        """返回兼容后端不包含原生事务统计的状态。"""
        return {
            "backend": self.name,
            "chunk_size": 0,
            "write_count": 0,
            "byte_count": 0,
            "transaction_count": 0,
        }


class NativeDmaTransferBackend:
    """使用内部 DMA 双缓冲向 ESP32-S3 SPI 外设提交像素数据。"""

    name = LCD_TRANSFER_BACKEND_NATIVE_DMA

    def __init__(self, chunk_size=DEFAULT_DMA_CHUNK_SIZE, native_module=None):
        """校验原生接口版本，并初始化内部 DMA 双缓冲。"""
        self._native = native_module or _load_native_dma_module()
        api_version = self._native.api_version()
        if api_version != NATIVE_DMA_API_VERSION:
            raise RuntimeError(
                "fn_lcd API 版本不兼容：{}".format(api_version)
            )
        self._chunk_size = int(self._native.init(int(chunk_size)))

    def write(self, spi, pixels):
        """把像素缓冲区交给原生 DMA 后端，并返回实际写入字节数。"""
        return self._native.write(spi, pixels)

    def stats(self):
        """返回原生 DMA 缓冲区和累计 SPI 事务统计。"""
        result = dict(self._native.stats())
        result["backend"] = self.name
        return result


def create_lcd_transfer_backend(
    backend=LCD_TRANSFER_BACKEND_AUTO,
    chunk_size=DEFAULT_DMA_CHUNK_SIZE,
    native_module=None,
):
    """根据配置创建 LCD 传输后端，自动模式允许旧固件安全回退。"""
    normalized = normalize_lcd_transfer_backend(backend)
    if normalized == LCD_TRANSFER_BACKEND_LEGACY:
        return LegacySpiTransferBackend()
    if normalized == LCD_TRANSFER_BACKEND_NATIVE_DMA:
        return NativeDmaTransferBackend(chunk_size, native_module)
    try:
        return NativeDmaTransferBackend(chunk_size, native_module)
    except (ImportError, AttributeError, OSError, RuntimeError, ValueError):
        return LegacySpiTransferBackend()
