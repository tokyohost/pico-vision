import serial
import time

PORT = "COM9"   # 改成你的 Pico 串口
BAUD = 115200   # USB CDC 实际不太依赖这个值

WIDTH = 240
HEIGHT = 320
MAGIC = b'PV-V1'


def rgb565(r, g, b):
    value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    return value.to_bytes(2, "big")


def make_test_frame():
    buf = bytearray()

    for y in range(HEIGHT):
        for x in range(WIDTH):
            r = int(x * 255 / (WIDTH - 1))
            g = int(y * 255 / (HEIGHT - 1))
            b = 80
            buf += rgb565(r, g, b)

    return buf


ser = serial.Serial(PORT, BAUD, timeout=3)
time.sleep(2)

frame = make_test_frame()

while True:
    ser.write(MAGIC)
    ser.write(frame)
    ser.flush()
    print("sent one frame")
    time.sleep(1)