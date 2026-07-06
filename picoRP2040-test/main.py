from machine import Pin, PWM
import time

bl = PWM(Pin(26))  # 改成你实际接 BL 的 GPIO
bl.freq(1000)

while True:
    bl.duty_u16(0)
    print("0%")
    time.sleep(2)

    bl.duty_u16(10000)
    print("15%")
    time.sleep(2)

    bl.duty_u16(32768)
    print("50%")
    time.sleep(2)

    bl.duty_u16(65535)
    print("100%")
    time.sleep(2)