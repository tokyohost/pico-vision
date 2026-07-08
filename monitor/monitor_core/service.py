"""系统指标采集与 Pico 通信服务。"""

import json
import logging
import os
import platform
import queue
import socket
import threading
import time
from datetime import datetime

import serial

from collectTask import CollectionCoordinator, LockFreeSnapshotStore
from custom_data import get_manager as get_custom_data_manager
from pico_client import PicoJsonClient, PicoRestartingError
from qbittorrent_monitor import QbittorrentMonitor
from system_monitor import SystemInformationCollector

from .runtime_operations import RuntimeOperationsMixin
from .style_commands import BUILTIN_LCD_STYLES, StyleCommandMixin

LOGGER = logging.getLogger("pico-monitor")


class MonitorService(StyleCommandMixin, RuntimeOperationsMixin):
    """管理系统指标采集、Pico 连接以及异常重连。"""

    def __init__(self, arguments):
        """根据命令行配置创建采集器、串口客户端和停止事件。"""
        self.arguments = arguments
        self.collector = SystemInformationCollector(arguments.ping_target)
        self.qbittorrent_monitor = None
        if arguments.qbittorrent_enabled:
            LOGGER.info(
                "qBittorrent 采集配置：启用=是，地址=%s，账号=%s，密码=%s，采集间隔=%.1f 秒",
                arguments.qbittorrent_address,
                arguments.qbittorrent_username,
                "已配置" if arguments.qbittorrent_password else "未配置",
                arguments.qbittorrent_interval,
            )
            self.qbittorrent_monitor = QbittorrentMonitor(
                arguments.qbittorrent_address,
                arguments.qbittorrent_username,
                arguments.qbittorrent_password,
                arguments.qbittorrent_interval,
            )
            self.qbittorrent_monitor.start()
        self.client = PicoJsonClient(arguments.port, arguments.serial_probe_interval)
        self.stopping = threading.Event()
        self.reboot_requested = threading.Event()
        self.custom_style_catalog_requested = threading.Event()
        self.custom_style_uploads = queue.Queue()
        self.custom_style_deletes = queue.Queue()
        self.screenshot_requested = threading.Event()
        self.available_styles = set(BUILTIN_LCD_STYLES)
        self._snapshot_store = LockFreeSnapshotStore(self._create_initial_snapshot(arguments))
        self._latest_collected_snapshot = self._snapshot_store.snapshot()
        self._latest_collection_error = None
        self._collection_thread = None
        self.custom_data_manager = get_custom_data_manager()
        extra_collection_tasks = self._custom_data_collection_tasks()
        if self.qbittorrent_monitor is not None:
            extra_collection_tasks.append(("qbittorrent", self._collect_qbittorrent_fragment, 1.0, "qBittorrent"))
        self._collection_coordinator = CollectionCoordinator(
            self.collector,
            self._snapshot_store,
            self._complete_collection_fragment,
            extra_collection_tasks,
            arguments.collection_task_intervals,
        )

    @staticmethod
    def _create_initial_snapshot(arguments):
        """创建连接后立即发送的完整默认快照，真实采集结果稍后原子替换。"""
        empty_history = [0] * 24
        return {
            "version": 1,
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "host": socket.gethostname(),
            "platform": platform.system(),
            "uptime_seconds": None,
            "cpu": {
                "percent": None,
                "frequency_ghz": None,
                "temperature_c": None,
                "history": list(empty_history),
            },
            "memory": {
                "percent": None,
                "used_bytes": None,
                "total_bytes": None,
                "history": list(empty_history),
            },
            "disk": {"percent": None, "used_bytes": None, "total_bytes": None},
            "disks": [],
            "physical_disks": [],
            "gpu": None,
            "fps": {
                "value": None,
                "history": list(empty_history),
                "source": "unavailable",
                "process_id": None,
                "process_name": "",
            },
            "power": {
                "watts": None,
                "source": "unavailable",
                "scope": "unavailable",
                "history": [],
            },
            "network": {
                "upload_bps": None,
                "download_bps": None,
                "transmit_bytes": None,
                "receive_bytes": None,
                "link_speed_mbps": None,
                "upload_history": list(empty_history),
                "download_history": list(empty_history),
                "ping_ms": None,
                "online": False,
                "ip": None,
            },
            "ext": {},
            "display": {
                "rotation": arguments.screen_rotation,
                "brightness": getattr(arguments, "lcd_brightness", 100),
                "collection_interval_ms": max(1, round(arguments.interval * 1000)),
                "network_unit": arguments.network_unit,
                "style": arguments.lcd_style,
            },
        }


    def close(self):
        """释放采集器持有的原生资源及其启动的外部子进程。"""
        coordinator = getattr(self, "_collection_coordinator", None)
        if coordinator is not None:
            coordinator.close(wait=True)
        self.collector.close()

    def run(self):
        """持续连接设备、采集指标并发送最新系统快照。"""
        LOGGER.info("监控服务启动：端口=%s，Ping=%s，发送间隔=%.1f 秒，重连间隔=%.1f 秒，屏幕旋转=%d°，网络单位=%s，LCD 样式=%s，开发模式=%s", self.arguments.port or "自动发现", self.arguments.ping_target, self.arguments.interval, self.arguments.reconnect_interval, self.arguments.screen_rotation, self.arguments.network_unit, self.arguments.lcd_style, "开启" if self.arguments.dev else "关闭")
        self._start_collection_worker()
        while not self.stopping.is_set():
            probing = not self.client.is_connected
            ports_before_probe = self.client.available_ports()
            try:
                if not self.client.is_connected:
                    LOGGER.info("正在搜索 Pico LCD 设备")
                    try:
                        self.client.connect()
                    except (OSError, RuntimeError, serial.SerialException):
                        if self.arguments.dev:
                            self.client.close()
                            result = self._run_development_loop()
                            if result is not None:
                                return result
                            continue
                        raise
                    LOGGER.info("Pico LCD 已连接：%s", self.client.port_name)
                    self._synchronize_style_catalog()
                if self.arguments.upgrade_pico:
                    return self._upgrade_pico()
                if self.custom_style_catalog_requested.is_set():
                    self._publish_custom_style_catalog()
                if self.screenshot_requested.is_set():
                    self._publish_screenshot()
                if not self.custom_style_uploads.empty():
                    self._publish_custom_style_upload()
                if not self.custom_style_deletes.empty():
                    self._publish_custom_style_delete()
                    continue
                started = time.monotonic()
                snapshot = self._snapshot_for_sending()
                if self.arguments.dev:
                    self._print_development_snapshot(snapshot)
                self.client.send(snapshot)
                if self.arguments.once:
                    return 0
                remaining = self.arguments.interval - (time.monotonic() - started)
                self.stopping.wait(max(0.0, remaining))
            except (OSError, RuntimeError, serial.SerialException) as error:
                LOGGER.warning("监控通信异常：%s；准备重新连接", error)
                self.client.close()
                if isinstance(error, PicoRestartingError):
                    self.stopping.wait(self.arguments.reconnect_interval)
                    continue
                # 探测失败和已连接后的通信异常都按固定间隔重新握手，避免同名 COM 口常驻时卡在等待新增端口。
                if not probing:
                    LOGGER.info(
                        "串口连接已断开，%.1f 秒后重新探测 Pico LCD",
                        self.arguments.reconnect_interval,
                    )
                self.stopping.wait(self.arguments.reconnect_interval)
                continue
        reboot_requested = getattr(self, "reboot_requested", None)
        reboot_result = None
        if reboot_requested is not None and reboot_requested.is_set() and self.client.is_connected:
            try:
                self.client.reboot()
                reboot_result = {"status": "ok", "message": "设备已确认重启"}
            except (OSError, RuntimeError, serial.SerialException) as error:
                LOGGER.warning("Pico 重启指令下发失败：%s", error)
                reboot_result = {"status": "error", "message": str(error)}
        elif reboot_requested is not None and reboot_requested.is_set():
            reboot_result = {"status": "error", "message": "当前没有已连接设备"}
        self.client.close()
        if reboot_result is not None:
            print(
                "DEVICE_REBOOT_RESULT:" + json.dumps(reboot_result, ensure_ascii=False),
                flush=True,
            )
        LOGGER.info("监控服务已停止")
        return 0
