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



"""集中定义 RP2040 与 ESP32-S3 运行方案和通信协议参数。"""


# 开发板型号：可配置为 rp2040_usb、rp2040_typec 或 ESP32-S3。
# ESP32-S3 档案默认使用 GPIO48 的板载 WS2812；具体引脚由开发板档案管理。
BOARD_MODEL = "ESP32-S3"
# 开发源码使用 development；正式升级包由打包工具写入发布版本。
FIRMWARE_VERSION = "development"
# LCD 屏幕方案：具体分辨率、色彩、显存偏移和 GPIO 均由 lcd 目录中的档案定义。
LCD_DEVICE_TYPE = "st7789-2.4inch-8pin-b"


# LCD 通用刷新参数。
LCD_STRIP_HEIGHT = 40
# 未收到新 JSON 时仍使用缓存快照主动刷新的最大间隔，保证至少一帧每秒。
RENDER_INTERVAL_MS = 1000
LCD_STYLE = "disk"
# 每累计分配指定字节数后主动执行垃圾回收，降低长期运行时的堆碎片。
GC_ALLOCATION_THRESHOLD = 16 * 1024
# 在系统启动页阶段预编译大型内置样式，避免连接后在碎片化堆上首次导入。
LCD_BOOT_PRELOAD_STYLES = ("horizontal_disk4x_qb",)


# JSON 数据包限制与单次读取预算。
MAX_JSON_SIZE = 16 * 1024
SERIAL_READ_BUDGET = 2048

# 后盖三按键使用 GP1、GP2、GP3，避开全部八针/十针 LCD 与两种板载状态灯。
# 按键默认一端接 GPIO、另一端共接 GND，并使用 RP2040 内部上拉。
PIN_BUTTON_STYLE_PREVIOUS = 1
PIN_BUTTON_STYLE_NEXT = 2
PIN_BUTTON_FUNCTION = 3
BUTTON_ACTIVE_LOW = True
BUTTON_DEBOUNCE_MS = 60

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
# 是否启用 Wi-Fi 与 WebSocket 传输；设为 False 时完全不初始化无线网卡。
WIFI_ENABLED = False
# Wi-Fi WebSocket 服务参数；Monitor 默认连接 ws://设备IP:8765/pv1。
WEBSOCKET_PORT = 8765
WEBSOCKET_PATH = "/pv1"
# 连续缺失多少个 Monitor 采集周期后返回系统启动等待页。
MONITOR_TIMEOUT_INTERVALS = 10
# 每接收多少份 Monitor 快照，使用主机时间重新校准一次本地推进基准。
TIME_CALIBRATION_SNAPSHOTS = 20
# Pico 推进时间与主机运行时间的允许误差；误差不超过该值时保持原基准。
TIME_CALIBRATION_TOLERANCE_SECONDS = 2

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


def _load_runtime_configuration():
    """从持久化文件加载允许覆盖的运行配置。"""
    try:
        import ujson as runtime_json
    except ImportError:
        import json as runtime_json
    try:
        with open("runtime_config.json", "r") as source:
            values = runtime_json.loads(source.read())
    except (OSError, ValueError):
        return
    allowed = {
        "BOARD_MODEL": str,
        "WIFI_ENABLED": bool,
        "LCD_STYLE": str,
        "RENDER_INTERVAL_MS": int,
        "MONITOR_TIMEOUT_INTERVALS": int,
        "TIME_CALIBRATION_SNAPSHOTS": int,
        "TIME_CALIBRATION_TOLERANCE_SECONDS": int,
        "LED_BRIGHTNESS": int,
        "PIN_BUTTON_STYLE_PREVIOUS": int,
        "PIN_BUTTON_STYLE_NEXT": int,
        "PIN_BUTTON_FUNCTION": int,
        "BUTTON_ACTIVE_LOW": bool,
        "BUTTON_DEBOUNCE_MS": int,
    }
    for name, expected_type in allowed.items():
        if name in values:
            globals()[name] = expected_type(values[name])


_load_runtime_configuration()

# 无线传输仅允许 ESP32-S3 启用，防止 RP2040 的旧运行配置误开 Wi-Fi 后
# 导入不存在的 network 模块或占用紧张的堆内存。
WIFI_ENABLED = bool(
    WIFI_ENABLED
    and str(BOARD_MODEL).strip().lower().replace("_", "-") == "esp32-s3"
)
