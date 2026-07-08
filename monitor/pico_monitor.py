#!/usr/bin/env python3
"""Pico LCD 跨平台系统硬件监控程序入口。"""


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

import argparse
import io
import json
import logging
import os
import platform
import queue
import signal
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import psutil
import serial

from pico_client import PicoJsonClient, PicoRestartingError
from pico_upgrade import PicoFirmwareUpgrader, PicoUpgradeDownloader, PicoUpgradePackage
from build_info import GITHUB_REPOSITORY, MONITOR_VERSION
from custom_data import get_manager as get_custom_data_manager
from monitor_update import LinuxDebUpdater
from qbittorrent_monitor import QbittorrentMonitor
from system_monitor import SystemInformationCollector


LOGGER = logging.getLogger("pico-monitor")
BUILTIN_LCD_STYLES = (
    "default", "disk", "diskv2", "diskv3", "diskv4", "horizontal_disk",
    "horizontal_diskv2",
    "horizontal_disk4x",
    "horizontal_disk4x_qb", "horizontal_disk6x", "simple", "fpstest",
    "fps_simple", "game",
)


def _ensure_utf8_text_stream(stream):
    """确保日志输出流使用 UTF-8 编码，避免 Windows 打包后中文日志乱码。"""
    if stream is None:
        return None
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
        return stream
    except (AttributeError, OSError, ValueError):
        buffer = getattr(stream, "buffer", None)
        if buffer is None:
            return stream
        return io.TextIOWrapper(
            buffer,
            encoding="utf-8",
            errors="replace",
            line_buffering=True,
            write_through=True,
        )


def _open_inherited_text_stream(file_descriptor):
    """在 Windows 无控制台 EXE 中重新打开继承的标准管道。"""
    try:
        return os.fdopen(
            os.dup(file_descriptor),
            "w",
            encoding="utf-8",
            errors="replace",
            buffering=1,
        )
    except OSError:
        return None


def _configure_standard_streams():
    """统一修正标准输出和错误输出的编码，并返回日志应写入的文本流。"""
    stdout = _ensure_utf8_text_stream(getattr(sys, "stdout", None))
    stderr = _ensure_utf8_text_stream(getattr(sys, "stderr", None))
    if stdout is None:
        stdout = _open_inherited_text_stream(1)
        sys.stdout = stdout
    if stderr is None:
        stderr = _open_inherited_text_stream(2)
        sys.stderr = stderr
    return stderr or stdout or open(os.devnull, "w", encoding="utf-8")


def _write_version_to_console(version_text):
    """向当前命令行输出版本，并兼容 Windows 无控制台打包程序。"""
    output = getattr(sys, "stdout", None)
    if output is None and sys.platform == "win32" and getattr(sys, "frozen", False):
        try:
            import ctypes

            ctypes.windll.kernel32.AttachConsole(-1)
            output = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        except (OSError, AttributeError):
            output = None
    if output is not None:
        output.write(version_text + "\n")
        output.flush()


class MonitorVersionAction(argparse.Action):
    """输出 Monitor 构建版本后立即结束命令行程序。"""

    def __call__(self, parser, namespace, values, option_string=None):
        """打印统一构建版本，并以成功状态退出参数解析。"""
        del namespace, values, option_string
        _write_version_to_console("pico-monitor {}".format(MONITOR_VERSION))
        parser.exit()


def environment_flag(name, default=False):
    """读取常见布尔环境变量值，无法识别时使用默认值。"""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def create_argument_parser():
    """创建监控程序统一命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="Pico LCD 系统硬件监控程序")
    parser.add_argument(
        "--version",
        action=MonitorVersionAction,
        nargs=0,
        help="显示 Monitor 版本号并退出",
    )
    parser.add_argument("--port", default=os.getenv("PICO_MONITOR_PORT") or None, help="固定串口名称，留空时自动发现")
    parser.add_argument("--ping-target", default=os.getenv("PICO_MONITOR_PING_TARGET", "www.baidu.com"), help="网络延迟检测目标")
    parser.add_argument("--interval", type=float, default=float(os.getenv("PICO_MONITOR_INTERVAL", "0.5")), help="采集和发送间隔，单位为秒")
    parser.add_argument("--reconnect-interval", type=float, default=float(os.getenv("PICO_MONITOR_RECONNECT_INTERVAL", "3.0")), help="设备断线后的重连间隔，单位为秒")
    parser.add_argument("--serial-probe-interval", type=float, default=float(os.getenv("PICO_MONITOR_SERIAL_PROBE_INTERVAL", "3.0")), help="串口探测 PING 的发送间隔，单位为秒")
    parser.add_argument("--screen-rotation", type=int, choices=(0, 180), default=int(os.getenv("PICO_MONITOR_SCREEN_ROTATION", "0")), help="Pico 屏幕旋转角度，可选 0 或 180")
    parser.add_argument("--lcd-brightness", type=int, choices=range(1, 101), default=int(os.getenv("PICO_MONITOR_LCD_BRIGHTNESS", "50")), help="Pico LCD 背光亮度百分比，范围为 1 至 100")
    parser.add_argument("--network-unit", choices=("MB", "Mbps"), default=os.getenv("PICO_MONITOR_NETWORK_UNIT", "MB"), help="网络速率模式：MB 自动使用 B/KB/MB/GB，Mbps 自动使用 bps/Kbps/Mbps/Gbps")
    parser.add_argument("--lcd-style", default=os.getenv("PICO_MONITOR_LCD_STYLE", "fps_simple"), help="Pico LCD 界面样式名称")
    qbittorrent_group = parser.add_mutually_exclusive_group()
    qbittorrent_group.add_argument("--qbittorrent-enabled", dest="qbittorrent_enabled", action="store_true", help="开启 qBittorrent 指标采集")
    qbittorrent_group.add_argument("--no-qbittorrent", dest="qbittorrent_enabled", action="store_false", help="关闭 qBittorrent 指标采集")
    parser.set_defaults(qbittorrent_enabled=environment_flag("PICO_MONITOR_QBITTORRENT_ENABLED"))
    parser.add_argument("--qbittorrent-address", default=os.getenv("PICO_MONITOR_QBITTORRENT_ADDRESS") or None, help="qBittorrent Web UI 地址")
    parser.add_argument("--qbittorrent-username", default=os.getenv("PICO_MONITOR_QBITTORRENT_USERNAME") or None, help="qBittorrent Web UI 账号")
    parser.add_argument("--qbittorrent-password", default=os.getenv("PICO_MONITOR_QBITTORRENT_PASSWORD") or None, help="qBittorrent Web UI 密码")
    parser.add_argument("--qbittorrent-interval", type=float, default=float(os.getenv("PICO_MONITOR_QBITTORRENT_INTERVAL", "2.0")), help="qBittorrent 指标采集间隔，单位为秒")
    parser.add_argument("--dev", action="store_true", default=environment_flag("PICO_MONITOR_DEV",True), help="开发模式：未发现 Pico 时仍打印待发送的 JSON 协议行")
    parser.add_argument("--disk-health-test-index", type=int, default=int(os.getenv("PICO_MONITOR_DISK_HEALTH_TEST_INDEX", "0")), help="磁盘健康显示测试：指定从 1 开始的磁盘序号，0 表示关闭")
    parser.add_argument("--disk-health-test-level", type=int, choices=range(6), default=int(os.getenv("PICO_MONITOR_DISK_HEALTH_TEST_LEVEL", "3")), help="磁盘健康显示测试等级，范围为 0 至 5，默认 3")
    parser.add_argument("--once", action="store_true", help="仅成功发送一次数据")
    parser.add_argument("--pico-info", action="store_true", help="连接 Pico，显示开发板型号、屏幕方案和固件版本后退出")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--upgrade-pico", action="store_true", help="下载当前 Monitor 版本的 Pico 升级包并执行升级")
    parser.add_argument("--upgrade-url", default=os.getenv("PICO_MONITOR_UPGRADE_URL") or None, help="覆盖 Pico 升级包下载地址")
    parser.add_argument("--upgrade-sha256", default=os.getenv("PICO_MONITOR_UPGRADE_SHA256") or None, help="可选的升级包 SHA-256 摘要")
    parser.add_argument("--update", action="store_true", help="从 GitHub 最新 Release 下载并安装当前架构的 Linux DEB")
    return parser


class MonitorService:
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
        self._latest_collected_snapshot = self._create_initial_snapshot(arguments)
        self._latest_collection_error = None
        self._collection_thread = None

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

    def _synchronize_style_catalog(self):
        """接收 Pico 样式清单并更新 monitor 的 JSON 配置文件。"""
        catalog = getattr(self.client, "styles", None) or []
        if not catalog:
            return
        names = set(BUILTIN_LCD_STYLES)
        names.update({
            item.get("name") for item in catalog
            if isinstance(item, dict) and item.get("name")
        })
        if not names:
            return
        self.available_styles = names
        settings_path = os.getenv("PICO_MONITOR_SETTINGS_PATH")
        if settings_path:
            from win.settings import TraySettingsStore, normalize_style_catalog

            normalized = normalize_style_catalog(catalog)
            if normalized:
                store = TraySettingsStore(settings_path)
                settings = store.load()
                settings["styles"] = normalized
                if settings["lcd_style"] not in names:
                    settings["lcd_style"] = normalized[0]["name"]
                    self.arguments.lcd_style = settings["lcd_style"]
                store.save(settings)
        LOGGER.info("STYLE_CATALOG_UPDATED：已同步 %d 个 Pico 样式", len(names))

    def request_reboot_and_stop(self):
        """让主循环退出，并在释放串口前请求 Pico 重启。"""
        LOGGER.info("收到托盘退出请求，将在停止监控前重启 Pico")
        self.reboot_requested.set()
        self.stopping.set()

    def request_custom_style_catalog(self):
        """安排主循环在当前串口交互结束后查询自定义样式。"""
        self.custom_style_catalog_requested.set()

    def request_screenshot(self):
        """安排主循环在当前串口交互完成后截取 LCD 画面。"""
        self.screenshot_requested.set()

    def _publish_screenshot(self):
        """接收 Pico 截图、转换为 PNG，并把保存结果输出给托盘。"""
        self.screenshot_requested.clear()
        try:
            from PIL import Image

            metadata, pixels = self.client.screenshot()
            width = int(metadata["width"])
            height = int(metadata["height"])
            # Pillow 的 BGR;16 解码器读取小端 RGB565，Pico 回传的是 LCD 使用的
            # 大端字节序，因此先按像素交换高低字节再生成 PNG。
            little_endian_pixels = bytearray(len(pixels))
            little_endian_pixels[0::2] = pixels[1::2]
            little_endian_pixels[1::2] = pixels[0::2]
            image = Image.frombytes(
                "RGB", (width, height), bytes(little_endian_pixels), "raw", "BGR;16"
            )
            screenshot_directory = Path(
                os.getenv("PICO_MONITOR_SCREENSHOT_DIR", Path.cwd() / "screenshot")
            )
            screenshot_directory.mkdir(parents=True, exist_ok=True)
            path = screenshot_directory / datetime.now().strftime(
                "screenshot_%Y%m%d_%H%M%S_%f.png"
            )
            image.save(path, "PNG")
            result = {"status": "ok", "path": str(path.resolve())}
        except (KeyError, OSError, RuntimeError, ValueError, serial.SerialException) as error:
            result = {"status": "error", "message": str(error)}
        print(
            "SCREENSHOT_RESULT:"
            + json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            flush=True,
        )

    def _publish_custom_style_catalog(self):
        """通过 Pico 指令查询自定义样式并输出给托盘进程。"""
        self.custom_style_catalog_requested.clear()
        try:
            catalog = self.client.request_style_catalog_info()
            result = {
                "status": "ok",
                "styles": catalog["styles"],
                "flash": catalog["flash"],
            }
        except (OSError, RuntimeError, serial.SerialException) as error:
            result = {"status": "error", "message": str(error), "styles": []}
        print(
            "CUSTOM_STYLE_LIST_RESULT:"
            + json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            flush=True,
        )

    def request_custom_style_upload(self, payload):
        """安排主循环在串口空闲时上传一个已校验的自定义样式。"""
        self.custom_style_uploads.put(dict(payload))

    def _publish_custom_style_upload(self):
        """执行待处理的自定义样式上传并向托盘输出结构化结果。"""
        payload = self.custom_style_uploads.get_nowait()
        try:
            import base64

            content = base64.b64decode(payload["content"], validate=True)
            data = self.client.upload_style(
                payload["filename"],
                payload["style_name"],
                content,
                overwrite=payload.get("overwrite") is True,
            )
            result = {"status": "ok", "data": data}
            self.client.styles = self.client.request_style_catalog()
            self._synchronize_style_catalog()
        except (KeyError, ValueError, OSError, RuntimeError, serial.SerialException) as error:
            result = {"status": "error", "message": str(error)}
        print(
            "CUSTOM_STYLE_UPLOAD_RESULT:"
            + json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            flush=True,
        )

    def request_custom_style_delete(self, payload):
        """安排主循环删除指定自定义样式。"""
        self.custom_style_deletes.put(dict(payload))

    def _publish_custom_style_delete(self):
        """删除 Pico 自定义样式并向托盘发布重启状态。"""
        payload = self.custom_style_deletes.get_nowait()
        try:
            data = self.client.delete_style(
                payload["filename"], payload["style_name"],
            )
            result = {"status": "ok", "data": data}
        except (KeyError, ValueError, OSError, RuntimeError, serial.SerialException) as error:
            result = {"status": "error", "message": str(error)}
        print(
            "CUSTOM_STYLE_DELETE_RESULT:"
            + json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            flush=True,
        )
        if result["status"] == "ok":
            # Pico 已由删除命令复位，关闭旧串口以立即进入 PONG 重连流程。
            self.client.close()

    def apply_display_config(self, payload):
        """校验并热更新 Windows 托盘下发的显示配置。"""
        brightness = int(payload.get("lcd_brightness", self.arguments.lcd_brightness))
        rotation = int(payload.get("screen_rotation", self.arguments.screen_rotation))
        style = payload.get("lcd_style", self.arguments.lcd_style)
        network_unit = payload.get("network_unit", self.arguments.network_unit)
        if not 1 <= brightness <= 100:
            raise ValueError("LCD 背光亮度必须为 1 至 100")
        if rotation not in (0, 180):
            raise ValueError("屏幕旋转角度仅支持 0 或 180")
        if style not in self.available_styles:
            raise ValueError("不支持的 LCD 样式")
        if network_unit not in ("MB", "Mbps"):
            raise ValueError("不支持的网络速率单位")
        self.arguments.lcd_brightness = brightness
        self.arguments.screen_rotation = rotation
        self.arguments.lcd_style = style
        self.arguments.network_unit = network_unit
        LOGGER.info(
            "显示设置已热更新：亮度=%d%%，旋转=%d°，样式=%s，网络单位=%s",
            brightness, rotation, style, network_unit,
        )

    def apply_dev_config(self, payload):
        """热更新开发模式开关，不重启 Monitor 工作进程。"""
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError("开发模式开关必须为布尔值")
        self.arguments.dev = enabled
        LOGGER.info("开发模式已热更新：%s", "开启" if enabled else "关闭")

    def stop(self, signum=None, frame=None):
        """请求主循环停止，由通信线程在退出阶段统一关闭串口。"""
        del signum, frame
        LOGGER.info("收到停止请求，正在关闭监控程序")
        # Windows 的 PySerial 正在 ReadFile 时不能由其他线程执行 close，
        # 否则内部 OVERLAPPED 事件会被置空并触发 ctypes.byref(None) 异常。
        self.stopping.set()

    def close(self):
        """释放采集器持有的原生资源及其启动的外部子进程。"""
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
        """按配置周期采集快照，并以原子替换方式发布最近一次成功结果。"""
        while not self.stopping.is_set():
            started = time.monotonic()
            try:
                snapshot = self._collect_snapshot()
                # CPython 的对象引用赋值具备原子性；完整构造后一次发布，发送线程无需加锁。
                self._latest_collected_snapshot = snapshot
                self._latest_collection_error = None
            except (OSError, RuntimeError, TypeError, ValueError, psutil.Error) as error:
                LOGGER.exception("后台系统指标采集失败，将继续发送最近一次成功快照：%s", error)
                self._latest_collection_error = error
            remaining = self.arguments.interval - (time.monotonic() - started)
            self.stopping.wait(max(0.0, remaining))

    def _snapshot_for_sending(self):
        """无锁返回采集线程原子发布的最近一次完整快照。"""
        return self._latest_collected_snapshot

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
        snapshot["ext"] = get_custom_data_manager().collect_due_data()
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


def configure_logging():
    """配置适合终端、systemd 和 Windows 托盘收集的日志格式。"""
    handler = logging.StreamHandler(_configure_standard_streams())
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def log_monitor_version():
    """在服务启动阶段记录当前 Monitor 构建版本。"""
    LOGGER.info("Pico Monitor 启动：版本=%s", MONITOR_VERSION)


def format_pico_information(information):
    """将 Pico 硬件配置与固件版本格式化为终端文本。"""
    return "\n".join((
        "Pico 开发板型号：{}".format(
            information.get("board_model") or "未知（旧版固件未提供）"
        ),
        "Pico 屏幕色彩方案：{}".format(
            information.get("screen_color_profile") or "未知（旧版固件未提供）"
        ),
        "Pico 固件版本：{}".format(
            information.get("firmware_version") or "未知（旧版固件未提供）"
        ),
        "Pico 屏幕分辨率：{}".format(
            "{} x {}".format(
                information.get("screen_width"), information.get("screen_height")
            )
            if information.get("screen_width") and information.get("screen_height")
            else "未知（旧版固件未提供）"
        ),
    ))


def show_pico_information(port=None):
    """连接指定或自动发现的 Pico，输出设备信息后安全断开。"""
    client = PicoJsonClient(port)
    try:
        client.connect()
        _write_version_to_console(
            format_pico_information(client.device_information())
        )
        return 0

    finally:
        client.close()


def validate_arguments(arguments):
    """校验通用间隔以及启用 qBittorrent 后的必填连接参数。"""
    exclusive_actions = sum(bool(value) for value in (
        arguments.pico_info, arguments.upgrade_pico, arguments.update,
    ))
    if exclusive_actions > 1:
        raise SystemExit("--pico-info、--upgrade-pico 和 --update 不能同时使用")
    if (arguments.interval <= 0 or arguments.reconnect_interval <= 0
            or arguments.serial_probe_interval <= 0
            or arguments.qbittorrent_interval <= 0):
        raise SystemExit("采集间隔和重连间隔必须大于 0")
    if arguments.pico_info:
        return
    if not arguments.qbittorrent_enabled:
        return
    required = (
        ("--qbittorrent-address", arguments.qbittorrent_address),
        ("--qbittorrent-username", arguments.qbittorrent_username),
        ("--qbittorrent-password", arguments.qbittorrent_password),
    )
    missing = [name for name, value in required if not str(value or "").strip()]
    if missing:
        raise SystemExit("开启 qBittorrent 采集后必须配置：" + "、".join(missing))


def main():
    """校验参数并按当前平台启动后台工作进程或 Windows 托盘。"""
    # 参数解析器会在 --help 场景直接输出中文，必须先于 parse_args 配置编码。
    _configure_standard_streams()
    arguments = create_argument_parser().parse_args()
    validate_arguments(arguments)
    if (
        sys.platform == "win32"
        and getattr(sys, "frozen", False)
        and not arguments.worker
        and not arguments.pico_info
        and not arguments.upgrade_pico
        and not arguments.update
    ):
        from windows_tray import WindowsTrayApplication

        return WindowsTrayApplication.start([*sys.argv[1:], "--worker"])
    configure_logging()
    log_monitor_version()
    if arguments.pico_info:
        return show_pico_information(arguments.port)
    if arguments.update:
        LinuxDebUpdater(GITHUB_REPOSITORY, MONITOR_VERSION).update()
        return 0
    service = MonitorService(arguments)
    if arguments.worker and getattr(sys, "stdin", None) is not None:
        def listen_for_tray_commands():
            """处理托盘命令，并在托盘管道关闭时停止后台监控服务。"""
            for line in sys.stdin:
                command = line.strip()
                if command == "EXIT_REBOOT":
                    service.request_reboot_and_stop()
                    return
                if command == "EXIT":
                    service.stop()
                    return
                if command.startswith("DEV_CONFIG:"):
                    try:
                        service.apply_dev_config(
                            json.loads(command[len("DEV_CONFIG:"):])
                        )
                    except (TypeError, ValueError, json.JSONDecodeError) as error:
                        LOGGER.warning("开发模式热更新失败：%s", error)
                    continue
                if command.startswith("DISPLAY_CONFIG:"):
                    try:
                        service.apply_display_config(
                            json.loads(command[len("DISPLAY_CONFIG:"):])
                        )
                    except (TypeError, ValueError, json.JSONDecodeError) as error:
                        LOGGER.warning("显示设置热更新失败：%s", error)
                elif command == "CUSTOM_STYLE_LIST":
                    service.request_custom_style_catalog()
                elif command == "SCREENSHOT":
                    service.request_screenshot()
                elif command.startswith("CUSTOM_STYLE_UPLOAD:"):
                    try:
                        service.request_custom_style_upload(
                            json.loads(command[len("CUSTOM_STYLE_UPLOAD:"):])
                        )
                    except (TypeError, ValueError, json.JSONDecodeError) as error:
                        LOGGER.warning("自定义样式上传请求无效：%s", error)
                elif command.startswith("CUSTOM_STYLE_DELETE:"):
                    try:
                        service.request_custom_style_delete(
                            json.loads(command[len("CUSTOM_STYLE_DELETE:"):])
                        )
                    except (TypeError, ValueError, json.JSONDecodeError) as error:
                        LOGGER.warning("自定义样式删除请求无效：%s", error)
            # 托盘崩溃或被强制结束后，Windows 会关闭其持有的管道写端；
            # 此处收到 EOF 后主动停止服务，避免遗留孤立的 monitor 进程。
            service.stop()

        threading.Thread(
            target=listen_for_tray_commands,
            name="tray-control",
            daemon=True,
        ).start()
    signal.signal(signal.SIGINT, service.stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, service.stop)
    try:
        return service.run()
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
