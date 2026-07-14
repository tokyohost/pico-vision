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



"""定义 LCD 脚位档案和屏幕档案。"""


class LcdBacklightProfile:
    """统一描述八针 BL 与十针 LED 正负极背光控制方案。"""

    def __init__(
        self,
        mode,
        control_pin,
        active_high,
        positive_connection,
        negative_connection,
    ):
        """使用控制模式、PWM 脚位、有效极性和正负极连接创建背光档案。"""
        self.mode = str(mode)
        self.control_pin = int(control_pin)
        self.active_high = bool(active_high)
        self.positive_connection = positive_connection
        self.negative_connection = negative_connection

    @classmethod
    def pwm(cls, pin, active_high=True):
        """创建使用单个 BL 脚位进行 PWM 调光的八针屏背光档案。"""
        return cls("pwm", pin, active_high, "BL", "GND")

    @classmethod
    def led_pair(cls, positive_pin=None, negative_pin=None):
        """创建控制 LED+ 或 LED-、另一端固定接电源轨的十针屏背光档案。"""
        if (positive_pin is None) == (negative_pin is None):
            raise ValueError("LED 背光必须且只能指定一个 PWM 控制端")
        if positive_pin is not None:
            return cls("led_pair", positive_pin, True, "PWM", "GND")
        return cls("led_pair", negative_pin, False, "VDD", "PWM")

    @classmethod
    def external_low_side(cls, control_pin):
        """创建由 GPIO 驱动外部 MOSFET、从 LED- 低端调光的裸背光档案。"""
        return cls(
            "external_low_side",
            control_pin,
            True,
            "LIMITED_SUPPLY",
            "MOSFET_DRAIN",
        )

    def off_level(self):
        """返回创建 PWM GPIO 前用于关闭背光的静态电平。"""
        return 0 if self.active_high else 1

    def duty_for_brightness(self, brightness):
        """将零至一百的亮度百分比转换为符合有效极性的 PWM 占空比。"""
        normalized = max(0, min(100, int(brightness)))
        duty = round(65535 * normalized / 100)
        return duty if self.active_high else 65535 - duty


class LcdPinProfile:
    """描述 LCD 模组与开发板之间的信号脚位和排针定义。"""

    def __init__(
        self,
        spi_id,
        sck,
        mosi,
        cs,
        dc,
        rst,
        backlight,
        baudrate=40_000_000,
        connector_pins=(),
        signal_labels=None,
        miso=None,
    ):
        """使用信号 GPIO、背光极性和物理排针顺序创建脚位档案。"""
        self.spi_id = int(spi_id)
        self.sck = int(sck)
        self.mosi = int(mosi)
        self.cs = int(cs)
        self.dc = int(dc)
        self.rst = int(rst)
        if isinstance(backlight, LcdBacklightProfile):
            self.backlight = backlight
        else:
            # 兼容旧屏幕档案直接传入 BL GPIO 的写法。
            self.backlight = LcdBacklightProfile.pwm(backlight)
        self.bl = self.backlight.control_pin
        self.baudrate = int(baudrate)
        self.miso = None if miso is None else int(miso)
        self.connector_pins = tuple(connector_pins)
        self.signal_labels = dict(signal_labels or {})

    def signal_label(self, signal_name):
        """返回屏幕丝印使用的信号名称，未声明时返回内部规范名称。"""
        normalized_name = str(signal_name or "").strip().lower()
        return self.signal_labels.get(normalized_name, normalized_name.upper())


def create_eight_pin_board_profiles():
    """创建 RP2040 与 ESP32-S3 共用八针屏的板型脚位档案。"""
    rp2040_profile = LcdPinProfile(
        0,
        6,
        7,
        8,
        14,
        15,
        LcdBacklightProfile.pwm(26),
        connector_pins=(
            "GND", "VCC", "SCL", "SDA", "RES", "DC", "CS", "BL"
        ),
    )
    # ESP32-S3 的旧版 MicroPython 会给 SPI(2) 自动分配 GPIO13 作为 MISO，
    # 因此显式将未接屏幕的 MISO 放到 GPIO15，避免与 GPIO13 背光 PWM 冲突。
    # 杜邦线连接在 40 MHz 下容易产生信号完整性问题，默认降到稳定的 10 MHz。
    esp32_s3_profile = LcdPinProfile(
        2,
        12,
        11,
        10,
        9,
        14,
        LcdBacklightProfile.pwm(13),
        baudrate=40_000_000,
        connector_pins=(
            "GND", "VCC", "SCL", "SDA", "RES", "DC", "CS", "BL"
        ),
        miso=15,
    )
    return {
        "rp2040_usb": rp2040_profile,
        "rp2040_typec": rp2040_profile,
        "esp32-s3": esp32_s3_profile,
    }


class LcdPanelProfile:
    """描述 LCD 模组的尺寸、显存偏移和色彩方案。"""

    def __init__(
        self,
        device_type,
        chip,
        size,
        pin_count,
        batch,
        width,
        height,
        x_offset,
        y_offset,
        color_profile_name,
    ):
        """使用硬件型号、屏幕参数和色彩方案创建屏幕档案。"""
        self.device_type = device_type
        self.chip = chip
        self.size = size
        self.pin_count = int(pin_count)
        self.batch = batch
        self.width = int(width)
        self.height = int(height)
        self.x_offset = int(x_offset)
        self.y_offset = int(y_offset)
        self.color_profile_name = color_profile_name
