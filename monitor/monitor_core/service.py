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
from custom_data import normalize_plugin_configs, normalize_plugin_enabled
from pico_client import PicoJsonClient
from net import LanWebSocketScanner
from qbittorrent_monitor import QbittorrentMonitor
from system_monitor import SystemInformationCollector

from .runtime_operations import RuntimeOperationsMixin
from .custom_data import CustomDataServiceMixin
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


class MonitorService(
    WebSocketClientCommandMixin,
    WifiCommandMixin,
    StyleCommandMixin,
    CustomDataServiceMixin,
    RuntimeOperationsMixin,
):
    """管理系统指标采集、Pico 连接以及异常重连。"""

    @staticmethod
    def _runtime_connection_signature(arguments):
        """生成规范化连接配置签名，将未配置字段统一为空字符串。"""
        return (
            str(getattr(arguments, "port", "") or "").strip(),
            str(getattr(arguments, "websocket_url", "") or "").strip(),
            bool(getattr(arguments, "force_usb_cdc", False)),
            str(getattr(arguments, "websocket_client_name", "") or "").strip(),
            str(getattr(arguments, "websocket_client_id", "") or "").strip(),
            float(getattr(arguments, "serial_probe_interval", 0)),
        )

    @staticmethod
    def _runtime_connection_requires_reconnect(before, after, connected):
        """判断运行配置变化是否必须中断当前设备连接。"""
        if not connected:
            return after != before
        # 已建立连接时仅显式切换串口或传输模式需要立即重连；WebSocket
        # 地址、客户端身份和探测周期均作为下次自然重连参数延迟生效。
        return before[0] != after[0] or before[2] != after[2]

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
            websocket_url=(
                None
                if getattr(arguments, "force_usb_cdc", False)
                else getattr(arguments, "websocket_url", None)
            ),
            websocket_client_name=getattr(arguments, "websocket_client_name", None),
            websocket_client_id=getattr(arguments, "websocket_client_id", None),
        )
        self.client.event_callback = self._handle_device_event
        self.stopping = threading.Event()
        self.runtime_reconnect_requested = threading.Event()
        self.active_probe_requested = threading.Event()
        # 应用启动后执行且仅执行一次完整主动探测：USB 优先，失败后再检查
        # 已保存的 WebSocket 地址及局域网候选。成功连接后该事件由主循环清除。
        self.active_probe_requested.set()
        self.reboot_requested = threading.Event()
        self.sdk_bootloader_requested = threading.Event()
        self.custom_style_catalog_requested = threading.Event()
        self.custom_style_uploads = queue.Queue()
        self.custom_style_deletes = queue.Queue()
        self.screenshot_requested = threading.Event()
        self.initialize_wifi_commands()
        self.initialize_websocket_client_commands()
        self.available_styles = set(BUILTIN_LCD_STYLES)
        self.available_idle_styles = {"idle"}
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
        extra_collection_tasks = [
            ("qbittorrent", self._collect_qbittorrent_fragment, 1.0, "qBittorrent")
        ]
        self._collection_coordinator = CollectionCoordinator(
            self.collector,
            self._snapshot_store,
            self._complete_collection_fragment,
            extra_collection_tasks,
            arguments.collection_task_intervals,
            arguments.collection_task_logs,
        )
        self.initialize_custom_data()

    def apply_runtime_config(self, payload):
        """校验并热更新托盘管理的完整运行配置。"""
        if not isinstance(payload, dict):
            raise ValueError("运行时配置必须是对象")
        numeric_fields = {
            "interval": float,
            "reconnect_interval": float,
            "serial_probe_interval": float,
            "lan_probe_port": int,
            "lan_probe_timeout": float,
            "lan_probe_max_workers": int,
            "qbittorrent_interval": float,
        }
        text_fields = (
            "port",
            "websocket_url",
            "websocket_client_name",
            "websocket_client_id",
            "ping_target",
            "lan_probe_path",
            "qbittorrent_address",
            "qbittorrent_username",
            "qbittorrent_password",
        )
        updated = {}
        for name, converter in numeric_fields.items():
            if name in payload:
                updated[name] = converter(payload[name])
        for name in text_fields:
            if name in payload:
                updated[name] = str(payload[name] or "").strip()
        if (
            updated.get("interval", self.arguments.interval) < 0.3
            or updated.get("reconnect_interval", self.arguments.reconnect_interval) <= 0
            or updated.get("serial_probe_interval", self.arguments.serial_probe_interval) <= 0
            or updated.get("lan_probe_timeout", self.arguments.lan_probe_timeout) <= 0
            or updated.get("qbittorrent_interval", self.arguments.qbittorrent_interval) <= 0
        ):
            raise ValueError("运行时配置中的时间间隔无效")
        lan_port = updated.get("lan_probe_port", self.arguments.lan_probe_port)
        lan_workers = updated.get(
            "lan_probe_max_workers", self.arguments.lan_probe_max_workers
        )
        if not 1 <= lan_port <= 65535 or lan_workers <= 0:
            raise ValueError("局域网探测端口或并发数无效")
        task_intervals = payload.get(
            "collection_task_intervals",
            self.arguments.collection_task_intervals,
        )
        if (
            not isinstance(task_intervals, dict)
            or any(float(interval) <= 0 for interval in task_intervals.values())
        ):
            raise ValueError("采集任务频率必须是大于零的对象")

        connection_before = self._runtime_connection_signature(self.arguments)
        for name, value in updated.items():
            setattr(self.arguments, name, value)
        self.arguments.adaptive_transmit = bool(
            payload.get("adaptive_transmit", self.arguments.adaptive_transmit)
        )
        self.arguments.collection_task_logs = bool(
            payload.get(
                "collection_task_logs", self.arguments.collection_task_logs
            )
        )
        self.arguments.force_usb_cdc = bool(
            payload.get(
                "force_usb_cdc",
                getattr(self.arguments, "force_usb_cdc", False),
            )
        )
        self.arguments.collection_task_intervals = {
            str(name): float(interval)
            for name, interval in task_intervals.items()
        }
        self.arguments.custom_data_configs = normalize_plugin_configs(
            payload.get("custom_data_configs", getattr(self.arguments, "custom_data_configs", {}))
        )
        self.arguments.custom_data_enabled = normalize_plugin_enabled(
            payload.get("custom_data_enabled", getattr(self.arguments, "custom_data_enabled", {}))
        )
        self.collector.ping_monitor.target = self.arguments.ping_target
        self._collection_coordinator.update_runtime_settings(
            self.arguments.collection_task_intervals,
            self.arguments.collection_task_logs,
        )
        self.update_custom_data_runtime_settings()
        self._apply_runtime_qbittorrent(payload)
        self.apply_display_config(payload)
        self.apply_dev_config(
            {"enabled": bool(payload.get("dev", self.arguments.dev))}
        )
        self._reset_adaptive_transmit_negotiation()

        self.client.configured_port = self.arguments.port or None
        self.client.websocket_url = (
            None
            if self.arguments.force_usb_cdc
            else self.arguments.websocket_url or None
        )
        self.client.websocket_client_name = self.arguments.websocket_client_name
        self.client.websocket_client_id = self.arguments.websocket_client_id
        self.client.probe_interval = self.arguments.serial_probe_interval
        connection_after = self._runtime_connection_signature(self.arguments)
        if self._runtime_connection_requires_reconnect(
            connection_before,
            connection_after,
            self.client.is_connected,
        ):
            self.runtime_reconnect_requested.set()
        elif connection_after != connection_before and self.client.is_connected:
            LOGGER.info(
                "连接参数已热更新并保留当前会话，新参数将在下次自然重连时生效"
            )
        LOGGER.info("完整运行配置已热更新，不重启 Monitor 工作进程")

    def _handle_device_event(self, payload):
        """处理设备主动事件，并按白名单同步配置变化。"""
        try:
            message = bytes(payload).decode("utf-8", "replace").strip()
        except (TypeError, ValueError):
            return
        prefix = "configChange:"
        if not message.startswith(prefix):
            return
        try:
            change = json.loads(message[len(prefix):])
        except (TypeError, ValueError, json.JSONDecodeError):
            LOGGER.warning("设备上报了无效 configChange：%s", message)
            return
        if not isinstance(change, dict):
            return
        key = str(change.get("key") or "").strip()
        value = change.get("value")
        validators = {
            "lcd_style": lambda item: isinstance(item, str)
            and item in self.available_styles,
            "lcd_brightness": lambda item: isinstance(item, int)
            and not isinstance(item, bool)
            and 1 <= item <= 100,
            "screen_rotation": lambda item: item in (0, 180)
            and not isinstance(item, bool),
            "network_unit": lambda item: item in ("MB", "Mbps"),
        }
        validator = validators.get(key)
        if validator is None or not validator(value):
            LOGGER.warning("设备上报了不允许的配置变化：%s=%r", key, value)
            return
        setattr(self.arguments, key, value)
        LOGGER.info("设备按键修改配置，Monitor 已实时同步：%s=%s", key, value)
        print(
            "CONFIG_CHANGE_RESULT:"
            + json.dumps(
                {"status": "ok", "key": key, "value": value},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            flush=True,
        )

    def _apply_runtime_qbittorrent(self, payload):
        """根据最新配置启动、停止或替换 qBittorrent 采集器。"""
        enabled = bool(
            payload.get(
                "qbittorrent_enabled", self.arguments.qbittorrent_enabled
            )
        )
        address = str(
            payload.get(
                "qbittorrent_address", self.arguments.qbittorrent_address
            )
            or ""
        ).strip().rstrip("/")
        username = str(
            payload.get(
                "qbittorrent_username", self.arguments.qbittorrent_username
            )
            or ""
        )
        password = str(
            payload.get(
                "qbittorrent_password", self.arguments.qbittorrent_password
            )
            or ""
        )
        interval = float(
            payload.get(
                "qbittorrent_interval", self.arguments.qbittorrent_interval
            )
        )
        desired = (enabled, address, username, password, interval)
        current_monitor = self.qbittorrent_monitor
        current = (
            current_monitor is not None,
            current_monitor.client.address if current_monitor is not None else "",
            current_monitor.client.username if current_monitor is not None else "",
            current_monitor.client.password if current_monitor is not None else "",
            current_monitor.interval if current_monitor is not None else interval,
        )
        self.arguments.qbittorrent_enabled = enabled
        self.arguments.qbittorrent_address = address
        self.arguments.qbittorrent_username = username
        self.arguments.qbittorrent_password = password
        self.arguments.qbittorrent_interval = interval
        if desired == current:
            return
        previous = current_monitor
        if previous is not None:
            previous.close()
        self.qbittorrent_monitor = None
        if enabled:
            monitor = QbittorrentMonitor(
                address, username, password, interval
            )
            monitor.start()
            self.qbittorrent_monitor = monitor

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
                "idle_style": getattr(arguments, "idle_style", "idle"),
                "idle_timeout": getattr(arguments, "idle_timeout", 30),
                "dev": bool(getattr(arguments, "dev", False)),
            },
        }


    def close(self):
        """释放采集器持有的原生资源及其启动的外部子进程。"""
        self._stop_thread_diagnostics()
        coordinator = getattr(self, "_collection_coordinator", None)
        if coordinator is not None:
            coordinator.close(wait=True)
        self.close_custom_data()
        qbittorrent_monitor = getattr(self, "qbittorrent_monitor", None)
        if qbittorrent_monitor is not None:
            qbittorrent_monitor.close()
        self._stop_transmit_worker(wait=True)
        self.collector.close()

    def _force_usb_cdc_enabled(self):
        """返回是否启用仅使用 USB-CDC 的连接策略。"""
        arguments = getattr(self, "arguments", None)
        return bool(getattr(arguments, "force_usb_cdc", False))

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
        if self._force_usb_cdc_enabled():
            return False
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

    def request_active_probe(self):
        """请求主循环立即探测设备，已有连接时保持当前传输不变。"""
        if self.client.is_connected:
            LOGGER.info("主动探测复用当前连接，不关闭已握手成功的传输")
            return
        LOGGER.info("收到主动探测请求，正在唤醒主循环立即搜索设备")
        self.active_probe_requested.set()
        self.runtime_reconnect_requested.set()

    def _connect_for_active_probe(self):
        """优先连接 USB，失败后扫描局域网，并保留成功建立的连接。"""
        original_url = self.client.websocket_url
        self.client.close()
        self.client.websocket_url = None
        try:
            self.client.connect()
            LOGGER.info("主动探测已连接 USB CDC，连接将由常驻监控继续使用")
            return
        except (OSError, RuntimeError, serial.SerialException) as usb_error:
            self.client.close()
            if self._force_usb_cdc_enabled():
                raise RuntimeError("主动探测未发现 USB CDC 设备：{}".format(usb_error))
        self.client.websocket_url = original_url
        if (
            isinstance(original_url, str)
            and original_url
            and self._probe_and_reconnect_saved_websocket(original_url)
        ):
            LOGGER.info("主动探测已连接保存的 WebSocket，连接将由常驻监控继续使用")
            return
        if self._rediscover_websocket_device():
            LOGGER.info("主动探测已连接 WebSocket，连接将由常驻监控继续使用")
            return
        raise RuntimeError("主动探测未发现 USB CDC 或局域网 WebSocket 设备")

    def _maybe_discover_linux_websocket(self, now=None):
        """Linux 未连接时按三十秒节流执行一次低影响局域网设备发现。"""
        if (
            self._force_usb_cdc_enabled()
            or platform.system() != "Linux"
            or self.client.is_connected
        ):
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
        if self._force_usb_cdc_enabled():
            return False
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
            if self._force_usb_cdc_enabled():
                return False
            if self.runtime_reconnect_requested.is_set():
                return False
            now = time.monotonic()
            wait_seconds = max(0.0, min(next_direct_probe, next_network_scan) - now)
            if self._wait_for_runtime_interrupt(wait_seconds):
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

    def _wait_for_runtime_interrupt(self, timeout):
        """等待停止或连接配置热更新信号，并避免长间隔阻塞配置生效。"""
        deadline = time.monotonic() + max(0.0, float(timeout))
        while not self.stopping.is_set():
            if self.runtime_reconnect_requested.is_set():
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self.stopping.wait(min(remaining, 0.1))
        return True

    def _wait_for_usb_addition(self, previous_ports):
        """等待串口拔出后重新插入，期间不打开端口或发送探测命令。"""
        baseline = frozenset(previous_ports)
        while not self.stopping.is_set():
            if self.runtime_reconnect_requested.is_set():
                return False
            current_ports = self.client.available_ports()
            if current_ports - baseline:
                return True
            # 拔出只更新基线；设备使用相同 COM 号重新枚举时，相对空基线仍是新增。
            baseline = current_ports
            self.stopping.wait(0.5)
        return False

    def _apply_pending_runtime_reconnect(self):
        """由监控主线程关闭旧连接，使串口与 WebSocket 配置安全切换。"""
        if not self.runtime_reconnect_requested.is_set():
            return
        active_probe_requested = getattr(self, "active_probe_requested", None)
        if (
            active_probe_requested is not None
            and active_probe_requested.is_set()
            and self.client.is_connected
        ):
            # 主动探测请求可能恰好到达正在进行的握手阶段；若握手随后成功，
            # 直接采用该连接，不能再按普通配置热更新流程把它关闭。
            active_probe_requested.clear()
            self.runtime_reconnect_requested.clear()
            LOGGER.info("主动探测期间握手已成功，保留当前连接")
            return
        self.runtime_reconnect_requested.clear()
        self._stop_transmit_worker(wait=True)
        self.client.close()
        LOGGER.info("连接参数已热更新，正在使用新配置重新连接设备")

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
            self._apply_pending_runtime_reconnect()
            probing = not self.client.is_connected
            ports_before_probe = self.client.available_ports()
            try:
                if not self.client.is_connected:
                    LOGGER.info("正在搜索 Pico LCD 设备")
                    active_probe_requested = getattr(
                        self, "active_probe_requested", None
                    )
                    if (
                        active_probe_requested is not None
                        and active_probe_requested.is_set()
                    ):
                        active_probe_requested.clear()
                        self._connect_for_active_probe()
                    else:
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
                    and not self._force_usb_cdc_enabled()
                    and isinstance(websocket_url, str)
                    and websocket_url
                    and self._recover_windows_websocket(websocket_url)
                ):
                    continue
                if isinstance(websocket_url, str) and websocket_url:
                    self._wait_for_runtime_interrupt(
                        self.arguments.reconnect_interval
                    )
                    continue
                # USB CDC 只在端口拔出并重新枚举后再次握手，避免断线期间
                # 每隔数秒打开系统全部 COM 口并重复发送 PING。
                if not probing:
                    LOGGER.info(
                        "串口连接已断开，正在等待 USB CDC 端口重新枚举",
                    )
                if not self._wait_for_usb_addition(ports_before_probe):
                    continue
                LOGGER.info(
                    "检测到 USB CDC 端口新增，%.1f 秒后探测 Pico LCD",
                    self.arguments.reconnect_interval,
                )
                self._wait_for_runtime_interrupt(
                    self.arguments.reconnect_interval
                )
                continue
        # 设备控制命令必须独占协议流，先等待发送线程完全退出再发送最终命令。
        self._stop_transmit_worker(wait=True)
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
        sdk_bootloader_requested = getattr(self, "sdk_bootloader_requested", None)
        sdk_bootloader_result = None
        if (
            sdk_bootloader_requested is not None
            and sdk_bootloader_requested.is_set()
            and self.client.is_connected
        ):
            try:
                data = self.client.enter_sdk_bootloader()
                sdk_bootloader_result = {
                    "status": "ok",
                    "message": "设备已确认 ROM USB 下载模式切换请求",
                    "data": data,
                }
            except (OSError, RuntimeError, serial.SerialException) as error:
                LOGGER.warning("设备进入 ROM USB 下载模式失败：%s", error)
                sdk_bootloader_result = {"status": "error", "message": str(error)}
        elif sdk_bootloader_requested is not None and sdk_bootloader_requested.is_set():
            sdk_bootloader_result = {"status": "error", "message": "当前没有已连接的 USB 设备"}
        self._stop_thread_diagnostics()
        self.client.close()
        if reboot_result is not None:
            print(
                "DEVICE_REBOOT_RESULT:" + json.dumps(reboot_result, ensure_ascii=False),
                flush=True,
            )
        if sdk_bootloader_result is not None:
            print(
                "SDK_BOOTLOADER_RESULT:"
                + json.dumps(sdk_bootloader_result, ensure_ascii=False),
                flush=True,
            )
        LOGGER.info("监控服务已停止")
        return 0
