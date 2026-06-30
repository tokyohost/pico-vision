"""集中管理 Pico 屏幕、引脚、协议和颜色配置。"""

# LCD 显示区域尺寸及单帧 RGB565 数据长度。
WIDTH = 240
HEIGHT = 320
FRAME_SIZE = WIDTH * HEIGHT * 2

# 仪表盘刷新周期、JSON 数据包最大长度。
RENDER_INTERVAL_MS = 500
MAX_JSON_SIZE = 16 * 1024

# ST7789 屏幕的 SPI 与控制引脚。
PIN_SCK = 18
PIN_MOSI = 19
PIN_CS = 17
PIN_DC = 16
PIN_RST = 20
PIN_BL = 21

# RP2040 板载 WS2812 数据引脚，本开发板的灯珠数据线连接 GPIO22。
PIN_LED = 22

# WS2812 灯珠数量；板载仅有一颗灯珠，因此配置为 1。
LED_COUNT = 1
# 绿灯亮度，取值范围为 0～255；数值越大亮度和功耗越高。
LED_BRIGHTNESS = 10
# 绿灯单次点亮时长，单位为毫秒；200 表示点亮 0.2 秒。
LED_ON_DURATION_MS = 200

# 绿灯单次熄灭时长，单位为毫秒；1500 表示熄灭 1.5 秒。
LED_OFF_DURATION_MS = 1500

# 成功接收一包数据时蓝灯的点亮时长，单位为毫秒。
LED_DATA_PULSE_DURATION_MS = 100

# LCD 显示区域相对于显存原点的坐标偏移。
X_OFFSET = 0
Y_OFFSET = 0

# 设备握手标识、屏幕驱动名称及像素格式。
DEVICE_NAME = "PICO_LCD"
LCD_DRIVER = "ST7789"
PIXEL_FORMAT = "RGB565"

# USB 串口握手内容及 JSON 数据包魔数。
PING_TEXT = b"PING:PICO_LCD?"
JSON_MAGIC = b"JSN0"

# 仪表盘使用的 RGB565 调色板。
BLACK = 0x0000
WHITE = 0xE71C
GRAY = 0x5ACB
DARK = 0x18E3
BLUE = 0x1CBF
GREEN = 0x46E9
YELLOW = 0xFE00
PURPLE = 0x9ADF
RED = 0xF9C7
