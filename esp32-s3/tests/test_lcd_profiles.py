"""验证 ESP32-S3 LCD 屏幕档案自动发现和十针屏脚位定义。"""

import sys
import types
import unittest
from pathlib import Path
from unittest import mock


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
from lcd.factory import (
    available_lcd_device_types,
    create_lcd_device,
    get_lcd_panel_profile,
)
from lcd.st7789_2_4inch_10pin_a import St7789TwoPointFourInch10PinADevice
from lcd.st7789_2_4inch_10pin_backpcb import (
    St7789TwoPointFourInch10PinBackPcbDevice,
)


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


class BackPcbLcdProfilesTest(unittest.TestCase):
    """确认 V3 背板屏幕的接口、背光与两种传输后端一致。"""

    def test_backpcb_is_discovered_and_alias_resolves(self):
        """规范型号和下划线别名应指向相同的二点四英寸十针屏。"""
        self.assertIn(
            "st7789-2.4inch-10pin-backpcb", available_lcd_device_types()
        )
        panel = get_lcd_panel_profile("st7789-2.4inch-10pin-backpcb")
        self.assertIs(
            panel, get_lcd_panel_profile("st7789_2_4inch_10pin_backpcb")
        )
        self.assertEqual((panel.width, panel.height, panel.pin_count), (240, 320, 10))
        self.assertEqual((panel.x_offset, panel.y_offset), (0, 0))
        color = get_color_profile(panel.color_profile_name)
        self.assertEqual(color.inversion_command(), 0x21)
        self.assertEqual(color.madctl_color_bits(), 0x00)

    def test_backpcb_connector_and_gpio_match_pcb(self):
        """J1 屏幕座脚序及 J3 引出的 GPIO 必须符合背板实际网络。"""
        pins = St7789TwoPointFourInch10PinBackPcbDevice.pin_profile
        self.assertEqual(pins.spi_id, 2)
        self.assertEqual(pins.baudrate, 40_000_000)
        self.assertEqual(
            (pins.sck, pins.mosi, pins.cs, pins.dc, pins.rst, pins.bl, pins.miso),
            (7, 15, 6, 5, 4, 16, 17),
        )
        self.assertEqual(
            pins.connector_pins,
            ("LED-", "LED+", "GND", "VDD", "SDA", "CS", "DC", "SCL", "RST", "GND"),
        )
        self.assertEqual(pins.signal_label("sck"), "SCL")
        self.assertEqual(pins.signal_label("mosi"), "SDA")
        # 加入 J2 三键后，全部被占用 GPIO 仍应互不重复。
        used_pins = (
            pins.sck, pins.mosi, pins.cs, pins.dc, pins.rst,
            pins.bl, pins.miso, 1, 2, 42,
        )
        self.assertEqual(len(set(used_pins)), len(used_pins))

    def test_backpcb_backlight_uses_active_high_low_side_driver(self):
        """Q1 的栅极应在初始化时为低，亮度增加时提高 GPIO16 的占空比。"""
        backlight = St7789TwoPointFourInch10PinBackPcbDevice.pin_profile.backlight
        self.assertEqual(backlight.mode, "external_low_side")
        self.assertEqual(backlight.control_pin, 16)
        self.assertTrue(backlight.active_high)
        self.assertEqual(backlight.off_level(), 0)
        self.assertEqual(backlight.duty_for_brightness(0), 0)
        self.assertEqual(backlight.duty_for_brightness(100), 65535)

    def test_backpcb_spi_and_native_backend_receive_board_pins(self):
        """实际创建设备时，兼容 SPI 与原生 DMA 均应接收背板脚位。"""
        for backend in ("legacy", "native_dma"):
            native = types.SimpleNamespace(
                api_version=mock.Mock(return_value=2),
                init=mock.Mock(return_value=4092),
            )
            with self.subTest(backend=backend), mock.patch(
                "lcd.base.LCD_TRANSFER_BACKEND", backend
            ), mock.patch(
                "lcd.transfer_backend._load_native_dma_module", return_value=native
            ):
                device = create_lcd_device("st7789-2.4inch-10pin-backpcb")
            self.assertEqual(device.spi.spi_id, 2)
            self.assertEqual(device.spi.parameters["baudrate"], 40_000_000)
            self.assertEqual(device.spi.parameters["sck"].pin, 7)
            self.assertEqual(device.spi.parameters["mosi"].pin, 15)
            self.assertEqual(device.spi.parameters["miso"].pin, 17)
            self.assertEqual((device.cs.pin, device.dc.pin, device.rst.pin), (6, 5, 4))
            self.assertEqual(device.bl.pin.pin, 16)
            self.assertEqual(device.bl.duty, 0)
            self.assertEqual(device.transfer_backend_name(), backend)
            if backend == "native_dma":
                native.init.assert_called_once()
                configuration = native.init.call_args.args[0]
                expected = {
                    "device_type": "st7789-2.4inch-10pin-backpcb",
                    "width": 240, "height": 320,
                    "x_offset": 0, "y_offset": 0,
                    "spi_id": 2, "sck": 7, "mosi": 15, "miso": 17,
                    "cs": 6, "dc": 5, "rst": 4, "backlight": 16,
                    "baudrate": 40_000_000,
                }
                for key, value in expected.items():
                    self.assertEqual(configuration[key], value)
            else:
                native.init.assert_not_called()


if __name__ == "__main__":
    unittest.main()
