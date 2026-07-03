#!/usr/bin/env python3
"""Pico LCD 跨平台系统硬件监控程序入口。"""

import argparse
import logging
import os
import signal
import sys
import threading
import time

import psutil
import serial

from pico_client import PicoJsonClient
from pico_upgrade import PicoFirmwareUpgrader, PicoUpgradeDownloader, PicoUpgradePackage
from build_info import GITHUB_REPOSITORY, MONITOR_VERSION
from monitor_update import LinuxDebUpdater
from qbittorrent_monitor import QbittorrentMonitor
from system_monitor import SystemInformationCollector


LOGGER = logging.getLogger("pico-monitor")
BUILTIN_LCD_STYLES = (
    "default", "disk", "horizontal_disk", "horizontal_disk4x",
    "horizontal_disk4x_qb", "horizontal_disk6x",
)


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
    parser.add_argument("--interval", type=float, default=float(os.getenv("PICO_MONITOR_INTERVAL", "0.9")), help="采集和发送间隔，单位为秒")
    parser.add_argument("--reconnect-interval", type=float, default=float(os.getenv("PICO_MONITOR_RECONNECT_INTERVAL", "3.0")), help="设备断线后的重连间隔，单位为秒")
    parser.add_argument("--screen-rotation", type=int, choices=(0, 180), default=int(os.getenv("PICO_MONITOR_SCREEN_ROTATION", "0")), help="Pico 屏幕旋转角度，可选 0 或 180")
    parser.add_argument("--network-unit", choices=("MB", "Mbps"), default=os.getenv("PICO_MONITOR_NETWORK_UNIT", "MB"), help="网络速率模式：MB 自动使用 B/KB/MB/GB，Mbps 自动使用 bps/Kbps/Mbps/Gbps")
    parser.add_argument("--lcd-style", choices=BUILTIN_LCD_STYLES, default=os.getenv("PICO_MONITOR_LCD_STYLE", "horizontal_disk4x_qb"), help="Pico LCD 内置界面样式")
    qbittorrent_group = parser.add_mutually_exclusive_group()
    qbittorrent_group.add_argument("--qbittorrent-enabled", dest="qbittorrent_enabled", action="store_true", help="开启 qBittorrent 指标采集")
    qbittorrent_group.add_argument("--no-qbittorrent", dest="qbittorrent_enabled", action="store_false", help="关闭 qBittorrent 指标采集")
    parser.set_defaults(qbittorrent_enabled=environment_flag("PICO_MONITOR_QBITTORRENT_ENABLED"))
    parser.add_argument("--qbittorrent-address", default=os.getenv("PICO_MONITOR_QBITTORRENT_ADDRESS") or None, help="qBittorrent Web UI 地址")
    parser.add_argument("--qbittorrent-username", default=os.getenv("PICO_MONITOR_QBITTORRENT_USERNAME") or None, help="qBittorrent Web UI 账号")
    parser.add_argument("--qbittorrent-password", default=os.getenv("PICO_MONITOR_QBITTORRENT_PASSWORD") or None, help="qBittorrent Web UI 密码")
    parser.add_argument("--qbittorrent-interval", type=float, default=float(os.getenv("PICO_MONITOR_QBITTORRENT_INTERVAL", "2.0")), help="qBittorrent 指标采集间隔，单位为秒")
    parser.add_argument("--dev", action="store_true", default=environment_flag("PICO_MONITOR_DEV"), help="开发模式：未发现 Pico 时仍打印待发送的 JSON 协议行")
    parser.add_argument("--disk-health-test-index", type=int, default=int(os.getenv("PICO_MONITOR_DISK_HEALTH_TEST_INDEX", "0")), help="磁盘健康显示测试：指定从 1 开始的磁盘序号，0 表示关闭")
    parser.add_argument("--disk-health-test-level", type=int, choices=range(6), default=int(os.getenv("PICO_MONITOR_DISK_HEALTH_TEST_LEVEL", "3")), help="磁盘健康显示测试等级，范围为 0 至 5，默认 3")
    parser.add_argument("--once", action="store_true", help="仅成功发送一次数据")
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
        self.client = PicoJsonClient(arguments.port)
        self.stopping = threading.Event()

    def stop(self, signum=None, frame=None):
        """请求主循环停止，并安全关闭当前串口连接。"""
        del signum, frame
        LOGGER.info("收到停止请求，正在关闭监控程序")
        self.stopping.set()
        self.client.close()

    def run(self):
        """持续连接设备、采集指标并发送最新系统快照。"""
        LOGGER.info("监控服务启动：端口=%s，Ping=%s，发送间隔=%.1f 秒，重连间隔=%.1f 秒，屏幕旋转=%d°，网络单位=%s，LCD 样式=%s，开发模式=%s", self.arguments.port or "自动发现", self.arguments.ping_target, self.arguments.interval, self.arguments.reconnect_interval, self.arguments.screen_rotation, self.arguments.network_unit, self.arguments.lcd_style, "开启" if self.arguments.dev else "关闭")
        while not self.stopping.is_set():
            try:
                if not self.client.is_connected:
                    LOGGER.info("正在搜索 Pico LCD 设备")
                    try:
                        self.client.connect()
                    except (OSError, RuntimeError, serial.SerialException):
                        if self.arguments.dev:
                            self.client.close()
                            return self._run_development_loop()
                        raise
                    LOGGER.info("Pico LCD 已连接：%s", self.client.port_name)
                if self.arguments.upgrade_pico:
                    return self._upgrade_pico()
                started = time.monotonic()
                snapshot = self._collect_snapshot()
                collection_elapsed = time.monotonic() - started
                if collection_elapsed > 0.5:
                    LOGGER.warning(
                        "系统指标采集耗时较长：%.3f 秒",
                        collection_elapsed,
                    )
                self.client.send(snapshot)
                if self.arguments.once:
                    return 0
                remaining = self.arguments.interval - (time.monotonic() - started)
                self.stopping.wait(max(0.0, remaining))
            except (OSError, RuntimeError, serial.SerialException) as error:
                LOGGER.warning("监控通信异常：%s；%.1f 秒后重试", error, self.arguments.reconnect_interval)
                self.client.close()
                self.stopping.wait(self.arguments.reconnect_interval)
        LOGGER.info("监控服务已停止")
        return 0

    def _upgrade_pico(self):
        """下载当前 Monitor 版本升级包，完成串口升级后退出。"""
        url = self.arguments.upgrade_url
        if not url:
            if not GITHUB_REPOSITORY or MONITOR_VERSION == "development":
                raise RuntimeError("开发版本必须通过 --upgrade-url 指定 Pico 升级包")
            url = "https://github.com/{}/releases/download/v{}/pico-upgrade-v{}.zip".format(
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
        """未发现 Pico 时停止串口重试，并按采集周期持续打印 JSON。"""
        while not self.stopping.is_set():
            started = time.monotonic()
            self._print_development_snapshot()
            if self.arguments.once:
                return 0
            remaining = self.arguments.interval - (time.monotonic() - started)
            self.stopping.wait(max(0.0, remaining))
        return 0

    def _collect_snapshot(self):
        """采集系统指标并补充 Pico 显示配置。"""
        snapshot = self.collector.collect()
        if self.qbittorrent_monitor is not None:
            snapshot["qbittorrent"] = self.qbittorrent_monitor.snapshot()
        self._apply_disk_health_test(snapshot)
        snapshot["display"] = {
            "rotation": self.arguments.screen_rotation,
            "network_unit": self.arguments.network_unit,
            "style": self.arguments.lcd_style,
        }
        return snapshot

    def _apply_disk_health_test(self, snapshot):
        """按命令行指定的磁盘序号覆盖健康等级，用于验证 LCD 告警效果。"""
        disk_index = int(getattr(self.arguments, "disk_health_test_index", 0) or 0)
        if disk_index <= 0:
            return
        health = int(getattr(self.arguments, "disk_health_test_level", 3))
        physical_disks = snapshot.get("physical_disks") or snapshot.get("disks", ())
        if disk_index > len(physical_disks):
            LOGGER.warning("磁盘健康测试序号超出范围：index=%d，磁盘数量=%d", disk_index, len(physical_disks))
            return
        selected = physical_disks[disk_index - 1]
        selected["health"] = health
        selected_name = selected.get("name")
        for disk in snapshot.get("disks", ()):
            if disk is selected or (selected_name and disk.get("name") == selected_name):
                disk["health"] = health

    def _print_development_snapshot(self):
        """打印当前采集结果对应的完整 JSON 协议行。"""
        try:
            packet = PicoJsonClient.build_packet(self._collect_snapshot())
            LOGGER.info(
                "[DEV][Monitor -> Pico][JSON] %s",
                packet.decode("utf-8", errors="replace").rstrip(),
            )
        except (OSError, ValueError, psutil.Error) as error:
            LOGGER.warning("[DEV][JSON] 系统指标采集失败：%s", error)


def configure_logging():
    """配置适合终端、systemd 和 Windows 托盘收集的日志格式。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def log_monitor_version():
    """在服务启动阶段记录当前 Monitor 构建版本。"""
    LOGGER.info("Pico Monitor 启动：版本=%s", MONITOR_VERSION)


def validate_arguments(arguments):
    """校验通用间隔以及启用 qBittorrent 后的必填连接参数。"""
    if arguments.interval <= 0 or arguments.reconnect_interval <= 0 or arguments.qbittorrent_interval <= 0:
        raise SystemExit("采集间隔和重连间隔必须大于 0")
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
    arguments = create_argument_parser().parse_args()
    validate_arguments(arguments)
    if sys.platform == "win32" and getattr(sys, "frozen", False) and not arguments.worker:
        from windows_tray import WindowsTrayApplication

        return WindowsTrayApplication([*sys.argv[1:], "--worker"]).run()
    configure_logging()
    log_monitor_version()
    if arguments.update:
        LinuxDebUpdater(GITHUB_REPOSITORY, MONITOR_VERSION).update()
        return 0
    service = MonitorService(arguments)
    signal.signal(signal.SIGINT, service.stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, service.stop)
    return service.run()


if __name__ == "__main__":
    raise SystemExit(main())
