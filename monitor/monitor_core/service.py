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
from urllib.parse import urlsplit

import serial

from collectTask import CollectionCoordinator, LockFreeSnapshotStore
from custom_data import CustomDataCollectionCoordinator
from custom_data import get_manager as get_custom_data_manager
from pico_client import PicoJsonClient, PicoRestartingError
from net import LanWebSocketScanner
from qbittorrent_monitor import QbittorrentMonitor
from system_monitor import SystemInformationCollector

from .runtime_operations import RuntimeOperationsMixin
from .style_commands import BUILTIN_LCD_STYLES, StyleCommandMixin
from .wifi_commands import WifiCommandMixin
from .websocket_client_commands import WebSocketClientCommandMixin

LOGGER = logging.getLogger("pico-monitor")

WINDOWS_WEBSOCKET_DIRECT_PROBE_INTERVAL = 5.0
WINDOWS_WEBSOCKET_NETWORK_SCAN_INTERVAL = 10.0
WINDOWS_WEBSOCKET_FAST_PROBE_TIMEOUT = 0.15
WINDOWS_WEBSOCKET_FAST_SCAN_WORKERS = 32
LINUX_WEBSOCKET_NETWORK_SCAN_INTERVAL = 30.0
LINUX_WEBSOCKET_FAST_PROBE_TIMEOUT = 0.15
LINUX_WEBSOCKET_FAST_SCAN_WORKERS = 16


class MonitorService(WebSocketClientCommandMixin, WifiCommandMixin, StyleCommandMixin, RuntimeOperationsMixin):
    """管理系统指标采集、Pico 连接以及异常重连。"""

    def __init__(self, arguments):
        """根据命令行配置创建采集器、串口客户端和停止事件。"""
        self.arguments = arguments
        self.collector = SystemInformationCollector(
            arguments.ping_target,
            getattr(arguments, "sensor_host_enabled", True),
            getattr(arguments, "sensor_host_path", None),
            getattr(arguments, "sensor_host_pipe", "omniwatch.sensorhost"),
        )
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
        self.client = PicoJsonClient(
            arguments.port,
            arguments.serial_probe_interval,
            websocket_url=getattr(arguments, "websocket_url", None),
            websocket_client_name=getattr(arguments, "websocket_client_name", None),
            websocket_client_id=getattr(arguments, "websocket_client_id", None),
        )
        self.stopping = threading.Event()
        self.reboot_requested = threading.Event()
        self.custom_style_catalog_requested = threading.Event()
        self.custom_style_uploads = queue.Queue()
        self.custom_style_deletes = queue.Queue()
        self.screenshot_requested = threading.Event()
        self.initialize_wifi_commands()
        self.initialize_websocket_client_commands()
        self.available_styles = set(BUILTIN_LCD_STYLES)
        self._snapshot_store = LockFreeSnapshotStore(self._create_initial_snapshot(arguments))
        self._latest_collected_snapshot = self._snapshot_store.snapshot()
        self._latest_collection_error = None
        self._collection_thread = None
        self._transmit_thread = None
        self._transmit_queue = queue.Queue(maxsize=1)
        self._transmit_lock = threading.Lock()
        self._transmit_sending = False
        self._transmit_error = None
        self._transmit_error_event = threading.Event()
        self._transmit_dropped_snapshots = 0
        self.custom_data_manager = get_custom_data_manager()
        self.custom_data_manager.prepare_environments_async()
        extra_collection_tasks = []
        if self.qbittorrent_monitor is not None:
            extra_collection_tasks.append(("qbittorrent", self._collect_qbittorrent_fragment, 1.0, "qBittorrent"))
        self._collection_coordinator = CollectionCoordinator(
            self.collector,
            self._snapshot_store,
            self._complete_collection_fragment,
            extra_collection_tasks,
            arguments.collection_task_intervals,
            arguments.collection_task_logs,
        )
        self._custom_data_coordinator = CustomDataCollectionCoordinator(
            self.custom_data_manager,
            self._snapshot_store,
            self._complete_collection_fragment,
            arguments.collection_task_intervals,
            arguments.collection_task_logs,
        )

    def activate_custom_data_plugin(self, name):
        """将运行中新加载的自定义数据插件实时加入采集任务。"""
        definition = self._custom_data_coordinator.activate_plugin(name)
        LOGGER.info(
            "自定义数据插件实时加入 Monitor 任务：插件=%s，任务=%s",
            definition.name,
            definition.task_name,
        )
        return definition

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
                "collection_interval_ms": max(300, round(arguments.interval * 1000)),
                "adaptive_transmit": bool(getattr(arguments, "adaptive_transmit", True)),
                "network_unit": arguments.network_unit,
                "style": arguments.lcd_style,
                "dev": bool(getattr(arguments, "dev", False)),
            },
        }


    def close(self):
        """释放采集器持有的原生资源及其启动的外部子进程。"""
        self._stop_thread_diagnostics()
        coordinator = getattr(self, "_collection_coordinator", None)
        if coordinator is not None:
            coordinator.close(wait=True)
        custom_data_coordinator = getattr(self, "_custom_data_coordinator", None)
        if custom_data_coordinator is not None:
            custom_data_coordinator.close(wait=True)
        custom_data_manager = getattr(self, "custom_data_manager", None)
        if custom_data_manager is not None:
            custom_data_manager.close()
        self._stop_transmit_worker(wait=True)
        self.collector.close()

    def _create_lan_scanner(self, port=None, path=None, fast=False, low_impact=False):
        """创建局域网扫描器；自恢复模式使用更短超时和更低并发以保护局域网。"""
        configured_timeout = getattr(self.arguments, "lan_probe_timeout", 0.3)
        configured_workers = getattr(self.arguments, "lan_probe_max_workers", 256)
        fast_timeout = (
            LINUX_WEBSOCKET_FAST_PROBE_TIMEOUT
            if low_impact
            else WINDOWS_WEBSOCKET_FAST_PROBE_TIMEOUT
        )
        fast_workers = (
            LINUX_WEBSOCKET_FAST_SCAN_WORKERS
            if low_impact
            else WINDOWS_WEBSOCKET_FAST_SCAN_WORKERS
        )
        return LanWebSocketScanner(
            port=port if port is not None else getattr(self.arguments, "lan_probe_port", 8765),
            path=path if path is not None else getattr(self.arguments, "lan_probe_path", "/pv1"),
            timeout=(
                min(configured_timeout, fast_timeout)
                if fast
                else configured_timeout
            ),
            max_workers=(
                min(configured_workers, fast_workers)
                if fast
                else configured_workers
            ),
            minimum_prefix_length=24,
        )

    def _rediscover_websocket_device(self, fast=False, low_impact=False):
        """扫描局域网候选地址，并通过 PV1 握手切换到可用 Wi-Fi 设备。"""
        scanner = self._create_lan_scanner(fast=fast, low_impact=low_impact)
        original_url = self.client.websocket_url
        LOGGER.info("开始快速扫描局域网中的 Wi-Fi 设备")
        try:
            candidates = scanner.scan()
        except (OSError, RuntimeError, ValueError) as error:
            LOGGER.warning("重新扫描 Wi-Fi 设备失败：%s", error)
            return False
        for candidate in candidates:
            self.client.websocket_url = candidate.url
            try:
                self.client.connect()
            except (OSError, RuntimeError, serial.SerialException) as error:
                LOGGER.info("Wi-Fi 候选设备确认失败：地址=%s，原因=%s", candidate.url, error)
                self.client.close()
                continue
            LOGGER.info("重新扫描 Wi-Fi 设备成功：%s", candidate.url)
            self.arguments.websocket_url = candidate.url
            return True
        self.client.websocket_url = original_url
        LOGGER.warning("重新扫描局域网未发现可连接的 Pico LCD")
        return False

    def _maybe_discover_linux_websocket(self, now=None):
        """Linux 未连接时按三十秒节流执行一次低影响局域网设备发现。"""
        if platform.system() != "Linux" or self.client.is_connected:
            return False
        current = time.monotonic() if now is None else float(now)
        next_scan = getattr(self, "_next_linux_network_scan", 0.0)
        if current < next_scan:
            return False
        self._next_linux_network_scan = current + LINUX_WEBSOCKET_NETWORK_SCAN_INTERVAL
        LOGGER.info(
            "Linux 未连接设备，开始低影响局域网扫描；下一次扫描不早于 %.0f 秒后",
            LINUX_WEBSOCKET_NETWORK_SCAN_INTERVAL,
        )
        return self._rediscover_websocket_device(fast=True, low_impact=True)

    def _probe_and_reconnect_saved_websocket(self, websocket_url):
        """快速探测保存的 WebSocket 地址，并仅在端口可用时执行完整 PV1 重连。"""
        parsed = urlsplit(websocket_url)
        if parsed.scheme != "ws" or not parsed.hostname:
            LOGGER.warning("保存的 WebSocket 地址无法用于快速探测：%s", websocket_url)
            return False
        scanner = self._create_lan_scanner(
            port=parsed.port or 80,
            path=parsed.path or "/",
            fast=True,
        )
        if not scanner.port_is_open_safely(parsed.hostname):
            LOGGER.debug("保存的 Wi-Fi 地址端口尚未开放：%s", websocket_url)
            return False
        if scanner.probe_safely(parsed.hostname) is None:
            LOGGER.debug("保存的 Wi-Fi 地址未通过 WebSocket 协议验证：%s", websocket_url)
            return False
        self.client.websocket_url = websocket_url
        try:
            self.client.connect()
        except (OSError, RuntimeError, serial.SerialException) as error:
            LOGGER.info("保存的 Wi-Fi 地址端口已响应，但 PV1 重连失败：%s", error)
            self.client.close()
            return False
        self.arguments.websocket_url = websocket_url
        LOGGER.info("保存的 Wi-Fi 设备地址已恢复：%s", websocket_url)
        return True

    def _recover_windows_websocket(self, websocket_url):
        """在 Windows 中按五秒直连、十秒扫描的节奏持续恢复 WebSocket 业务。"""
        next_direct_probe = time.monotonic() + WINDOWS_WEBSOCKET_DIRECT_PROBE_INTERVAL
        next_network_scan = time.monotonic() + WINDOWS_WEBSOCKET_NETWORK_SCAN_INTERVAL
        LOGGER.warning(
            "WebSocket 已断开；每 %.0f 秒探测原地址，每 %.0f 秒快速扫描本地网段",
            WINDOWS_WEBSOCKET_DIRECT_PROBE_INTERVAL,
            WINDOWS_WEBSOCKET_NETWORK_SCAN_INTERVAL,
        )
        while not self.stopping.is_set():
            now = time.monotonic()
            wait_seconds = max(0.0, min(next_direct_probe, next_network_scan) - now)
            if self.stopping.wait(wait_seconds):
                return False
            now = time.monotonic()
            if now >= next_direct_probe:
                next_direct_probe = now + WINDOWS_WEBSOCKET_DIRECT_PROBE_INTERVAL
                if (
                    self._probe_and_reconnect_saved_websocket(websocket_url)
                    and self._complete_websocket_recovery()
                ):
                    return True
            if now >= next_network_scan:
                next_network_scan = now + WINDOWS_WEBSOCKET_NETWORK_SCAN_INTERVAL
                if (
                    self._rediscover_websocket_device(fast=True)
                    and self._complete_websocket_recovery()
                ):
                    return True
        return False

    def _complete_websocket_recovery(self):
        """重新同步设备状态并恢复发送线程，失败时保持服务继续自恢复。"""
        try:
            LOGGER.info("Pico LCD 已恢复连接：%s", self.client.port_name)
            self._synchronize_style_catalog()
            self._start_transmit_worker()
            return True
        except (OSError, RuntimeError, serial.SerialException) as error:
            LOGGER.warning("WebSocket 已重连但业务恢复失败，将继续探测：%s", error)
            self._stop_transmit_worker(wait=True)
            self.client.close()
            return False

    def run(self):
        """持续连接设备、采集指标并发送最新系统快照。"""
        LOGGER.info(
            "监控服务启动：端口=%s，Ping=%s，发送间隔=%.1f 秒，发送自适应=%s，重连间隔=%.1f 秒，屏幕旋转=%d°，网络单位=%s，LCD 样式=%s，开发模式=%s",
            self.arguments.port or "自动发现",
            self.arguments.ping_target,
            self.arguments.interval,
            "开启" if getattr(self.arguments, "adaptive_transmit", True) else "关闭",
            self.arguments.reconnect_interval,
            self.arguments.screen_rotation,
            self.arguments.network_unit,
            self.arguments.lcd_style,
            "开启" if self.arguments.dev else "关闭",
        )
        self._start_thread_diagnostics()
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
                        if not self._maybe_discover_linux_websocket():
                            raise
                    LOGGER.info("Pico LCD 已连接：%s", self.client.port_name)
                    self._synchronize_style_catalog()
                    self._start_transmit_worker()
                if self.arguments.upgrade_pico:
                    return self._upgrade_pico()
                self._raise_transmit_error_if_any()
                has_control_operation = (
                    self.custom_style_catalog_requested.is_set()
                    or self.screenshot_requested.is_set()
                    or not self.custom_style_uploads.empty()
                    or not self.custom_style_deletes.empty()
                    or self.has_pending_wifi_operation()
                    or self.has_pending_websocket_client_operation()
                )
                if has_control_operation:
                    self._wait_for_transmit_idle()
                if self.custom_style_catalog_requested.is_set():
                    self._publish_custom_style_catalog()
                if self.screenshot_requested.is_set():
                    self._publish_screenshot()
                if not self.custom_style_uploads.empty():
                    self._publish_custom_style_upload()
                if not self.custom_style_deletes.empty():
                    self._publish_custom_style_delete()
                    continue
                if self.has_pending_wifi_operation():
                    self.publish_wifi_operation()
                    continue
                if self.has_pending_websocket_client_operation():
                    self.publish_websocket_client_operation()
                    continue
                snapshot = self._snapshot_for_sending()
                if self.arguments.dev:
                    self._print_development_snapshot(snapshot)
                self._submit_snapshot_for_transmission(snapshot)
                if self.arguments.once:
                    self._wait_for_transmit_idle()
                    return 0
                self._wait_for_next_transmission()
            except (OSError, RuntimeError, serial.SerialException) as error:
                LOGGER.warning("监控通信异常：%s；准备重新连接", error)
                self._stop_transmit_worker(wait=True)
                websocket_url = getattr(self.client, "websocket_url", None)
                self.client.close()
                if (
                    platform.system() == "Windows"
                    and isinstance(websocket_url, str)
                    and websocket_url
                    and self._recover_windows_websocket(websocket_url)
                ):
                    continue
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
        self._stop_transmit_worker(wait=True)
        self._stop_thread_diagnostics()
        self.client.close()
        if reboot_result is not None:
            print(
                "DEVICE_REBOOT_RESULT:" + json.dumps(reboot_result, ensure_ascii=False),
                flush=True,
            )
        LOGGER.info("监控服务已停止")
        return 0
