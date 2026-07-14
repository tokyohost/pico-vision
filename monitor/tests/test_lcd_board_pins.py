"""验证 LCD 工厂按开发板型号选择八针屏 GPIO 档案。"""


import sys
import types
import unittest
from pathlib import Path


PICO_ROOT = Path(__file__).resolve().parents[2] / "picoRP2040"
if str(PICO_ROOT) not in sys.path:
    sys.path.insert(0, str(PICO_ROOT))


class FakePin:
    """记录 LCD 初始化时使用的 GPIO 编号。"""

    OUT = 1

    def __init__(self, identifier, mode=None, value=None):
        """保存 GPIO 编号、工作模式和初始电平。"""
        self.identifier = int(identifier)
        self.mode = mode
        self.initial_value = value

    def value(self, level=None):
        """读写模拟 GPIO 电平。"""
        if level is not None:
            self.initial_value = level
        return self.initial_value


class FakePwm:
    """记录背光 PWM 使用的 GPIO 与参数。"""

    def __init__(self, pin):
        """保存 PWM 对应的模拟 GPIO。"""
        self.pin = pin
        self.frequency = None
        self.duty = None

    def freq(self, frequency):
        """保存 PWM 频率。"""
        self.frequency = int(frequency)

    def duty_u16(self, duty):
        """保存十六位 PWM 占空比。"""
        self.duty = int(duty)


class FakeSpi:
    """记录 LCD 初始化时选择的 SPI 控制器和信号脚。"""

    def __init__(self, identifier, **parameters):
        """保存 SPI 控制器编号与初始化参数。"""
        self.identifier = int(identifier)
        self.parameters = parameters

    def write(self, data):
        """忽略测试期间的模拟 SPI 数据。"""
        del data


class LcdBoardPinsTest(unittest.TestCase):
    """确认 RP2040 与 ESP32-S3 使用各自的八针屏脚位。"""

    @classmethod
    def setUpClass(cls):
        """安装 machine 模块替身并载入 LCD 工厂。"""
        cls._original_machine = sys.modules.get("machine")
        sys.modules["machine"] = types.SimpleNamespace(
            Pin=FakePin,
            PWM=FakePwm,
            SPI=FakeSpi,
        )
        from lcd.factory import create_lcd_device

        cls.create_lcd_device = staticmethod(create_lcd_device)

    @classmethod
    def tearDownClass(cls):
        """恢复测试前的 machine 模块状态。"""
        if cls._original_machine is None:
            sys.modules.pop("machine", None)
        else:
            sys.modules["machine"] = cls._original_machine

    def test_esp32_s3_uses_spi_id_2_eight_pin_profile(self):
        """ESP32-S3 的两种八针屏都应使用 GPIO11 至 GPIO14 信号组。"""
        for device_type in (
            "st7789-2inch-8pin-a",
            "st7789-2.4inch-8pin-b",
        ):
            with self.subTest(device_type=device_type):
                device = self.create_lcd_device(device_type, "ESP32-S3")
                profile = device.pin_profile
                self.assertEqual(2, profile.spi_id)
                self.assertEqual(10_000_000, profile.baudrate)
                self.assertEqual(15, profile.miso)
                self.assertEqual(15, device.spi.parameters["miso"].identifier)
                self.assertEqual((12, 11, 10, 9, 14, 13), (
                    profile.sck,
                    profile.mosi,
                    profile.cs,
                    profile.dc,
                    profile.rst,
                    profile.bl,
                ))

    def test_rp2040_keeps_existing_eight_pin_profile(self):
        """RP2040 的两种八针屏应继续使用原有 GPIO 映射。"""
        for board_model in ("rp2040_usb", "rp2040_typec"):
            with self.subTest(board_model=board_model):
                device = self.create_lcd_device(
                    "st7789-2inch-8pin-a",
                    board_model,
                )
                profile = device.pin_profile
                self.assertEqual(0, profile.spi_id)
                self.assertEqual(40_000_000, profile.baudrate)
                self.assertIsNone(profile.miso)
                self.assertNotIn("miso", device.spi.parameters)
                self.assertEqual((6, 7, 8, 14, 15, 26), (
                    profile.sck,
                    profile.mosi,
                    profile.cs,
                    profile.dc,
                    profile.rst,
                    profile.bl,
                ))

    def test_esp32_s3_rejects_unsupported_ten_pin_profile(self):
        """ESP32-S3 选择未适配的十针屏时应明确拒绝启动。"""
        with self.assertRaisesRegex(ValueError, "不支持开发板"):
            self.create_lcd_device("st7789-2.4inch-10pin-a", "esp32-s3")


if __name__ == "__main__":
    unittest.main()
