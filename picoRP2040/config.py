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



"""集中定义 RP2040、ST7789、WS2812 和通信协议参数。"""


# 开发板型号：多色 WS2812 灯版本使用 rp2040_usb；GP25 单色灯版本使用
# rp2040_typec。具体引脚由开发板硬件档案统一管理。
BOARD_MODEL = "rp2040_typec"
# 开发源码使用 development；正式升级包由打包工具写入发布版本。
FIRMWARE_VERSION = "development"
# 屏幕色彩方案：旧款 ST7789VW 二英寸屏使用 st7789vw_2inch；新款
# 二点四英寸屏使用 st7789_2_4inch。当前默认选择新款屏幕。
SCREEN_COLOR_PROFILE = "st7789_2_4inch"


# ST7789 显示参数。
WIDTH = 240
HEIGHT = 320
LCD_STRIP_HEIGHT = 40
# 未收到新 JSON 时仍使用缓存快照主动刷新的最大间隔，保证至少一帧每秒。
RENDER_INTERVAL_MS = 1000
LCD_STYLE = "disk"


# JSON 数据包限制与单次读取预算。
MAX_JSON_SIZE = 16 * 1024
SERIAL_READ_BUDGET = 2048

# ST7789 的 SPI 与控制引脚。
PIN_SCK = 6
PIN_MOSI = 7
PIN_CS = 8
PIN_DC = 14
PIN_RST = 15
PIN_BL = 26
X_OFFSET = 0
Y_OFFSET = 0

# 板载状态灯公共时序参数。
LED_BRIGHTNESS = 10
LED_ON_DURATION_MS = 200
LED_OFF_DURATION_MS = 1500
LED_DATA_PULSE_DURATION_MS = 100

# USB 串口协议参数。
DEVICE_NAME = "PICO_LCD"
LCD_DRIVER = "ST7789"
PIXEL_FORMAT = "RGB565"
MAX_UPGRADE_LINE_SIZE = 1024
USB_CDC_RX_BUFFER_SIZE = 4096
USB_CDC_TX_BUFFER_SIZE = 1024
USB_CDC_ENUMERATION_TIMEOUT_MS = 5000

# RGB565 调色板。
BLACK = 0x0000
WHITE = 0xE71C
GRAY = 0x5ACB
DARK = 0x18E3
BLUE = 0x1CBF
GREEN = 0x46E9
YELLOW = 0xFE00
PURPLE = 0x9ADF
RED = 0xF9C7
