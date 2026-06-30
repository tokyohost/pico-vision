from machine import Pin, SPI
import time
import sys
import struct

# =========================
# LCD 参数
# =========================
WIDTH = 240
HEIGHT = 320
FRAME_SIZE = WIDTH * HEIGHT * 2   # RGB565，每像素2字节

# =========================
# Pico 接线配置
# =========================
PIN_SCK = 18
PIN_MOSI = 19
PIN_CS = 17
PIN_DC = 16
PIN_RST = 20
PIN_BL = 21

# 有些 ST7789 屏幕需要偏移
# 240x320 通常是 0,0
X_OFFSET = 0
Y_OFFSET = 0

# USB 串口帧头
# PC 每发一帧前，先发 b'PICO'
MAGIC = b'PV-V1'

# =========================
# SPI / GPIO 初始化
# =========================
cs = Pin(PIN_CS, Pin.OUT, value=1)
dc = Pin(PIN_DC, Pin.OUT, value=1)
rst = Pin(PIN_RST, Pin.OUT, value=1)
bl = Pin(PIN_BL, Pin.OUT, value=1)

spi = SPI(
    0,
    baudrate=62_500_000,
    polarity=1,
    phase=1,
    sck=Pin(PIN_SCK),
    mosi=Pin(PIN_MOSI)
)


# =========================
# 基础 LCD 函数
# =========================
def lcd_write_cmd(cmd):
    dc.value(0)
    cs.value(0)
    spi.write(bytearray([cmd]))
    cs.value(1)


def lcd_write_data(data):
    dc.value(1)
    cs.value(0)
    spi.write(data)
    cs.value(1)


def lcd_cmd(cmd, data=None):
    lcd_write_cmd(cmd)
    if data is not None:
        lcd_write_data(data)


def lcd_reset():
    rst.value(1)
    time.sleep_ms(50)
    rst.value(0)
    time.sleep_ms(50)
    rst.value(1)
    time.sleep_ms(120)


def lcd_set_window(x0, y0, x1, y1):
    x0 += X_OFFSET
    x1 += X_OFFSET
    y0 += Y_OFFSET
    y1 += Y_OFFSET

    lcd_cmd(0x2A, struct.pack(">HH", x0, x1))  # CASET
    lcd_cmd(0x2B, struct.pack(">HH", y0, y1))  # RASET
    lcd_write_cmd(0x2C)                        # RAMWR


def lcd_init():
    lcd_reset()

    lcd_cmd(0x01)  # Software reset
    time.sleep_ms(150)

    lcd_cmd(0x11)  # Sleep out
    time.sleep_ms(120)

    # RGB565
    lcd_cmd(0x3A, b'\x55')

    # 屏幕方向
    # 0x00: 竖屏 240x320
    # 如果显示方向不对，可以试 0x60 / 0xC0 / 0xA0
    lcd_cmd(0x36, b'\x00')

    # 有些 ST7789 需要开启反色，否则颜色不正常
    lcd_cmd(0x21)  # Display inversion ON
    # 如果颜色怪异，可以改成：
    # lcd_cmd(0x20)  # Display inversion OFF

    lcd_cmd(0x13)  # Normal display mode
    time.sleep_ms(10)

    lcd_cmd(0x29)  # Display ON
    time.sleep_ms(100)

    bl.value(1)


def lcd_fill_black():
    lcd_set_window(0, 0, WIDTH - 1, HEIGHT - 1)

    dc.value(1)
    cs.value(0)

    block = b'\x00\x00' * 1024
    total = FRAME_SIZE

    while total > 0:
        n = min(total, len(block))
        spi.write(block[:n])
        total -= n

    cs.value(1)


# =========================
# USB 串口读取
# =========================
def get_usb_stream():
    # 大多数 Pico MicroPython 可以用 sys.stdin.buffer
    # 少数版本如果没有 buffer，就直接用 sys.stdin
    try:
        return sys.stdin.buffer
    except AttributeError:
        return sys.stdin


usb = get_usb_stream()


def read_exact(n):
    buf = bytearray(n)
    view = memoryview(buf)
    pos = 0

    while pos < n:
        chunk = usb.read(n - pos)
        if chunk:
            ln = len(chunk)
            view[pos:pos + ln] = chunk
            pos += ln
        else:
            time.sleep_ms(1)

    return buf


def wait_magic():
    """
    等待 PC 发送 b'PICO' 帧头。
    这样即使串口数据错位，也可以重新同步。
    """
    index = 0

    while True:
        b = usb.read(1)
        if not b:
            time.sleep_ms(1)
            continue

        if b[0] == MAGIC[index]:
            index += 1
            if index == len(MAGIC):
                return
        else:
            index = 0


def receive_frame_to_lcd():
    """
    接收一整帧 RGB565 数据并直接写入 LCD。
    不把完整 153600 字节图片放进内存，边收边刷屏。
    """
    lcd_set_window(0, 0, WIDTH - 1, HEIGHT - 1)

    dc.value(1)
    cs.value(0)

    left = FRAME_SIZE
    chunk_size = 4096

    while left > 0:
        n = min(chunk_size, left)
        data = read_exact(n)
        spi.write(data)
        left -= n

    cs.value(1)


# =========================
# 主程序
# =========================
print("Pico LCD USB Frame Receiver")
print("LCD: 240x320 ST7789 RGB565")
print("Waiting for frames...")

lcd_init()
lcd_fill_black()

frame_count = 0

while True:
    wait_magic()
    receive_frame_to_lcd()

    frame_count += 1
    print("Frame received:", frame_count)