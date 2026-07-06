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

from config import (
    BOARD_MODEL,
    LCD_STYLE,
    MONITOR_TIMEOUT_INTERVALS,
    RENDER_INTERVAL_MS,
)
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
        from board_manager import get_board_profile
        from led import create_led_controller

        self._protocol = protocol
        self._protocol.write(b"BOOT:PROTOCOL_READY\n")
        self._board_profile = get_board_profile(BOARD_MODEL)
        self._led = create_led_controller(self._board_profile)
        self._led.start()
        self._protocol.write(
            "BOOT:BOARD_MODEL:{}\n".format(
                self._board_profile.name
            ).encode()
        )
        self._protocol.write(b"BOOT:LED_READY\n")
        self._lcd = LcdDevice()
        self._lcd.initialize()
        self._protocol.write(
            "BOOT:LCD_COLOR_PROFILE:{}\n".format(
                self._lcd.color_profile_name()
            ).encode()
        )
        self._protocol.write(b"BOOT:LCD_READY\n")
        # 在 Monitor 发送首个快照前保持专用启动样式，该样式独立于数据看板配置。
        self._renderer = DashboardRenderer(self._lcd, style_name="boot")
        self._boot_frame = 0
        self._boot_logs = []
        self._next_boot_animation = time.ticks_ms()
        self._show_boot(72, "BOOT:LCD_READY", "loading...", flush=True)
        self._cache = SnapshotCache()
        self._show_boot(84, "BOOT:CACHE_READY", "loading...", flush=True)
        self._receiver = DataReceiver(self._protocol, self._cache, self._led)
        self._show_boot(94, "BOOT:RECEIVER_READY", "loading...", flush=True)
        self._rendering_version = -1
        self._next_render = time.ticks_add(
            time.ticks_ms(), RENDER_INTERVAL_MS
        )
        self._monitor_interval_ms = 500
        self._monitor_connected = False

    def _show_boot(self, progress, log, status, flush=False):
        """提交启动画面，并可选择立即刷新其全部条带。"""
        if log and (not self._boot_logs or self._boot_logs[-1] != log):
            self._boot_logs.append(log)
            self._boot_logs = self._boot_logs[-4:]
        self._renderer.request_render({
            "boot": {
                "progress": progress,
                "logs": self._boot_logs,
                "status": status,
            }
        }, force=True)
        if flush:
            while self._renderer.is_rendering():
                self._renderer.update_pending(max_regions=1)

    def _monitor_timed_out(self, now):
        """判断 Monitor 是否已连续超过配置周期没有发送有效消息。"""
        if not self._monitor_connected:
            return False
        last_message_ms = self._protocol.last_message_ms()
        if last_message_ms is None:
            return False
        return (
            time.ticks_diff(now, last_message_ms)
            >= self._monitor_interval_ms * MONITOR_TIMEOUT_INTERVALS
        )

    def _return_to_waiting_page(self):
        """切换到系统启动等待页，并保留现有 USB CDC 等待主机重连。"""
        self._monitor_connected = False
        self._cache.clear()
        self._renderer.set_style("boot")
        self._rendering_version = -1
        self._boot_frame = 0
        self._boot_logs = ["MONITOR:TIMEOUT", "USB:CDC:WAITING"]
        self._show_boot(
            100,
            "SYSTEM_BOOT:WAITING_MONITOR",
            "waiting connecting ....",
            flush=True,
        )
        # Monitor 进程退出只会关闭主机侧串口，不会销毁 Pico 已注册的 CDC。
        # 运行中再次调用 usb.device.init() 可能等待未完成的 USB 传输，导致
        # 主循环永久停顿；继续轮询原协议即可在 Monitor 重启后自动恢复。
        self._next_boot_animation = time.ticks_ms()

    def run(self):
        """持续推进各组件，每轮均在有限时间内返回。"""
        memory_used, memory_total = memory_usage()
        self._protocol.write(
            "BOOT:MEMORY:USED={}:TOTAL={}\n".format(
                memory_used, memory_total
            ).encode()
        )
        self._show_boot(
            97,
            "BOOT:MEMORY:USED={}:TOTAL={}".format(memory_used, memory_total),
            "loading...",
            flush=True,
        )
        self._protocol.write(b"BOOT:PICO_LCD_READY\n")
        self._show_boot(
            100,
            "BOOT:PICO_LCD_READY",
            "waiting connecting ....",
            flush=True,
        )
        while True:
            self._receiver.update()
            self._led.update()
            now = time.ticks_ms()
            # Monitor 被强制结束后，USB CDC 可能持续报告端点可读或遗留半包，
            # 此时接收器会一直处于忙状态。超时判断必须先于忙状态短路，
            # 否则主循环永远无法切换回 SYSTEM BOOT 等待页。
            if self._monitor_timed_out(now):
                self._return_to_waiting_page()
                continue
            if self._receiver.is_busy():
                time.sleep_ms(0)
                continue
            snapshot, version = self._cache.latest()
            has_new_snapshot = version != self._rendering_version
            idle_refresh_due = time.ticks_diff(now, self._next_render) >= 0
            if (
                snapshot is None
                and not self._renderer.is_rendering()
                and time.ticks_diff(now, self._next_boot_animation) >= 0
            ):
                dots = "." * (self._boot_frame % 4 + 1)
                self._show_boot(
                    100,
                    "BOOT:PICO_LCD_READY",
                    "waiting connecting " + dots,
                )
                self._boot_frame += 1
                self._next_boot_animation = time.ticks_add(now, 250)
            if (
                snapshot is not None
                and not self._renderer.is_rendering()
                and (has_new_snapshot or idle_refresh_due)
            ):
                display = snapshot.get("display", {}) if snapshot else {}
                requested_interval_ms = display.get(
                    "collection_interval_ms", self._monitor_interval_ms
                )
                try:
                    requested_interval_ms = int(requested_interval_ms)
                except (TypeError, ValueError):
                    requested_interval_ms = self._monitor_interval_ms
                self._monitor_interval_ms = max(1, requested_interval_ms)
                self._monitor_connected = True
                requested_rotation = display.get("rotation", 0)
                try:
                    requested_rotation = int(requested_rotation)
                except (TypeError, ValueError):
                    requested_rotation = 0
                requested_style = display.get("style", LCD_STYLE)
                requested_brightness = display.get("brightness", 100)
                try:
                    requested_brightness = int(requested_brightness)
                except (TypeError, ValueError):
                    requested_brightness = 100
                if self._lcd.set_backlight_brightness(requested_brightness):
                    self._protocol.write(
                        "CONFIG:LCD_BRIGHTNESS:{}\n".format(
                            self._lcd.backlight_brightness()
                        ).encode()
                    )
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
            # 每绘制一个区域就返回主循环轮询 USB，避免连续绘制多个区域期间
            # 主机串口写入因 Pico 不消费数据而阻塞数百毫秒。
            render_completed = self._renderer.update_pending(max_regions=1)
            # system_boot 等待页使用尚未打开的应用 CDC；此时若发送帧完成
            # ACK，CDC 写缓冲会持续返回零并阻塞主循环。仅在 Monitor 已
            # 恢复连接后发送渲染性能信息，等待动画本身仍可正常推进。
            if render_completed and self._monitor_connected:
                canvas_us, lcd_us, region_count = self._renderer.last_profile()
                profile = self._renderer.last_detailed_profile()
                memory_used, memory_total = memory_usage()
                response = (
                    "ACK:LCD_FRAME:{}:TOTAL={}MS:CANVAS={}US:LCD={}US:"
                    "VIEW={}US:BUFFER={}US:GC={}US:SCHEDULE={}US:"
                    "SLOWEST_REGION={}US:"
                    "REGIONS={}:MEMORY_USED={}:MEMORY_TOTAL={}:"
                    "CANVAS_BACKEND={}:PROTOCOL_BACKEND={}\n"
                ).format(
                    self._rendering_version,
                    self._renderer.last_render_ms(),
                    canvas_us,
                    lcd_us,
                    profile["view_us"],
                    profile["buffer_us"],
                    profile["gc_us"],
                    profile["schedule_us"],
                    profile["slowest_region_us"],
                    region_count,
                    memory_used,
                    memory_total,
                    self._renderer.canvas_backend().upper(),
                    self._protocol.protocol_backend(),
                )
                self._protocol.write(response.encode())
            time.sleep_ms(1)


def main():
    """优先建立诊断通道，再启动硬件应用。"""
    protocol = None
    try:
        from upgrade_manager import UpgradeManager

        from usb_transport import create_data_cdc

        protocol = JsonProtocol(stream=create_data_cdc())
        protocol._upgrade_manager = UpgradeManager(protocol.write_upgrade_response)
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
        if isinstance(error, MemoryError):
            # MemoryError 后堆往往已高度碎片化，继续运行无法恢复。
            # 先给独立 CDC 留出发送 FATAL 的时间，再硬复位重建堆。
            time.sleep_ms(300)
            import machine

            machine.reset()
        while True:
            time.sleep_ms(1000)
            if protocol is not None:
                protocol.write(message.encode("utf-8"))


if __name__ == "__main__":
    main()
