"""Windows 托盘与监控工作进程之间的命令分发。"""

import json
import logging
import threading

LOGGER = logging.getLogger("pico-monitor")


def _dispatch_tray_command(service, command):
    """解析并执行一条托盘控制命令，返回是否应结束监听。"""
    if command == "EXIT_REBOOT":
        service.request_reboot_and_stop()
        return True
    if command == "EXIT":
        service.stop()
        return True
    if command.startswith("DEV_CONFIG:"):
        service.apply_dev_config(json.loads(command[len("DEV_CONFIG:"):]))
    elif command.startswith("DISPLAY_CONFIG:"):
        service.apply_display_config(json.loads(command[len("DISPLAY_CONFIG:"):]))
    elif command == "CUSTOM_STYLE_LIST":
        service.request_custom_style_catalog()
    elif command == "SCREENSHOT":
        service.request_screenshot()
    elif command.startswith("CUSTOM_STYLE_UPLOAD:"):
        service.request_custom_style_upload(
            json.loads(command[len("CUSTOM_STYLE_UPLOAD:"):])
        )
    elif command.startswith("CUSTOM_STYLE_DELETE:"):
        service.request_custom_style_delete(
            json.loads(command[len("CUSTOM_STYLE_DELETE:"):])
        )
    elif command.startswith("CUSTOM_DATA_ACTIVATE:"):
        service.activate_custom_data_plugin(
            json.loads(command[len("CUSTOM_DATA_ACTIVATE:"):]).get("name")
        )
    return False


def listen_for_tray_commands(service, input_stream):
    """持续处理托盘命令，并在输入管道关闭时停止监控服务。"""
    for line in input_stream:
        command = line.strip()
        try:
            if _dispatch_tray_command(service, command):
                return
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            LOGGER.warning("托盘控制命令无效：%s", error)
    service.stop()


def start_tray_command_listener(service, input_stream):
    """创建并启动托盘控制命令后台监听线程。"""
    thread = threading.Thread(
        target=listen_for_tray_commands,
        args=(service, input_stream),
        name="tray-control",
        daemon=True,
    )
    thread.start()
    return thread
