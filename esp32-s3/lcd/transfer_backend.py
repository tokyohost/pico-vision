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
NATIVE_DMA_API_VERSION = 2
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

    def configure(self, configuration):
        """接受统一画布配置接口，兼容后端无需分配固件缓冲。"""
        del configuration

    def write(self, spi, pixels):
        """通过 MicroPython 标准 SPI 接口同步写入像素缓冲区。"""
        spi.write(pixels)
        return len(pixels)

    def dirty_regions(self, frame, force=False):
        """兼容后端无法自动比较画布，因此每帧返回整个画布占位区域。"""
        del frame, force
        raise RuntimeError("兼容 SPI 后端不支持 C 固件脏区检测")

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
    """使用 C 侧脏区检测、双条带和 DMA 双缓冲提交完整画布。"""

    name = LCD_TRANSFER_BACKEND_NATIVE_DMA

    def __init__(self, configuration, native_module=None):
        """校验原生接口版本，并传入屏幕、脚位和全部缓冲参数。"""
        self._native = native_module or _load_native_dma_module()
        api_version = self._native.api_version()
        if api_version != NATIVE_DMA_API_VERSION:
            raise RuntimeError(
                "fn_lcd API 版本不兼容：{}".format(api_version)
            )
        self._configuration = dict(configuration)
        self._chunk_size = int(self._native.init(self._configuration))

    def configure(self, configuration):
        """在横竖屏或样式尺寸变化后重建匹配的 C 固件缓冲。"""
        next_configuration = dict(configuration)
        if next_configuration == self._configuration:
            return False
        self._chunk_size = int(self._native.init(next_configuration))
        self._configuration = next_configuration
        return True

    def write(self, spi, pixels):
        """保留启动清屏等旧局部刷新所需的连续像素 DMA 写入。"""
        return self._native.write(spi, pixels)

    def dirty_regions(self, frame, force=False):
        """让 C 固件检测并记录完整画布中的变化矩形。"""
        return self._native.dirty_regions(frame, bool(force))

    def write_region(self, spi, frame, x, y, width, height):
        """让 C 固件用双条带缓冲提取并发送指定脏矩形。"""
        return self._native.write_region(
            spi, frame, x, y, width, height
        )

    def commit_frame(self):
        """提交成功发送的画布哈希，使其成为下一帧比较基线。"""
        self._native.commit_frame()

    def discard_frame(self):
        """放弃未完整发送的画布，不污染已经显示的哈希基线。"""
        self._native.discard_frame()

    def stats(self):
        """返回原生 DMA 缓冲区和累计 SPI 事务统计。"""
        result = dict(self._native.stats())
        result["backend"] = self.name
        return result


def create_lcd_transfer_backend(
    backend=LCD_TRANSFER_BACKEND_AUTO,
    configuration=None,
    native_module=None,
):
    """根据配置创建 LCD 传输后端，自动模式允许旧固件安全回退。"""
    normalized = normalize_lcd_transfer_backend(backend)
    native_configuration = dict(configuration or {})
    native_configuration.setdefault("dma_chunk_size", DEFAULT_DMA_CHUNK_SIZE)
    if normalized == LCD_TRANSFER_BACKEND_LEGACY:
        return LegacySpiTransferBackend()
    if normalized == LCD_TRANSFER_BACKEND_NATIVE_DMA:
        return NativeDmaTransferBackend(native_configuration, native_module)
    try:
        return NativeDmaTransferBackend(native_configuration, native_module)
    except (
        ImportError, AttributeError, KeyError,
        OSError, RuntimeError, ValueError,
    ):
        return LegacySpiTransferBackend()
