"""验证 ESP32-S3 LCD 屏幕档案自动发现和十针屏脚位定义。"""

import sys
import types
import unittest
from pathlib import Path


ESP32_ROOT = Path(__file__).resolve().parents[1]
if str(ESP32_ROOT) not in sys.path:
    sys.path.insert(0, str(ESP32_ROOT))

if "machine" not in sys.modules:
    machine = types.ModuleType("machine")

    class Pin:
        """模拟 MicroPython Pin 构造，供导入 LCD 基类使用。"""

        OUT = 1

        def __init__(self, pin, mode=None, value=None):
            """保存测试传入的 GPIO 编号、模式和初始电平。"""
            self.pin = pin
            self.mode = mode
            self._value = value

        def value(self, value=None):
            """读取或更新模拟 GPIO 电平。"""
            if value is None:
                return self._value
            self._value = value

    class PWM:
        """模拟 MicroPython PWM 类型，测试只需要完成导入。"""

        def __init__(self, pin):
            """保存绑定的模拟 Pin 对象。"""
            self.pin = pin

        def freq(self, value):
            """记录 PWM 频率。"""
            self.frequency = value

        def duty_u16(self, value):
            """记录 PWM 占空比。"""
            self.duty = value

    class SPI:
        """模拟 MicroPython SPI 类型，测试只需要完成导入。"""

        def __init__(self, spi_id, **parameters):
            """保存 SPI 编号和初始化参数。"""
            self.spi_id = spi_id
            self.parameters = parameters

        def write(self, data):
            """接受 SPI 写入数据。"""
            self.last_write = bytes(data)

    machine.Pin = Pin
    machine.PWM = PWM
    machine.SPI = SPI
    sys.modules["machine"] = machine


from color_manager import get_color_profile
from lcd.factory import available_lcd_device_types, get_lcd_panel_profile
from lcd.st7789_2_4inch_10pin_a import St7789TwoPointFourInch10PinADevice


class LcdProfilesTest(unittest.TestCase):
    """确认新增十针 LCD 可以被工厂扫描并保持 ESP32-S3 固定脚位。"""

    def test_ten_pin_profile_is_discovered(self):
        """工厂自动发现结果必须包含十针屏规范型号。"""
        self.assertIn(
            "st7789-2.4inch-10pin-a",
            available_lcd_device_types(),
        )

    def test_ten_pin_alias_resolves_to_panel_profile(self):
        """兼容别名必须解析到同一个十针屏面板档案。"""
        panel = get_lcd_panel_profile("st7789_2_4inch_10pin")

        self.assertEqual(panel.device_type, "st7789-2.4inch-10pin-a")
        self.assertEqual(panel.pin_count, 10)
        self.assertEqual((panel.width, panel.height), (240, 320))

    def test_ten_pin_esp32_s3_pins_and_backlight(self):
        """十针屏必须使用 ESP32-S3 固定 SPI2 脚位和外置低端背光方案。"""
        pins = St7789TwoPointFourInch10PinADevice.pin_profile

        self.assertEqual(pins.spi_id, 2)
        self.assertEqual(
            (pins.sck, pins.mosi, pins.cs, pins.dc, pins.rst),
            (12, 11, 10, 9, 14),
        )
        self.assertEqual(pins.miso, 15)
        self.assertEqual(pins.backlight.mode, "external_low_side")
        self.assertEqual(pins.backlight.control_pin, 13)
        self.assertTrue(pins.backlight.active_high)
        self.assertEqual(pins.signal_label("dc"), "RS")

    def test_ten_pin_panel_enables_color_inversion(self):
        """十针 A 款屏必须开启控制器反色并保持 RGB 像素顺序。"""
        panel = St7789TwoPointFourInch10PinADevice.panel_profile
        color_profile = get_color_profile(panel.color_profile_name)

        self.assertEqual(color_profile.name, "st7789_2_4inch_10pin_a")
        self.assertEqual(color_profile.inversion_command(), 0x21)
        self.assertEqual(color_profile.madctl_color_bits(), 0x00)


if __name__ == "__main__":
    unittest.main()
