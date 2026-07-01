#!/usr/bin/env python3
"""Pico LCD 跨平台系统硬件监控程序入口。"""

import argparse
import logging
import os
import signal
import sys
import threading
import time

import serial

from pico_client import PicoJsonClient
from system_monitor import SystemInformationCollector


LOGGER = logging.getLogger("pico-monitor")


def create_argument_parser():
    """创建监控程序统一命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="Pico LCD 系统硬件监控程序")
    parser.add_argument("--port", default=os.getenv("PICO_MONITOR_PORT") or None, help="固定串口名称，留空时自动发现")
    parser.add_argument("--ping-target", default=os.getenv("PICO_MONITOR_PING_TARGET", "www.baidu.com"), help="网络延迟检测目标")
    parser.add_argument("--interval", type=float, default=float(os.getenv("PICO_MONITOR_INTERVAL", "1.0")), help="采集和发送间隔，单位为秒")
    parser.add_argument("--reconnect-interval", type=float, default=float(os.getenv("PICO_MONITOR_RECONNECT_INTERVAL", "3.0")), help="设备断线后的重连间隔，单位为秒")
    parser.add_argument("--once", action="store_true", help="仅成功发送一次数据")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    return parser


class MonitorService:
    """管理系统指标采集、Pico 连接以及异常重连。"""

    def __init__(self, arguments):
        """根据命令行配置创建采集器、串口客户端和停止事件。"""
        self.arguments = arguments
        self.collector = SystemInformationCollector(arguments.ping_target)
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
        LOGGER.info("监控服务启动：端口=%s，发送间隔=%.1f 秒，重连间隔=%.1f 秒", self.arguments.port or "自动发现", self.arguments.interval, self.arguments.reconnect_interval)
        while not self.stopping.is_set():
            try:
                if not self.client.is_connected:
                    LOGGER.info("正在搜索 Pico LCD 设备")
                    self.client.connect()
                    LOGGER.info("Pico LCD 已连接：%s", self.client.port_name)
                started = time.monotonic()
                self.client.send(self.collector.collect())
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


def configure_logging():
    """配置适合终端、systemd 和 Windows 托盘收集的日志格式。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main():
    """校验参数并按当前平台启动后台工作进程或 Windows 托盘。"""
    arguments = create_argument_parser().parse_args()
    if arguments.interval <= 0 or arguments.reconnect_interval <= 0:
        raise SystemExit("--interval 和 --reconnect-interval 必须大于 0")
    if sys.platform == "win32" and getattr(sys, "frozen", False) and not arguments.worker:
        from windows_tray import WindowsTrayApplication

        return WindowsTrayApplication([*sys.argv[1:], "--worker"]).run()
    configure_logging()
    service = MonitorService(arguments)
    signal.signal(signal.SIGINT, service.stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, service.stop)
    return service.run()


if __name__ == "__main__":
    raise SystemExit(main())
