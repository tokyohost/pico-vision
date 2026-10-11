"""兼容 macOS USB 拔插期间的串口枚举，保留 Windows 与 Linux 原生行为。"""

import glob
import logging
import os
import platform
import stat

from serial.tools import list_ports, list_ports_common


LOGGER = logging.getLogger("pico-monitor.serial")


def enumerate_serial_ports():
    """优先使用完整原生描述；Mac 元数据缺失时仅枚举真实字符设备节点。"""
    try:
        return list(list_ports.comports())
    except (TypeError, OSError) as error:
        if platform.system() != "Darwin":
            raise
        # pyserial 在 USB 拔插中可能取得缺失的 locationID 并在位移运算时
        # 抛出 TypeError；不能因此退出 worker 或阻止其他已插入设备被发现。
        LOGGER.debug("macOS USB 枚举元数据暂不可用，改用真实串口节点：%s", error)
    ports = []
    for device in sorted(set(glob.glob("/dev/cu.*"))):
        try:
            if not stat.S_ISCHR(os.stat(device).st_mode):
                continue
        except OSError:
            # 列目录与检查节点之间仍可能发生拔出，下一轮会重新枚举。
            continue
        ports.append(list_ports_common.ListPortInfo(device))
    return ports
