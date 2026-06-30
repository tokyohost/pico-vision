"""在 Raspberry Pi Pico 上接收系统 JSON 并渲染 ST7789 仪表盘。"""

from machine import Pin, SPI
import struct
import sys
import time

try:
    import ujson as json
except ImportError:
    import json

try:
    import uselect as select
except ImportError:
    try:
        import select
    except ImportError:
        select = None


WIDTH = 240
HEIGHT = 320
FRAME_SIZE = WIDTH * HEIGHT * 2
RENDER_INTERVAL_MS = 500
MAX_JSON_SIZE = 16 * 1024

PIN_SCK = 18
PIN_MOSI = 19
PIN_CS = 17
PIN_DC = 16
PIN_RST = 20
PIN_BL = 21
X_OFFSET = 0
Y_OFFSET = 0

DEVICE_NAME = "PICO_LCD"
LCD_DRIVER = "ST7789"
PIXEL_FORMAT = "RGB565"
PING_TEXT = b"PING:PICO_LCD?"
JSON_MAGIC = b"JSN0"

BLACK = 0x0000
WHITE = 0xE71C
GRAY = 0x5ACB
DARK = 0x18E3
BLUE = 0x1CBF
GREEN = 0x46E9
YELLOW = 0xFE00
PURPLE = 0x9ADF
RED = 0xF9C7

# 5×7 ASCII 点阵，按列从低位到高位保存像素。
FONT_5X7 = {
    " ": (0, 0, 0, 0, 0), "!": (0, 0, 95, 0, 0), "%": (99, 19, 8, 100, 99),
    "+": (8, 8, 62, 8, 8), "-": (8, 8, 8, 8, 8), ".": (0, 96, 96, 0, 0),
    "/": (32, 16, 8, 4, 2), ":": (0, 54, 54, 0, 0), "?": (2, 1, 81, 9, 6),
    "_": (64, 64, 64, 64, 64),
    "0": (62, 81, 73, 69, 62), "1": (0, 66, 127, 64, 0),
    "2": (66, 97, 81, 73, 70), "3": (33, 65, 69, 75, 49),
    "4": (24, 20, 18, 127, 16), "5": (39, 69, 69, 69, 57),
    "6": (60, 74, 73, 73, 48), "7": (1, 113, 9, 5, 3),
    "8": (54, 73, 73, 73, 54), "9": (6, 73, 73, 41, 30),
    "A": (126, 17, 17, 17, 126), "B": (127, 73, 73, 73, 54),
    "C": (62, 65, 65, 65, 34), "D": (127, 65, 65, 34, 28),
    "E": (127, 73, 73, 73, 65), "F": (127, 9, 9, 9, 1),
    "G": (62, 65, 73, 73, 122), "H": (127, 8, 8, 8, 127),
    "I": (0, 65, 127, 65, 0), "J": (32, 64, 65, 63, 1),
    "K": (127, 8, 20, 34, 65), "L": (127, 64, 64, 64, 64),
    "M": (127, 2, 12, 2, 127), "N": (127, 4, 8, 16, 127),
    "O": (62, 65, 65, 65, 62), "P": (127, 9, 9, 9, 6),
    "Q": (62, 65, 81, 33, 94), "R": (127, 9, 25, 41, 70),
    "S": (70, 73, 73, 73, 49), "T": (1, 1, 127, 1, 1),
    "U": (63, 64, 64, 64, 63), "V": (31, 32, 64, 32, 31),
    "W": (63, 64, 56, 64, 63), "X": (99, 20, 8, 20, 99),
    "Y": (7, 8, 112, 8, 7), "Z": (97, 81, 73, 69, 67),
}


class LcdDevice:
    """封装 ST7789 的初始化、窗口设置和整帧传输。"""

    def __init__(self):
        """初始化 LCD 所需的 GPIO 与 SPI 外设。"""
        self.cs = Pin(PIN_CS, Pin.OUT, value=1)
        self.dc = Pin(PIN_DC, Pin.OUT, value=1)
        self.rst = Pin(PIN_RST, Pin.OUT, value=1)
        self.bl = Pin(PIN_BL, Pin.OUT, value=1)
        self.spi = SPI(0, baudrate=40_000_000, polarity=0, phase=0,
                       sck=Pin(PIN_SCK), mosi=Pin(PIN_MOSI))

    def write_command(self, command):
        """向 LCD 写入一个控制命令。"""
        self.dc.value(0)
        self.cs.value(0)
        self.spi.write(bytes((command,)))
        self.cs.value(1)

    def write_data(self, data):
        """向 LCD 写入命令对应的数据。"""
        self.dc.value(1)
        self.cs.value(0)
        self.spi.write(data)
        self.cs.value(1)

    def command(self, command, data=None):
        """连续写入命令及其可选数据。"""
        self.write_command(command)
        if data is not None:
            self.write_data(data)

    def reset(self):
        """执行 LCD 硬件复位时序。"""
        self.rst.value(1)
        time.sleep_ms(50)
        self.rst.value(0)
        time.sleep_ms(50)
        self.rst.value(1)
        time.sleep_ms(150)

    def set_window(self, x0, y0, x1, y1):
        """设置下一次显存写入覆盖的矩形区域。"""
        self.command(0x2A, struct.pack(">HH", x0 + X_OFFSET, x1 + X_OFFSET))
        self.command(0x2B, struct.pack(">HH", y0 + Y_OFFSET, y1 + Y_OFFSET))
        self.write_command(0x2C)

    def initialize(self):
        """按照 ST7789 时序初始化竖屏显示模式。"""
        self.reset()
        self.command(0x01)
        time.sleep_ms(150)
        self.command(0x11)
        time.sleep_ms(120)
        self.command(0x3A, b"\x55")
        self.command(0x36, b"\x00")
        self.command(0x21)
        self.command(0x13)
        time.sleep_ms(10)
        self.command(0x29)
        time.sleep_ms(100)
        self.bl.value(1)

    def show(self, frame):
        """将一帧大端 RGB565 数据完整写入 LCD。"""
        self.set_window(0, 0, WIDTH - 1, HEIGHT - 1)
        self.dc.value(1)
        self.cs.value(0)
        self.spi.write(frame)
        self.cs.value(1)


class Canvas:
    """在大端 RGB565 字节缓冲区上提供轻量绘图能力。"""

    def __init__(self, width, height):
        """创建指定尺寸的 RGB565 帧缓冲区。"""
        self.width = width
        self.height = height
        self.buffer = bytearray(width * height * 2)

    @staticmethod
    def _pixel_bytes(color):
        """将 RGB565 整数转换为大端双字节像素。"""
        return bytes(((color >> 8) & 0xFF, color & 0xFF))

    def clear(self, color=BLACK):
        """使用指定颜色清空整个画布。"""
        self.buffer[:] = self._pixel_bytes(color) * (self.width * self.height)

    def pixel(self, x, y, color):
        """在画布范围内绘制一个像素。"""
        if 0 <= x < self.width and 0 <= y < self.height:
            offset = (y * self.width + x) * 2
            self.buffer[offset] = (color >> 8) & 0xFF
            self.buffer[offset + 1] = color & 0xFF

    def fill_rect(self, x, y, width, height, color):
        """绘制经过边界裁剪的实心矩形。"""
        left = max(0, x)
        top = max(0, y)
        right = min(self.width, x + width)
        bottom = min(self.height, y + height)
        if left >= right or top >= bottom:
            return
        row = self._pixel_bytes(color) * (right - left)
        for line_y in range(top, bottom):
            start = (line_y * self.width + left) * 2
            self.buffer[start:start + len(row)] = row

    def line(self, x0, y0, x1, y1, color):
        """使用整数 Bresenham 算法绘制线段。"""
        dx = abs(x1 - x0)
        sx = 1 if x0 < x1 else -1
        dy = -abs(y1 - y0)
        sy = 1 if y0 < y1 else -1
        error = dx + dy
        while True:
            self.pixel(x0, y0, color)
            if x0 == x1 and y0 == y1:
                break
            doubled = error * 2
            if doubled >= dy:
                error += dy
                x0 += sx
            if doubled <= dx:
                error += dx
                y0 += sy

    def text(self, x, y, value, color=WHITE, scale=1):
        """使用内置 5×7 点阵字体绘制 ASCII 文本。"""
        cursor_x = x
        for character in str(value).upper():
            columns = FONT_5X7.get(character, FONT_5X7["?"])
            for column_index, bits in enumerate(columns):
                for row_index in range(7):
                    if bits & (1 << row_index):
                        self.fill_rect(cursor_x + column_index * scale,
                                       y + row_index * scale, scale, scale, color)
            cursor_x += 6 * scale


class DashboardRenderer:
    """将系统状态快照绘制为适合 240×320 屏幕的仪表盘。"""

    def __init__(self, lcd):
        """创建渲染画布并保存 LCD 输出设备。"""
        self.lcd = lcd
        self.canvas = Canvas(WIDTH, HEIGHT)

    @staticmethod
    def _number(value, default=0):
        """安全地将 JSON 数值转换为浮点数。"""
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _format_bytes(value):
        """将字节数格式化为适合屏幕显示的短文本。"""
        amount = DashboardRenderer._number(value)
        for unit in ("B", "K", "M", "G", "T"):
            if amount < 1024 or unit == "T":
                if unit in ("G", "T"):
                    return "{:.1f}{}".format(amount, unit)
                return "{:.0f}{}".format(amount, unit)
            amount /= 1024
        return "0B"

    @staticmethod
    def _format_uptime(seconds):
        """将运行秒数格式化为天、小时和分钟。"""
        total_minutes = int(DashboardRenderer._number(seconds)) // 60
        days, remainder = divmod(total_minutes, 1440)
        hours, minutes = divmod(remainder, 60)
        return "{}D {:02d}:{:02d}".format(days, hours, minutes)

    def _draw_bar(self, x, y, width, height, percent, color):
        """绘制百分比进度条。"""
        value = max(0, min(100, self._number(percent)))
        self.canvas.fill_rect(x, y, width, height, DARK)
        self.canvas.fill_rect(x + 1, y + 1, int((width - 2) * value / 100), height - 2, color)

    def _draw_history(self, x, y, width, height, values, color, maximum=100):
        """将一组历史数值绘制为折线趋势图。"""
        if not values or len(values) < 2:
            return
        points = []
        count = len(values)
        for index, value in enumerate(values):
            point_x = x + int(index * (width - 1) / (count - 1))
            ratio = max(0, min(1, self._number(value) / max(1, maximum)))
            points.append((point_x, y + height - 1 - int(ratio * (height - 1))))
        for index in range(1, len(points)):
            self.canvas.line(points[index - 1][0], points[index - 1][1],
                             points[index][0], points[index][1], color)

    def _draw_metric_card(self, y, title, percent, detail, history, color):
        """绘制 CPU、内存或磁盘的通用指标卡片。"""
        self.canvas.text(8, y, title, color, 2)
        self.canvas.text(94, y, "{}%".format(int(self._number(percent))), WHITE, 2)
        self.canvas.text(8, y + 22, detail, GRAY, 1)
        self._draw_bar(8, y + 34, 105, 10, percent, color)
        self._draw_history(126, y + 18, 105, 27, history, color)

    def render(self, snapshot):
        """绘制最新系统快照并将完整帧提交到 LCD。"""
        snapshot = snapshot or {}
        cpu = snapshot.get("cpu", {})
        memory = snapshot.get("memory", {})
        disk = snapshot.get("disk", {})
        network = snapshot.get("network", {})
        self.canvas.clear(BLACK)

        host = str(snapshot.get("host", "WAITING"))[:18]
        self.canvas.text(8, 8, host, WHITE, 2)
        status_color = GREEN if network.get("online") else RED
        self.canvas.fill_rect(219, 10, 12, 12, status_color)
        self.canvas.line(0, 34, WIDTH - 1, 34, GRAY)

        temperature = cpu.get("temperature_c")
        temperature_text = "--C" if temperature is None else "{}C".format(int(self._number(temperature)))
        self._draw_metric_card(43, "CPU", cpu.get("percent"), "TEMP " + temperature_text,
                               cpu.get("history", ()), BLUE)
        self._draw_metric_card(
            100, "RAM", memory.get("percent"),
            self._format_bytes(memory.get("used_bytes")) + "/" + self._format_bytes(memory.get("total_bytes")),
            memory.get("history", ()), GREEN)
        self._draw_metric_card(
            157, "DISK", disk.get("percent"),
            self._format_bytes(disk.get("used_bytes")) + "/" + self._format_bytes(disk.get("total_bytes")),
            disk.get("history", ()), YELLOW)

        self.canvas.line(0, 213, WIDTH - 1, 213, GRAY)
        self.canvas.text(8, 222, "NET", PURPLE, 2)
        self.canvas.text(8, 245, "UP " + self._format_bytes(network.get("upload_bps")) + "/S", BLUE, 1)
        self.canvas.text(122, 245, "DN " + self._format_bytes(network.get("download_bps")) + "/S", GREEN, 1)
        ping = network.get("ping_ms")
        ping_text = "ERR" if ping is None else "{}MS".format(int(self._number(ping)))
        self.canvas.text(8, 261, "PING " + ping_text, PURPLE, 1)
        self.canvas.text(122, 261, str(network.get("ip", "0.0.0.0"))[:16], WHITE, 1)

        self.canvas.line(0, 280, WIDTH - 1, 280, GRAY)
        timestamp = str(snapshot.get("timestamp", ""))
        clock = timestamp[11:19] if len(timestamp) >= 19 else "--:--:--"
        self.canvas.text(8, 292, clock, WHITE, 2)
        self.canvas.text(116, 294, self._format_uptime(snapshot.get("uptime_seconds")), GRAY, 1)
        self.lcd.show(self.canvas.buffer)


class JsonProtocol:
    """处理 USB 串口握手和带长度前缀的 JSON 数据包。"""

    def __init__(self):
        """获取标准输入输出的二进制串口流。"""
        self.input = getattr(sys.stdin, "buffer", sys.stdin)
        self.output = getattr(sys.stdout, "buffer", sys.stdout)

    def write(self, data):
        """通过 USB 串口向系统端发送二进制响应。"""
        self.output.write(data)
        try:
            self.output.flush()
        except Exception:
            pass

    def read_exact(self, length):
        """从 USB 串口阻塞读取指定数量的字节。"""
        result = bytearray(length)
        view = memoryview(result)
        position = 0
        while position < length:
            chunk = self.input.read(length - position)
            if chunk:
                size = len(chunk)
                view[position:position + size] = chunk
                position += size
            else:
                time.sleep_ms(1)
        return result

    def read_line(self, first_byte, maximum=128):
        """从首字节开始读取一个长度受限的文本命令。"""
        result = bytearray(first_byte)
        while len(result) < maximum:
            byte = self.input.read(1)
            if byte:
                result.extend(byte)
                if byte == b"\n":
                    break
            else:
                time.sleep_ms(1)
        return bytes(result)

    def discard(self, length):
        """丢弃异常数据包的剩余字节，以恢复下一包协议同步。"""
        remaining = length
        while remaining > 0:
            size = min(remaining, 512)
            self.read_exact(size)
            remaining -= size

    def receive(self):
        """读取一个命令，返回新系统快照或空值。"""
        first = self.input.read(1)
        if not first:
            return None
        if first == b"P":
            line = self.read_line(first).strip()
            if line == PING_TEXT:
                response = "PONG:{}:{}:{}x{}:{}:JSON\n".format(
                    DEVICE_NAME, LCD_DRIVER, WIDTH, HEIGHT, PIXEL_FORMAT)
                self.write(response.encode())
            return None
        if first != b"J":
            return None
        magic = first + self.read_exact(3)
        if magic != JSON_MAGIC:
            return None
        payload_size = struct.unpack(">I", self.read_exact(4))[0]
        if payload_size <= 0 or payload_size > MAX_JSON_SIZE:
            self.write(b"ERR:BAD_JSON_SIZE\n")
            if 0 < payload_size < 1024 * 1024:
                self.discard(payload_size)
            return None
        payload = self.read_exact(payload_size)
        try:
            return json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeError):
            self.write(b"ERR:BAD_JSON\n")
            return None


def create_poller(stream):
    """创建 USB 输入轮询器；不支持轮询时返回空值。"""
    if select is None or not hasattr(select, "poll"):
        return None
    poller = select.poll()
    poller.register(stream, select.POLLIN)
    return poller


def main():
    """初始化屏幕并按固定 0.5 秒周期渲染最新 JSON 快照。"""
    lcd = LcdDevice()
    lcd.initialize()
    renderer = DashboardRenderer(lcd)
    protocol = JsonProtocol()
    poller = create_poller(sys.stdin)
    latest_snapshot = None
    next_render = time.ticks_ms()
    protocol.write(b"BOOT:PICO_LCD_READY\n")

    while True:
        now = time.ticks_ms()
        remaining = max(0, time.ticks_diff(next_render, now))
        if poller is None:
            snapshot = protocol.receive()
        elif poller.poll(min(remaining, 50)):
            snapshot = protocol.receive()
        else:
            snapshot = None
        if snapshot is not None:
            latest_snapshot = snapshot

        now = time.ticks_ms()
        if time.ticks_diff(now, next_render) >= 0:
            renderer.render(latest_snapshot)
            next_render = time.ticks_add(next_render, RENDER_INTERVAL_MS)
            if time.ticks_diff(now, next_render) >= 0:
                next_render = time.ticks_add(now, RENDER_INTERVAL_MS)


if __name__ == "__main__":
    main()
