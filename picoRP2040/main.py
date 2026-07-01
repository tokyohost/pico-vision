"""启动 RP2040 状态灯、JSON 接收和 LCD 异步刷新服务。"""

import sys
import time

from config import RENDER_INTERVAL_MS
from protocol import JsonProtocol


class Application:
    """以单核协作式循环编排 LED、USB JSON 与 LCD 刷新。"""

    def __init__(self, protocol):
        """按通信、LED、LCD 的顺序初始化各组件。"""
        from dashboard import DashboardRenderer
        from data_receiver import DataReceiver, SnapshotCache
        from lcd import LcdDevice
        from ledController import LedController

        self._protocol = protocol
        self._protocol.write(b"BOOT:PROTOCOL_READY\n")
        self._led = LedController()
        self._led.start()
        self._protocol.write(b"BOOT:LED_READY\n")
        self._lcd = LcdDevice()
        self._lcd.initialize()
        self._protocol.write(b"BOOT:LCD_READY\n")
        self._renderer = DashboardRenderer(self._lcd)
        self._cache = SnapshotCache()
        self._receiver = DataReceiver(self._protocol, self._cache, self._led)
        self._rendering_version = -1
        self._next_render = time.ticks_add(time.ticks_ms(), RENDER_INTERVAL_MS)

    def run(self):
        """持续推进各组件，每轮均在有限时间内返回。"""
        self._protocol.write(b"BOOT:PICO_LCD_READY\n")
        self._renderer.request_render(None)
        while True:
            self._receiver.update()
            self._led.update()
            if self._receiver.is_busy():
                time.sleep_ms(0)
                continue
            now = time.ticks_ms()
            snapshot, version = self._cache.latest()
            if (
                time.ticks_diff(now, self._next_render) >= 0
                and not self._renderer.is_rendering()
            ):
                self._renderer.request_render(snapshot)
                self._rendering_version = version
                self._next_render = time.ticks_add(
                    self._next_render, RENDER_INTERVAL_MS
                )
                if time.ticks_diff(now, self._next_render) >= 0:
                    self._next_render = time.ticks_add(now, RENDER_INTERVAL_MS)
            if self._renderer.update():
                canvas_us, lcd_us, region_count = self._renderer.last_profile()
                response = (
                    "ACK:LCD_FRAME:{}:TOTAL={}MS:CANVAS={}US:LCD={}US:REGIONS={}\n"
                ).format(
                    self._rendering_version,
                    self._renderer.last_render_ms(),
                    canvas_us,
                    lcd_us,
                    region_count,
                )
                self._protocol.write(response.encode())
            time.sleep_ms(1)


def main():
    """优先建立诊断通道，再启动硬件应用。"""
    protocol = None
    try:
        protocol = JsonProtocol()
        Application(protocol).run()
    except Exception as error:
        message = "FATAL:{}:{}\n".format(type(error).__name__, error)
        if protocol is not None:
            protocol.write(message.encode("utf-8"))
        else:
            print(message)
        try:
            sys.print_exception(error)
        except AttributeError:
            pass
        while True:
            time.sleep_ms(1000)
            if protocol is not None:
                protocol.write(message.encode("utf-8"))


if __name__ == "__main__":
    main()
