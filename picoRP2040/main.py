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



"""启动状态灯、多传输 JSON 接收和 LCD 异步刷新服务。"""


import gc
import sys
import time

from config import (
    BOARD_MODEL,
    GC_ALLOCATION_THRESHOLD,
    LCD_BOOT_PRELOAD_STYLES,
    LCD_STYLE,
    MONITOR_TIMEOUT_INTERVALS,
    RENDER_INTERVAL_MS,
)
from protocol import JsonProtocol
from fatal_policy import CANVAS_CAPACITY_ERROR, should_restart_after_fatal


def memory_usage():
    """返回 MicroPython 堆内存的已占用字节数和总字节数。"""
    allocated = gc.mem_alloc()
    free = gc.mem_free()
    return allocated, allocated + free


def collect_memory_error_ram_status():
    """记录内存异常现场，并返回垃圾回收前后的 RAM 使用情况。"""
    allocated_before_gc = gc.mem_alloc()
    free_before_gc = gc.mem_free()
    total = allocated_before_gc + free_before_gc
    gc.collect()
    return (
        allocated_before_gc,
        free_before_gc,
        gc.mem_free(),
        total,
    )


def configure_garbage_collection():
    """启用按累计分配量触发的主动垃圾回收，减缓堆碎片形成。"""
    gc.collect()
    threshold = getattr(gc, "threshold", None)
    if callable(threshold):
        threshold(GC_ALLOCATION_THRESHOLD)
        return GC_ALLOCATION_THRESHOLD
    return None


class Application:
    """以单核协作式循环编排 LED、JSON 传输与 LCD 刷新。"""

    def __init__(self, protocol, transport=None):
        """按通信、LED、LCD 的顺序初始化各组件。"""
        gc_threshold = configure_garbage_collection()
        from dashboard import DashboardRenderer
        from data_receiver import DataReceiver, SnapshotCache
        from lcd import create_lcd_device
        from board_manager import get_board_profile
        from button_controller import ButtonController
        from led import create_led_controller

        self._protocol = protocol
        self._transport = transport
        self._protocol.write(b"BOOT:PROTOCOL_READY\n")
        if gc_threshold is not None:
            self._protocol.write(
                "BOOT:GC_THRESHOLD:{}\n".format(gc_threshold).encode()
            )
        self._board_profile = get_board_profile(BOARD_MODEL)
        self._led = create_led_controller(self._board_profile)
        self._led.start()
        self._protocol.write(
            "BOOT:BOARD_MODEL:{}\n".format(
                self._board_profile.name
            ).encode()
        )
        self._protocol.write(b"BOOT:LED_READY\n")
        self._lcd = create_lcd_device()
        self._lcd.initialize()
        self._protocol.write(
            "BOOT:LCD_DEVICE_TYPE:{}\n".format(
                self._lcd.device_type()
            ).encode()
        )
        self._protocol.write(
            "BOOT:LCD_COLOR_PROFILE:{}\n".format(
                self._lcd.color_profile_name()
            ).encode()
        )
        self._protocol.write(b"BOOT:LCD_READY\n")
        self._failed_custom_style = None
        self._renderer = DashboardRenderer(
            self._lcd, style_name="boot"
        )
        self._buttons = ButtonController()
        self._protocol.set_command_services({"renderer": self._renderer})
        self._boot_frame = 0
        self._boot_logs = []
        self._next_boot_animation = time.ticks_ms()
        self._show_boot(72, "BOOT:LCD_READY", "loading...", flush=True)
        self._preload_boot_styles()
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
        self._dev_mode = False
        self._button_style_override = None
        self._last_display_style = LCD_STYLE

    def _preload_boot_styles(self):
        """在启动页阶段预加载大型样式，避免连接后首次编译造成内存峰值。"""
        preload_style = getattr(self._renderer, "preload_style", None)
        if not callable(preload_style):
            return
        style_count = len(LCD_BOOT_PRELOAD_STYLES)
        for style_index, style_name in enumerate(LCD_BOOT_PRELOAD_STYLES, 1):
            loading_log = "STYLE:LOADING:{}/{}:{}".format(
                style_index, style_count, style_name
            )
            try:
                self._protocol.write(
                    "BOOT:{}\n".format(loading_log).encode()
                )
                self._show_boot(
                    76,
                    loading_log,
                    "loading {}/{}...".format(style_index, style_count),
                    flush=True,
                )
                preload_style(style_name)
                self._protocol.write(
                    "BOOT:STYLE_PRELOADED:{}\n".format(style_name).encode()
                )
                self._show_boot(
                    80,
                    "STYLE:LOADED:{}".format(style_name),
                    "style ready {}/{}".format(style_index, style_count),
                    flush=True,
                )
            except (ImportError, MemoryError, TypeError, ValueError) as error:
                gc.collect()
                self._protocol.write(
                    "BOOT:STYLE_PRELOAD_ERROR:{}:{}\n".format(
                        style_name, error
                    ).encode("utf-8")
                )
                self._show_boot(
                    80,
                    "STYLE:FAILED:{}".format(style_name),
                    "style failed {}/{}".format(style_index, style_count),
                    flush=True,
                )

    def _write_custom_style_log(self, message):
        """向 Monitor 输出自定义样式启动加载结果。"""
        self._protocol.write(message.encode("utf-8"))

    def _show_boot(self, progress, log, status, flush=False):
        """提交启动画面，并可选择立即刷新其全部条带。"""
        if log and (not self._boot_logs or self._boot_logs[-1] != log):
            self._boot_logs.append(log)
            self._boot_logs = self._boot_logs[-4:]
        boot_snapshot = {
            "boot": {
                "progress": progress,
                "logs": self._boot_logs,
                "status": status,
                "wifi": self._boot_wifi_status(),
            }
        }
        self._renderer.request_render(boot_snapshot, force=True)
        if flush:
            while self._renderer.is_rendering():
                self._update_renderer_with_fallback(boot_snapshot)

    def _boot_wifi_status(self):
        """返回系统启动页固定展示的 Wi-Fi 状态。"""
        transport = getattr(self, "_transport", None)
        provider = getattr(transport, "wifi_status", None)
        if not callable(provider):
            return {"enabled": False}
        try:
            return provider()
        except (OSError, RuntimeError, ValueError) as error:
            return {
                "enabled": True,
                "available": False,
                "connected": False,
                "error": str(error),
            }

    def _set_style_after_system_boot(self, style_name):
        """先切换到系统启动页整理内存，再尝试加载指定样式。"""
        current_style = self._renderer.style_name()
        if style_name == current_style:
            return False
        if style_name == "boot":
            return self._renderer.set_style(style_name)
        self._renderer.set_style("boot")
        self._protocol.write(
            "CONFIG:LCD_STYLE_PREPARE:{}\n".format(style_name).encode("utf-8")
        )
        self._show_boot(
            100,
            "STYLE:PREPARE:{}".format(style_name),
            "loading style...",
            flush=True,
        )
        # 先释放上一样式和启动页刷新产生的短命对象，再导入可能较大的目标样式。
        gc.collect()
        changed = self._renderer.set_style(style_name)
        gc.collect()
        return changed or current_style != self._renderer.style_name()

    def _style_switch_candidates(self):
        """返回按键可循环切换的样式名称列表。"""
        try:
            from styles.style_plugins import style_catalog

            names = [
                item.get("name")
                for item in style_catalog()
                if isinstance(item, dict) and item.get("name")
            ]
        except Exception:
            names = []
        if LCD_STYLE not in names:
            names.insert(0, LCD_STYLE)
        current_style = self._renderer.style_name()
        if current_style != "boot" and current_style not in names:
            names.insert(0, current_style)
        return tuple(name for name in names if name != "boot")

    def _neighbor_style_name(self, direction):
        """按方向返回当前样式在样式清单中的上一个或下一个名称。"""
        names = self._style_switch_candidates()
        if not names:
            return LCD_STYLE
        current_style = self._renderer.style_name()
        try:
            index = names.index(current_style)
        except ValueError:
            try:
                index = names.index(self._button_style_override)
            except ValueError:
                index = 0
        return names[(index + direction) % len(names)]

    def _apply_button_style(self, style_name, snapshot):
        """应用按键选择的样式，并强制下一帧完整刷新。"""
        if snapshot is None:
            self._protocol.write(b"BUTTON:LCD_STYLE_IGNORED:NO_SNAPSHOT\n")
            return
        try:
            changed = self._set_style_after_system_boot(style_name)
        except (ImportError, MemoryError, TypeError, ValueError) as error:
            if isinstance(error, MemoryError):
                self._failed_custom_style = style_name
                gc.collect()
            self._protocol.write(
                "BUTTON:LCD_STYLE_ERROR:{}:{}\n".format(
                    style_name, error
                ).encode("utf-8")
            )
            return
        self._button_style_override = self._renderer.style_name()
        self._rendering_version = -1
        self._renderer.request_render(snapshot or {}, force=True)
        if changed:
            self._protocol.write(
                "BUTTON:LCD_STYLE:{}\n".format(
                    self._renderer.style_name()
                ).encode("utf-8")
            )

    def _handle_button_actions(self, actions, snapshot):
        """处理本轮按键动作，样式键立即切换，功能键暂时仅上报事件。"""
        for action in actions:
            if action == "style_previous":
                self._apply_button_style(
                    self._neighbor_style_name(-1), snapshot
                )
            elif action == "style_next":
                self._apply_button_style(
                    self._neighbor_style_name(1), snapshot
                )
            elif action == "function":
                self._protocol.write(b"BUTTON:FUNCTION:RESERVED\n")

    def _update_renderer_with_fallback(self, snapshot):
        """刷新一个区域，并在可恢复的渲染内存不足时降级到启动页。"""
        try:
            return self._renderer.update_pending(max_regions=1)
        except MemoryError as error:
            failed_style = self._renderer.style_name()
            self._protocol.write(
                "MEMORY:RENDER_RECOVERY:{}:{}\n".format(
                    failed_style, error,
                ).encode("utf-8")
            )
            # 放弃当前复杂帧，先释放其快照、脏区和字形缓存；显示启动页虽会
            # 变慢，但可继续处理 USB 数据，避免直接触发整机硬复位。
            self._renderer.abort_render(release_snapshot=True)
            gc.collect()
            self._renderer.set_style("boot")
            self._boot_logs = ["MEMORY:RECOVERED", "STYLE:{}".format(failed_style)]
            self._show_boot(100, None, "freeing memory...", flush=False)
            self._rendering_version = -1
            return False
        except ValueError as error:
            if (
                str(error) != CANVAS_CAPACITY_ERROR
                or self._renderer.style_type() != "custom"
            ):
                raise
            failed_style = self._renderer.style_name()
            self._failed_custom_style = failed_style
            self._protocol.write(
                "CUSTOM_STYLE:RENDER_FAILED:{}:{}\n".format(
                    failed_style, error,
                ).encode("utf-8")
            )
            self._renderer.set_style(failed_style)
            self._renderer.request_render(snapshot, force=True)
            self._protocol.write(
                "CONFIG:LCD_STYLE_FALLBACK:{}:default\n".format(
                    failed_style,
                ).encode("utf-8")
            )
            return False

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
            snapshot, version = self._cache.latest()
            self._handle_button_actions(self._buttons.update(now), snapshot)
            # Monitor 被强制结束后，USB CDC 可能持续报告端点可读或遗留半包，
            # 此时接收器会一直处于忙状态。超时判断必须先于忙状态短路，
            # 否则主循环永远无法切换回 SYSTEM BOOT 等待页。
            if self._monitor_timed_out(now):
                self._return_to_waiting_page()
                continue
            if self._receiver.is_busy():
                time.sleep_ms(0)
                continue
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
                self._dev_mode = bool(display.get("dev"))
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
                display_style = display.get("style", LCD_STYLE)
                if display_style != self._last_display_style:
                    self._button_style_override = None
                    self._last_display_style = display_style
                requested_style = self._button_style_override or display_style
                # if requested_style == self._failed_custom_style:
                #     requested_style = "default"
                # elif self._failed_custom_style is not None:
                #     # 用户切换到其他样式后允许未来再次尝试已修复的同名样式。
                #     self._failed_custom_style = None
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
                    if self._set_style_after_system_boot(requested_style):
                        self._protocol.write(
                            "CONFIG:LCD_STYLE:{}\n".format(
                                self._renderer.style_name()
                            ).encode()
                        )
                except (ImportError, MemoryError, TypeError, ValueError) as error:
                    if isinstance(error, MemoryError):
                        # DashboardRenderer 已尽力恢复启动页；本轮跳过复杂样式，
                        # 后续快照将回退默认样式，不让异常进入顶层硬复位策略。
                        self._failed_custom_style = requested_style
                        ram_status = collect_memory_error_ram_status()
                        self._protocol.write(
                            (
                                "CONFIG:LCD_STYLE_ERROR:{}:{}:"
                                "RAM:ALLOC_BEFORE_GC={}:FREE_BEFORE_GC={}:"
                                "FREE_AFTER_GC={}:TOTAL={}\n"
                            ).format(
                                requested_style,
                                error,
                                ram_status[0],
                                ram_status[1],
                                ram_status[2],
                                ram_status[3],
                            ).encode("utf-8")
                        )
                    else:
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
            render_completed = self._update_renderer_with_fallback(snapshot or {})
            # system_boot 等待页使用尚未打开的应用 CDC；此时若发送帧完成
            # ACK，CDC 写缓冲会持续返回零并阻塞主循环。仅在 Monitor 已
            # 恢复连接后发送渲染性能信息，等待动画本身仍可正常推进。
            if render_completed and self._monitor_connected and self._dev_mode:
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
    """创建可竞争的 USB/Wi-Fi 传输通道，再启动硬件应用。"""
    protocol = None
    try:
        from upgrade_manager import UpgradeManager

        from config import WIFI_ENABLED, WEBSOCKET_PATH, WEBSOCKET_PORT
        from net import TransportManager
        from usb_transport import create_data_cdc

        transport = TransportManager(
            usb_stream=create_data_cdc(wait_for_open=False),
            wifi_enabled=WIFI_ENABLED,
            websocket_port=WEBSOCKET_PORT,
            websocket_path=WEBSOCKET_PATH,
        )
        protocol = JsonProtocol(stream=transport)
        protocol.set_command_services({
            "transport": transport,
            "wifi": transport.wifi,
        })
        protocol._upgrade_manager = UpgradeManager(protocol.write_upgrade_response)
        Application(protocol, transport=transport).run()
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
        if should_restart_after_fatal(error):
            # 内存耗尽或脏矩形容量配置错误均无法由当前渲染循环自行恢复。
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
