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



"""集中定义 ESP32-S3 固件运行方案和通信协议参数。"""


# 固件仅面向 ESP32-S3，不允许通过运行配置切换为其他开发板。
BOARD_MODEL = "ESP32-S3"
# 开发源码使用 development；正式升级包由打包工具写入发布版本。
FIRMWARE_VERSION = "development"
# LCD 屏幕方案：具体分辨率、色彩、显存偏移和 GPIO 均由 lcd 目录中的档案定义。
LCD_DEVICE_TYPE = "st7789-2.4inch-10pin-a"


# LCD 通用刷新参数。
# LCD 像素传输后端：auto 优先使用原生 DMA，旧固件缺少模块时自动回退 legacy。
LCD_TRANSFER_BACKEND = "auto"
# ESP32 machine.SPI 默认单笔事务上限为 4092 字节，原生后端使用等大的双缓冲。
LCD_DMA_CHUNK_SIZE = 4092
# C 固件使用两块内部 SRAM 条带缓冲交替整理完整画布中的脏矩形。
LCD_STRIP_HEIGHT = 40
# C 固件按瓦片检测完整画布变化，再把相邻瓦片合并为待发送脏矩形。
LCD_DIRTY_TILE_WIDTH = 16
LCD_DIRTY_TILE_HEIGHT = 8
# 新帧背压策略：latest 覆盖未消费旧帧，block 等待待处理槽释放。
RENDER_FRAME_POLICY = "latest"
# 未收到新 JSON 时仍使用缓存快照主动刷新的最大间隔，保证至少一帧每秒。
RENDER_INTERVAL_MS = 1000
# 本地时间显示的固定刷新周期，独立于监控数据采集周期。
CLOCK_REFRESH_INTERVAL_MS = 1000
# 主动垃圾回收的最小间隔，避免每帧回收造成周期性停顿。
GC_MIN_INTERVAL_MS = 5000
# 距离下一次时钟刷新小于该窗口时延后主动垃圾回收。
GC_CLOCK_GUARD_MS = 100
# 每轮最多刷新的区域数，防止单次主循环长期占用通信处理。
RENDER_MAX_REGIONS = 8
# 每轮渲染的软时间预算；单个区域完成后才检查，因此允许少量超时。
RENDER_TIME_BUDGET_US = 50 * 1000
# 是否启用第二阶段 Python 渲染工作线程；失败时自动回退同步服务。
RENDER_SERVICE_THREAD_ENABLED = True
# 渲染线程每轮只推进一个区域，及时检查控制队列和最新快照。
RENDER_WORKER_MAX_REGIONS = 5
# 渲染线程栈需覆盖样式插件、字体和 Canvas 的较深调用链。
RENDER_WORKER_STACK_SIZE = 32 * 1024
# 样式切换、旋转和截图等不可丢弃控制命令的固定队列容量。
RENDER_CONTROL_QUEUE_CAPACITY = 8
# 渲染线程启动和同步控制命令的最长等待时间。
RENDER_SERVICE_START_TIMEOUT_MS = 5000
RENDER_CONTROL_TIMEOUT_MS = 15000
LCD_STYLE = "disk"
# 利用 ESP32-S3 的 PSRAM 设置较大的累计分配阈值，降低自动 GC 频率。
GC_ALLOCATION_THRESHOLD = 256 * 1024
# 在系统启动页阶段预编译大型内置样式，避免连接后在碎片化堆上首次导入。
LCD_BOOT_PRELOAD_STYLES = ("horizontal_disk4x_qb",)


# JSON 数据包限制与单次读取预算。
MAX_JSON_SIZE = 16 * 1024
SERIAL_READ_BUDGET = 4096

# 后盖三按键使用 GP1、GP2、GP3，避开全部八针/十针 LCD 与两种板载状态灯。
# 按键默认一端接 GPIO、另一端共接 GND，并使用 ESP32-S3 内部上拉。
PIN_BUTTON_STYLE_PREVIOUS = 1
PIN_BUTTON_STYLE_NEXT = 2
PIN_BUTTON_FUNCTION = 3
BUTTON_ACTIVE_LOW = True
BUTTON_DEBOUNCE_MS = 60

# 板载状态灯公共时序参数。
LED_PIN = 48
LED_COUNT = 1
LED_BRIGHTNESS = 10
LED_ON_DURATION_MS = 200
LED_OFF_DURATION_MS = 1500
LED_DATA_PULSE_DURATION_MS = 100

# USB 串口协议参数。
DEVICE_NAME = "ESP32_S3_LCD"
LCD_DRIVER = "ST7789"
PIXEL_FORMAT = "RGB565"
MAX_UPGRADE_LINE_SIZE = 1024
# 内置 USB 控制台连续无活动达到该时长后释放当前会话。
USB_SESSION_TIMEOUT_MS = 5000
# 是否在原生 USB OTG 上注册保留 REPL 的独立 PV1 数据 CDC。
USB_DEDICATED_CDC_ENABLED = True
# 独立数据 CDC 的发送与接收环形缓冲区容量。
USB_CDC_TX_BUFFER_SIZE = 1024
# ESP-IDF 的 CDC 示例会及时读空 TinyUSB FIFO并投递到应用队列。这里的纯 Python
# CDC 也必须为业务解析、样式切换和渲染期间的突发数据保留至少两个最大 PV1 帧。
USB_CDC_RX_BUFFER_SIZE = 2 * (MAX_JSON_SIZE + 64)
# 是否启用 Wi-Fi 与 WebSocket 传输；设为 False 时完全不初始化无线网卡。
WIFI_ENABLED = True
# Wi-Fi WebSocket 服务参数；Monitor 默认连接 ws://设备IP:8765/pv1。
WEBSOCKET_PORT = 8765
WEBSOCKET_PATH = "/pv1"
# 连续缺失多少个 Monitor 采集周期后返回系统启动等待页。
MONITOR_TIMEOUT_INTERVALS = 10
# 每接收多少份 Monitor 快照，使用主机时间重新校准一次本地推进基准。
TIME_CALIBRATION_SNAPSHOTS = 20
# 设备推进时间与主机运行时间的允许误差；误差不超过该值时保持原基准。
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
        "WIFI_ENABLED": bool,
        "LCD_STYLE": str,
        "LCD_TRANSFER_BACKEND": str,
        "RENDER_FRAME_POLICY": str,
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

# 空闲刷新允许配置得更快，但为保证秒钟连续显示，最长不得超过一秒。
CLOCK_REFRESH_INTERVAL_MS = min(
    CLOCK_REFRESH_INTERVAL_MS,
    max(1, int(RENDER_INTERVAL_MS)),
)

# ESP32-S3 原生支持无线传输，运行配置仅控制是否启用。
WIFI_ENABLED = bool(WIFI_ENABLED)
