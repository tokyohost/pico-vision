"""监控数据采集、升级和开发模式运行操作。"""

import faulthandler
import logging
import os
import queue
import sys
import threading
import time
from collections import deque

import psutil

from build_info import GITHUB_REPOSITORY, MONITOR_VERSION
from pico_client import JsonAckTimeoutError, PicoJsonClient
from pico_upgrade import PicoFirmwareUpgrader, PicoUpgradeDownloader, PicoUpgradePackage

LOGGER = logging.getLogger("pico-monitor")
TRANSMIT_STOP = object()
ADAPTIVE_ACK_HISTORY_SIZE = 8
ADAPTIVE_ACK_SAFETY_FACTOR = 1.25
ADAPTIVE_ACK_INTERVAL_CHANGE_LOG_RATIO = 0.1
MINIMUM_TRANSMIT_INTERVAL_SECONDS = 0.3


class RuntimeOperationsMixin:
    """提供后台采集、固件升级和开发模式辅助操作。"""

    def _start_collection_worker(self):
        """启动唯一的指标采集线程，全部可能阻塞的操作都在该线程执行。"""
        if self._collection_thread is not None and self._collection_thread.is_alive():
            return
        self._collection_thread = threading.Thread(
            target=self._collection_loop,
            name="system-metrics-collector",
            daemon=True,
        )
        self._collection_thread.start()

    def _collection_loop(self):
        """按配置周期调度独立采集子任务，不等待上一批慢任务完成。"""
        while not self.stopping.is_set():
            started = time.monotonic()
            self._collection_coordinator.schedule()
            custom_data_coordinator = getattr(self, "_custom_data_coordinator", None)
            if custom_data_coordinator is not None:
                custom_data_coordinator.schedule()
            schedule_delay = self._collection_coordinator.next_schedule_delay()
            if custom_data_coordinator is not None:
                schedule_delay = min(schedule_delay, custom_data_coordinator.next_schedule_delay())
            remaining = min(self.arguments.interval, schedule_delay) - (time.monotonic() - started)
            self.stopping.wait(max(0.0, remaining))

    def _ensure_transmit_state(self):
        """按需初始化异步发送状态，兼容测试中的轻量服务实例。"""
        if not hasattr(self, "_transmit_queue"):
            self._transmit_queue = queue.Queue(maxsize=1)
        if not hasattr(self, "_transmit_lock"):
            self._transmit_lock = threading.Lock()
        if not hasattr(self, "_transmit_error_event"):
            self._transmit_error_event = threading.Event()
        if not hasattr(self, "_transmit_thread"):
            self._transmit_thread = None
        if not hasattr(self, "_transmit_sending"):
            self._transmit_sending = False
        if not hasattr(self, "_transmit_error"):
            self._transmit_error = None
        if not hasattr(self, "_transmit_dropped_snapshots"):
            self._transmit_dropped_snapshots = 0
        if not hasattr(self, "_transmit_replaced_snapshots"):
            self._transmit_replaced_snapshots = 0
        if not hasattr(self, "_adaptive_interval_lock"):
            self._adaptive_interval_lock = threading.Lock()
        if not hasattr(self, "_adaptive_ack_seconds"):
            self._adaptive_ack_seconds = deque(maxlen=ADAPTIVE_ACK_HISTORY_SIZE)
        if not hasattr(self, "_adaptive_interval_seconds"):
            self._adaptive_interval_seconds = None
        if not hasattr(self, "_json_ack_suspended"):
            self._json_ack_suspended = False
        if not hasattr(self, "_thread_diagnostics_thread"):
            self._thread_diagnostics_thread = None
        if not hasattr(self, "_thread_diagnostics_active"):
            self._thread_diagnostics_active = False

    def _start_transmit_worker(self):
        """启动唯一的 JSON 快照发送线程，避免串口写入阻塞主监控循环。"""
        self._ensure_transmit_state()
        transmit_thread = getattr(self, "_transmit_thread", None)
        if transmit_thread is not None and transmit_thread.is_alive():
            return
        self._clear_transmit_queue()
        with self._transmit_lock:
            self._transmit_error = None
            self._transmit_error_event.clear()
            self._transmit_sending = False
        self._transmit_thread = threading.Thread(
            target=self._transmit_loop,
            name="pico-json-transmitter",
            daemon=True,
        )
        self._transmit_thread.start()

    def _start_thread_diagnostics(self):
        """按需启动线程诊断，周期记录线程清单并让 faulthandler 输出全线程栈。"""
        if not bool(getattr(self.arguments, "thread_diagnostics", False)):
            return
        self._ensure_transmit_state()
        diagnostics_thread = getattr(self, "_thread_diagnostics_thread", None)
        if diagnostics_thread is not None and diagnostics_thread.is_alive():
            return
        interval = max(1.0, float(getattr(self.arguments, "thread_diagnostics_interval", 10.0)))
        if faulthandler.is_enabled():
            faulthandler.cancel_dump_traceback_later()
        else:
            faulthandler.enable(file=sys.stderr, all_threads=True)
        faulthandler.dump_traceback_later(
            interval,
            repeat=True,
            file=sys.stderr,
            exit=False,
        )
        self._thread_diagnostics_thread = threading.Thread(
            target=self._thread_diagnostics_loop,
            args=(interval,),
            name="thread-diagnostics",
            daemon=True,
        )
        self._thread_diagnostics_thread.start()
        self._thread_diagnostics_active = True
        LOGGER.info(
            "线程诊断已开启：间隔=%.1f 秒，将输出 threading.enumerate() 摘要和 faulthandler 全线程栈",
            interval,
        )

    def _stop_thread_diagnostics(self):
        """关闭线程诊断定时器，避免服务退出后继续输出栈信息。"""
        diagnostics_thread = getattr(self, "_thread_diagnostics_thread", None)
        if getattr(self, "_thread_diagnostics_active", False):
            faulthandler.cancel_dump_traceback_later()
        if diagnostics_thread is not None and diagnostics_thread.is_alive():
            diagnostics_thread.join(timeout=1.0)
        self._thread_diagnostics_thread = None
        self._thread_diagnostics_active = False

    def _thread_diagnostics_loop(self, interval):
        """周期输出当前 Python 线程清单，用于核对发送线程是否存活。"""
        while not self.stopping.is_set():
            self._log_thread_enumeration()
            self.stopping.wait(interval)

    def _log_thread_enumeration(self):
        """记录 threading.enumerate() 的名称、标识和存活状态摘要。"""
        threads = threading.enumerate()
        summary = []
        for thread in threads:
            summary.append(
                "{}(ident={},native_id={},alive={},daemon={})".format(
                    thread.name,
                    thread.ident,
                    getattr(thread, "native_id", None),
                    thread.is_alive(),
                    thread.daemon,
                )
            )
        LOGGER.warning(
            "线程诊断 threading.enumerate()：数量=%d；%s",
            len(threads),
            "；".join(summary),
        )

    def _stop_transmit_worker(self, wait=True):
        """停止 JSON 快照发送线程，并清理尚未发送的待发快照。"""
        self._ensure_transmit_state()
        transmit_thread = getattr(self, "_transmit_thread", None)
        transmit_queue = getattr(self, "_transmit_queue", None)
        if transmit_queue is None:
            return
        self._clear_transmit_queue()
        if transmit_thread is not None and transmit_thread.is_alive():
            try:
                transmit_queue.put_nowait(TRANSMIT_STOP)
            except queue.Full:
                self._clear_transmit_queue()
                transmit_queue.put_nowait(TRANSMIT_STOP)
            if wait:
                transmit_thread.join()
        self._transmit_thread = None
        with self._transmit_lock:
            self._transmit_sending = False

    def _clear_transmit_queue(self):
        """清空待发送队列，丢弃断线或停止前尚未发送的旧快照。"""
        self._ensure_transmit_state()
        transmit_queue = getattr(self, "_transmit_queue", None)
        if transmit_queue is None:
            return
        while True:
            try:
                transmit_queue.get_nowait()
            except queue.Empty:
                return
            transmit_queue.task_done()

    def _transmit_loop(self):
        """从容量为一的队列取出快照并串行写入 Pico 串口。"""
        self._ensure_transmit_state()
        while not self.stopping.is_set():
            try:
                snapshot = self._transmit_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if snapshot is TRANSMIT_STOP:
                    return
                with self._transmit_lock:
                    self._transmit_sending = True
                adaptive_transmit = bool(getattr(self.arguments, "adaptive_transmit", True))
                # ACK 是串口流量控制，不是自适应采集间隔的附属能力。即使用户
                # 关闭自适应，也必须限制为一条在途 JSON，避免设备忙于样式加载
                # 或渲染时持续写满 CDC OUT 缓冲并触发 Windows WriteFile 失败。
                wait_ack = True
                ack_timeout = max(15.0, self._effective_transmit_interval() * 3.0)
                send_started = time.monotonic()
                try:
                    self.client.send(
                        snapshot,
                        wait_ack=wait_ack,
                        ack_timeout=ack_timeout,
                    )
                except JsonAckTimeoutError as error:
                    # 快照写入已经完成，缺少 ACK 只能说明设备端未确认该能力，
                    # 不能据此关闭仍然可用的串口，也不能降级为无限异步写入。
                    # 后续快照继续以 ACK 门控重试，保持 CDC 缓冲始终有上界。
                    LOGGER.warning(
                        "%s；当前连接保持 JSON ACK 背压并在下一帧重试，串口不会重连",
                        error,
                    )
                    continue
                if adaptive_transmit:
                    self._record_json_ack_duration(time.monotonic() - send_started)
            except (OSError, RuntimeError) as error:
                with self._transmit_lock:
                    self._transmit_error = error
                    self._transmit_error_event.set()
                return
            finally:
                with self._transmit_lock:
                    self._transmit_sending = False
                self._transmit_queue.task_done()

    def _replace_pending_snapshot(self, snapshot):
        """用最新快照覆盖尚未发送的旧快照，保持 Pico 只追赶最新状态。"""
        replaced = False
        while True:
            try:
                pending = self._transmit_queue.get_nowait()
            except queue.Empty:
                break
            if pending is TRANSMIT_STOP:
                self._transmit_queue.put_nowait(TRANSMIT_STOP)
                self._transmit_queue.task_done()
                return False
            replaced = True
            self._transmit_queue.task_done()
        try:
            self._transmit_queue.put_nowait(snapshot)
        except queue.Full:
            return False
        if replaced:
            self._transmit_replaced_snapshots += 1
            if self._transmit_replaced_snapshots == 1 or self._transmit_replaced_snapshots % 10 == 0:
                LOGGER.info(
                    "JSON ACK 背压生效，已用最新快照合并待发数据：累计合并=%d",
                    self._transmit_replaced_snapshots,
                )
        return True

    def _submit_snapshot_for_transmission(self, snapshot):
        """提交最新快照；自适应开启时保留最新待发快照，关闭时沿用丢帧策略。"""
        self._ensure_transmit_state()
        self._raise_transmit_error_if_any()
        transmit_thread = getattr(self, "_transmit_thread", None)
        if transmit_thread is None or not transmit_thread.is_alive():
            self._start_transmit_worker()
        adaptive_transmit = bool(getattr(self.arguments, "adaptive_transmit", True))
        with self._transmit_lock:
            if self._transmit_sending:
                if adaptive_transmit:
                    return self._replace_pending_snapshot(snapshot)
                self._transmit_dropped_snapshots += 1
                LOGGER.debug(
                    "JSON 快照发送仍在进行，丢弃本轮快照：累计丢弃=%d",
                    self._transmit_dropped_snapshots,
                )
                return False
        try:
            self._transmit_queue.put_nowait(snapshot)
            return True
        except queue.Full:
            if adaptive_transmit:
                return self._replace_pending_snapshot(snapshot)
            self._transmit_dropped_snapshots += 1
            LOGGER.debug(
                "JSON 快照发送队列已有待发数据，丢弃本轮快照：累计丢弃=%d",
                self._transmit_dropped_snapshots,
            )
            return False

    def _raise_transmit_error_if_any(self):
        """把发送线程捕获到的通信异常转交主循环，由原有重连逻辑处理。"""
        self._ensure_transmit_state()
        with self._transmit_lock:
            error = self._transmit_error
            self._transmit_error = None
            self._transmit_error_event.clear()
        if error is not None:
            raise error

    def _base_transmit_interval(self):
        """返回用户配置的基础发送间隔，并把最低发送时延限制为三百毫秒。"""
        try:
            return max(MINIMUM_TRANSMIT_INTERVAL_SECONDS, float(getattr(self.arguments, "interval", 0.5)))
        except (TypeError, ValueError):
            return 0.5

    def _effective_transmit_interval(self):
        """返回当前实际发送间隔；自适应关闭时等于基础间隔。"""
        base_interval = self._base_transmit_interval()
        if not bool(getattr(self.arguments, "adaptive_transmit", True)):
            return base_interval
        self._ensure_transmit_state()
        with self._adaptive_interval_lock:
            if self._adaptive_interval_seconds is None:
                return base_interval
            return max(MINIMUM_TRANSMIT_INTERVAL_SECONDS, self._adaptive_interval_seconds)

    def _record_json_ack_duration(self, elapsed_seconds):
        """根据最近 JSON ACK 耗时刷新自适应发送间隔。"""
        self._ensure_transmit_state()
        try:
            elapsed_seconds = max(0.0, float(elapsed_seconds))
        except (TypeError, ValueError):
            return
        base_interval = self._base_transmit_interval()
        max_interval = max(15.0, base_interval * 30.0)
        with self._adaptive_interval_lock:
            self._adaptive_ack_seconds.append(elapsed_seconds)
            samples = sorted(self._adaptive_ack_seconds)
            p90_index = min(len(samples) - 1, int((len(samples) - 1) * 0.9))
            target_interval = max(
                MINIMUM_TRANSMIT_INTERVAL_SECONDS,
                min(max_interval, samples[p90_index] * ADAPTIVE_ACK_SAFETY_FACTOR),
            )
            previous_interval = self._adaptive_interval_seconds or base_interval
            if target_interval > previous_interval:
                next_interval = target_interval
            else:
                next_interval = max(
                    MINIMUM_TRANSMIT_INTERVAL_SECONDS,
                    previous_interval * 0.7 + target_interval * 0.3,
                )
            self._adaptive_interval_seconds = next_interval
        if (
                abs(next_interval - previous_interval)
                >= max(0.05, previous_interval * ADAPTIVE_ACK_INTERVAL_CHANGE_LOG_RATIO)
        ):
            LOGGER.info(
                "JSON ACK 自适应发送间隔更新：ACK样本=%.1f ms，发送间隔=%.3f 秒",
                elapsed_seconds * 1000,
                next_interval,
            )

    def _wait_for_interval_or_transmit_error(self, timeout):
        """等待发送间隔，同时在发送线程失败时尽快唤醒主循环。"""
        self._ensure_transmit_state()
        deadline = time.monotonic() + max(0.0, timeout)
        while not self.stopping.is_set():
            self._raise_transmit_error_if_any()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            wait_time = min(remaining, 0.1)
            if self._transmit_error_event.wait(wait_time):
                self._raise_transmit_error_if_any()
            if self.stopping.is_set():
                return

    def _wait_for_transmit_idle(self):
        """等待全部已提交快照完成发送，避免取出队列瞬间被误判为空闲。"""
        self._ensure_transmit_state()
        while not self.stopping.is_set():
            self._raise_transmit_error_if_any()
            with self._transmit_queue.all_tasks_done:
                unfinished_tasks = self._transmit_queue.unfinished_tasks
            if unfinished_tasks == 0:
                return
            self.stopping.wait(0.05)

    def _wait_for_next_transmission(self):
        """等待当前快照发送完成，再从完成时刻开始计算完整发送间隔。"""
        self._wait_for_transmit_idle()
        self._wait_for_interval_or_transmit_error(self._effective_transmit_interval())

    def _snapshot_for_sending(self):
        """返回发送视图，并在发送前叠加不属于采集任务的配置字段。"""
        snapshot_store = getattr(self, "_snapshot_store", None)
        snapshot = snapshot_store.snapshot() if snapshot_store is not None else dict(self._latest_collected_snapshot)
        snapshot["display"] = self._display_configuration_snapshot()
        return snapshot

    def _display_configuration_snapshot(self):
        """生成发送给 Pico 的显示配置快照。"""
        effective_interval = self._effective_transmit_interval()
        return {
            "rotation": self.arguments.screen_rotation,
            "brightness": getattr(self.arguments, "lcd_brightness", 100),
            "collection_interval_ms": max(1, round(effective_interval * 1000)),
            "adaptive_transmit": bool(getattr(self.arguments, "adaptive_transmit", True)),
            "network_unit": self.arguments.network_unit,
            "style": self.arguments.lcd_style,
            "dev": bool(getattr(self.arguments, "dev", False)),
        }

    def _custom_data_collection_tasks(self):
        """把启动时发现的每个自定义数据插件封装为独立采集任务。"""
        tasks = []
        for definition in self.custom_data_manager.task_definitions():
            tasks.append((
                definition.task_name,
                self._create_custom_data_collector(definition.name),
                definition.interval,
                definition.zh_name,
            ))
        return tasks

    def _create_custom_data_collector(self, name):
        """创建指定自定义数据插件的采集回调。"""
        def collect():
            """执行一个自定义数据插件并返回 ext 子字段片段。"""
            return {"ext": self.custom_data_manager.collect_task_data(name)}

        return collect

    def _collect_qbittorrent_fragment(self):
        """读取 qBittorrent 后台采样结果并返回独立快照片段。"""
        return {"qbittorrent": self.qbittorrent_monitor.snapshot()}

    def _complete_collection_fragment(self, fragment):
        """处理单项采样结果，不混入发送层配置字段。"""
        fragment = dict(fragment)
        if "disks" in fragment:
            self._apply_disk_health_test(fragment)
        if "ext" in fragment:
            ext = dict(self._snapshot_store.snapshot().get("ext") or {})
            ext.update(fragment["ext"])
            fragment["ext"] = ext
        self._latest_collection_error = None
        return fragment

    def _wait_for_usb_addition(self, previous_ports):
        """等待新串口插入，拔出时只更新基线而不发起 Pico 握手。"""
        baseline = frozenset(previous_ports)
        while not self.stopping.is_set():
            current_ports = self.client.available_ports()
            if current_ports - baseline:
                return True
            baseline = current_ports
            self.stopping.wait(0.5)
        return False

    def _upgrade_pico(self):
        """下载当前 Monitor 版本升级包，完成串口升级后退出。"""
        url = self.arguments.upgrade_url
        if not url:
            if not GITHUB_REPOSITORY or MONITOR_VERSION == "development":
                raise RuntimeError("开发版本必须通过 --upgrade-url 指定 Pico 升级包")
            url = "https://github.com/{}/releases/download/v{}/OmniWatch-pico-upgrade-v{}.zip".format(
                GITHUB_REPOSITORY, MONITOR_VERSION, MONITOR_VERSION
            )
        archive_path = PicoUpgradeDownloader.download(url, self.arguments.upgrade_sha256)
        package = None
        try:
            package = PicoUpgradePackage(archive_path)
            LOGGER.info("[升级校验] 版本=%s，文件数=%d", package.version, len(package.files))
            PicoFirmwareUpgrader(self.client).upgrade(package)
            return 0
        finally:
            if package is not None:
                package.close()
            try:
                os.remove(archive_path)
            except OSError:
                pass

    def _run_development_loop(self):
        """未发现 Pico 时持续打印 JSON；关闭开发模式后返回连接循环。"""
        while not self.stopping.is_set() and self.arguments.dev:
            started = time.monotonic()
            self._print_development_snapshot(self._snapshot_for_sending())
            if self.arguments.once:
                return 0
            remaining = self.arguments.interval - (time.monotonic() - started)
            self.stopping.wait(max(0.0, remaining))
        return 0 if self.stopping.is_set() else None

    def _collect_snapshot(self):
        """采集系统指标并补充 Pico 显示配置。"""
        started = time.monotonic()
        snapshot = self.collector.collect()
        system_elapsed = time.monotonic() - started
        stage_started = time.monotonic()
        if self.qbittorrent_monitor is not None:
            snapshot["qbittorrent"] = self.qbittorrent_monitor.snapshot()
        qbittorrent_elapsed = time.monotonic() - stage_started
        stage_started = time.monotonic()
        self._apply_disk_health_test(snapshot)
        disk_test_elapsed = time.monotonic() - stage_started
        stage_started = time.monotonic()
        custom_ext = {}
        for definition in self.custom_data_manager.task_definitions():
            custom_ext.update(self.custom_data_manager.collect_task_data(definition.name))
        snapshot["ext"] = custom_ext
        custom_elapsed = time.monotonic() - stage_started
        total_elapsed = time.monotonic() - started
        log_method = LOGGER.warning if total_elapsed > 0.5 else LOGGER.debug
        log_method(
            "系统快照采集耗时：总计=%.3f秒，系统指标=%.3f秒，qBittorrent=%.3f秒，"
            "磁盘测试覆盖=%.3f秒，自定义扩展=%.3f秒",
            total_elapsed,
            system_elapsed,
            qbittorrent_elapsed,
            disk_test_elapsed,
            custom_elapsed,
        )
        return snapshot

    def _apply_disk_health_test(self, snapshot):
        """按命令行指定的磁盘序号覆盖健康等级，用于验证 LCD 告警效果。"""
        disk_index = int(getattr(self.arguments, "disk_health_test_index", 0) or 0)
        if disk_index <= 0:
            return
        health = int(getattr(self.arguments, "disk_health_test_level", 3))
        physical_disks = snapshot.get("physical_disks") or snapshot.get("disks", ())
        # 后台磁盘采集尚未完成时列表为空，此时不能判定测试序号配置错误。
        if not physical_disks:
            return
        if disk_index > len(physical_disks):
            warning_key = (disk_index, len(physical_disks))
            if getattr(self, "_disk_health_test_warning_key", None) != warning_key:
                LOGGER.warning("磁盘健康测试序号超出范围：index=%d，磁盘数量=%d", disk_index, len(physical_disks))
                self._disk_health_test_warning_key = warning_key
            return
        self._disk_health_test_warning_key = None
        selected = physical_disks[disk_index - 1]
        selected["health"] = health
        selected_name = selected.get("name")
        for disk in snapshot.get("disks", ()):
            if disk is selected or (selected_name and disk.get("name") == selected_name):
                disk["health"] = health

    def _print_development_snapshot(self, snapshot=None):
        """打印实际进入压缩和发送流程的紧凑 JSON 内容。"""
        try:
            if snapshot is None:
                snapshot = self._snapshot_for_sending()
            LOGGER.info(
                "[DEV][Monitor -> Pico][JSON] %s",
                PicoJsonClient.build_json_payload(snapshot).decode("utf-8"),
            )
        except (OSError, TypeError, ValueError, psutil.Error) as error:
            LOGGER.warning("[DEV][JSON] 系统指标采集或 JSON 序列化失败：%s", error)
