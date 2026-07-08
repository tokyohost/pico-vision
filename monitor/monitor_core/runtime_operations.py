"""监控数据采集、升级和开发模式运行操作。"""

import logging
import os
import threading
import time

import psutil

from build_info import GITHUB_REPOSITORY, MONITOR_VERSION
from pico_client import PicoJsonClient
from pico_upgrade import PicoFirmwareUpgrader, PicoUpgradeDownloader, PicoUpgradePackage

LOGGER = logging.getLogger("pico-monitor")


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
            schedule_delay = self._collection_coordinator.next_schedule_delay()
            remaining = min(self.arguments.interval, schedule_delay) - (time.monotonic() - started)
            self.stopping.wait(max(0.0, remaining))

    def _snapshot_for_sending(self):
        """无锁返回采集线程原子发布的最近一次完整快照。"""
        snapshot_store = getattr(self, "_snapshot_store", None)
        return snapshot_store.snapshot() if snapshot_store is not None else self._latest_collected_snapshot

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
        """为单项采样结果补充显示配置，并处理磁盘健康测试覆盖。"""
        fragment = dict(fragment)
        if "disks" in fragment:
            self._apply_disk_health_test(fragment)
        if "ext" in fragment:
            ext = dict(self._snapshot_store.snapshot().get("ext") or {})
            ext.update(fragment["ext"])
            fragment["ext"] = ext
        fragment["display"] = {
            "rotation": self.arguments.screen_rotation,
            "brightness": getattr(self.arguments, "lcd_brightness", 100),
            "collection_interval_ms": max(1, round(self.arguments.interval * 1000)),
            "network_unit": self.arguments.network_unit,
            "style": self.arguments.lcd_style,
        }
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
        snapshot["display"] = {
            "rotation": self.arguments.screen_rotation,
            "brightness": getattr(self.arguments, "lcd_brightness", 100),
            "collection_interval_ms": max(1, round(self.arguments.interval * 1000)),
            "network_unit": self.arguments.network_unit,
            "style": self.arguments.lcd_style,
        }
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


