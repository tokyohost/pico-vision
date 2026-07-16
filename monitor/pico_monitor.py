#!/usr/bin/env python3
"""Pico LCD 跨平台系统硬件监控程序兼容入口。"""

# Copyright (c) 2026 xuehui_li
#
# Licensed under the Custom Non-Commercial Copyleft License.
# Commercial use is prohibited without prior written permission.

import argparse
import ctypes
import logging
import signal
import sys

from build_info import GITHUB_REPOSITORY, MONITOR_VERSION
from monitor_update import LinuxDebUpdater
from monitor_core import arguments as _arguments
from monitor_core.arguments import (
    parse_monitor_arguments,
    validate_arguments,
)
from monitor_core.config import (
    config_flag,
    config_value,
    environment_flag,
    load_monitor_config,
    parse_collection_task_intervals,
)
from monitor_core.console import (
    _configure_standard_streams,
    _write_version_to_console,
    configure_logging,
)
from monitor_core.device import format_pico_information
from monitor_core.service import BUILTIN_LCD_STYLES, MonitorService
from monitor_core.tray_commands import start_tray_command_listener
from pico_client import PicoJsonClient

LOGGER = logging.getLogger("pico-monitor")


class MonitorVersionAction(argparse.Action):
    """输出兼容入口当前构建版本后结束命令行程序。"""

    def __call__(self, parser, namespace, values, option_string=None):
        """打印构建版本，并以成功状态退出参数解析。"""
        del namespace, values, option_string
        _write_version_to_console("pico-monitor {}".format(MONITOR_VERSION))
        parser.exit()


def create_argument_parser(config=None):
    """创建保留旧版版本补丁行为的命令行参数解析器。"""
    original_action = _arguments.MonitorVersionAction
    _arguments.MonitorVersionAction = MonitorVersionAction
    try:
        return _arguments.create_argument_parser(config)
    finally:
        _arguments.MonitorVersionAction = original_action


def log_monitor_version():
    """记录兼容入口当前加载的 Monitor 构建版本。"""
    LOGGER.info("Pico Monitor 启动：版本=%s", MONITOR_VERSION)


def is_windows_administrator():
    """判断当前 Windows 进程是否拥有管理员权限。"""
    if sys.platform != "win32":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def show_admin_required_message():
    """提示用户必须以管理员权限启动 Windows Monitor。"""
    message = "OmniWatch Monitor 需要以管理员身份运行，请右键选择“以管理员身份运行”后再启动。"
    try:
        ctypes.windll.user32.MessageBoxW(None, message, "OmniWatch Monitor", 0x10)
    except OSError:
        print(message, file=sys.stderr)


def show_pico_information(port=None, websocket_url=None):
    """探测 USB 或 WebSocket 设备；未找到时返回失败状态而不抛出异常。"""
    client = (
        PicoJsonClient(port, websocket_url=websocket_url)
        if websocket_url
        else PicoJsonClient(port)
    )
    try:
        try:
            client.connect()
            _write_version_to_console(format_pico_information(client.device_information()))
            return 0
        except (OSError, RuntimeError) as error:
            _write_version_to_console("设备探测未发现有效目标：{}".format(error))
            return 1
    finally:
        client.close()


def main():
    """校验参数并按当前平台启动后台工作进程或 Windows 托盘。"""
    _configure_standard_streams()
    if len(sys.argv) > 1 and sys.argv[1] == "--sdk-flasher":
        from sdk_flash import run_sdk_flasher_cli

        return run_sdk_flasher_cli(sys.argv[2:])
    arguments = parse_monitor_arguments()
    validate_arguments(arguments)
    if sys.platform == "win32" and not is_windows_administrator():
        show_admin_required_message()
        return 1
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
    configure_logging("DEBUG" if arguments.dev else arguments.log_level)
    log_monitor_version()
    if arguments.pico_info:
        return show_pico_information(arguments.port, arguments.websocket_url)
    if arguments.update:
        LinuxDebUpdater(GITHUB_REPOSITORY, MONITOR_VERSION).update()
        return 0
    service = MonitorService(arguments)
    if arguments.worker and getattr(sys, "stdin", None) is not None:
        start_tray_command_listener(service, sys.stdin)
    signal.signal(signal.SIGINT, service.stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, service.stop)
    try:
        return service.run()
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
