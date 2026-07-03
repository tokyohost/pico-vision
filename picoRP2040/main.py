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



"""启动 RP2040 状态灯、JSON 接收和 LCD 异步刷新服务。"""


import gc
import sys
import time

from config import LCD_STYLE, RENDER_INTERVAL_MS
from protocol import JsonProtocol


def memory_usage():
    """返回 MicroPython 堆内存的已占用字节数和总字节数。"""
    allocated = gc.mem_alloc()
    free = gc.mem_free()
    return allocated, allocated + free


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
        self._next_render = time.ticks_add(
            time.ticks_ms(), RENDER_INTERVAL_MS
        )

    def run(self):
        """持续推进各组件，每轮均在有限时间内返回。"""
        memory_used, memory_total = memory_usage()
        self._protocol.write(
            "BOOT:MEMORY:USED={}:TOTAL={}\n".format(
                memory_used, memory_total
            ).encode()
        )
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
            has_new_snapshot = version != self._rendering_version
            idle_refresh_due = time.ticks_diff(now, self._next_render) >= 0
            if (
                snapshot is not None
                and not self._renderer.is_rendering()
                and (has_new_snapshot or idle_refresh_due)
            ):
                display = snapshot.get("display", {}) if snapshot else {}
                requested_rotation = display.get("rotation", 0)
                try:
                    requested_rotation = int(requested_rotation)
                except (TypeError, ValueError):
                    requested_rotation = 0
                requested_style = display.get("style", LCD_STYLE)
                try:
                    if self._renderer.set_style(requested_style):
                        self._protocol.write(
                            "CONFIG:LCD_STYLE:{}\n".format(
                                self._renderer.style_name()
                            ).encode()
                        )
                except (ImportError, TypeError, ValueError) as error:
                    self._protocol.write(
                        "CONFIG:LCD_STYLE_ERROR:{}:{}\n".format(
                            requested_style, error
                        ).encode("utf-8")
                    )
                if self._renderer.set_rotation(requested_rotation):
                    self._protocol.write(
                        "CONFIG:SCREEN_ROTATION:{}\n".format(
                            self._lcd.rotation()
                        ).encode()
                    )
                self._renderer.request_render(
                    snapshot, force=not has_new_snapshot
                )
                self._rendering_version = version
                self._next_render = time.ticks_add(
                    now, RENDER_INTERVAL_MS
                )
            if self._renderer.update_pending():
                canvas_us, lcd_us, region_count = self._renderer.last_profile()
                memory_used, memory_total = memory_usage()
                response = (
                    "ACK:LCD_FRAME:{}:TOTAL={}MS:CANVAS={}US:LCD={}US:"
                    "REGIONS={}:MEMORY_USED={}:MEMORY_TOTAL={}\n"
                ).format(
                    self._rendering_version,
                    self._renderer.last_render_ms(),
                    canvas_us,
                    lcd_us,
                    region_count,
                    memory_used,
                    memory_total,
                )
                self._protocol.write(response.encode())
            time.sleep_ms(1)


def main():
    """优先建立诊断通道，再启动硬件应用。"""
    protocol = None
    try:
        from upgrade_manager import UpgradeManager

        protocol = JsonProtocol()
        protocol._upgrade_manager = UpgradeManager(protocol.write)
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
