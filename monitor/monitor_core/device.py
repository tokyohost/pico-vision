"""Pico 设备信息查询工具。"""

from pico_client import PicoJsonClient
from .console import _write_version_to_console

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


