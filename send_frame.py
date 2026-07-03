#!/usr/bin/env python3
"""启动电脑端系统采集，并持续向 Pico 发送 JSON 快照。"""


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
import time

from pico_client import PicoJsonClient
from system_monitor import SystemInformationCollector


SEND_INTERVAL_SECONDS = 1.0


def create_argument_parser():
    """创建系统采集程序的命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="向 Pico LCD 发送系统状态 JSON")
    parser.add_argument("--port", help="固定串口名称；省略时自动发现")
    parser.add_argument(
        "--ping-target",
        default="www.baidu.com",
        help="网络延迟检测目标",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=SEND_INTERVAL_SECONDS,
        help="JSON 发送间隔，单位为秒，默认 0.5",
    )
    parser.add_argument("--once", action="store_true", help="仅发送一次，便于协议调试")
    return parser


def main():
    """持续采集系统信息，并按配置周期发送最新 JSON 快照。"""
    arguments = create_argument_parser().parse_args()
    if arguments.interval <= 0:
        raise SystemExit("--interval 必须大于 0")
    collector = SystemInformationCollector(arguments.ping_target)
    client = PicoJsonClient(arguments.port)
    client.connect()
    try:
        while True:
            started = time.monotonic()
            snapshot = collector.collect()
            client.send(snapshot)
            print(
                snapshot
            )
            if arguments.once:
                break
            time.sleep(max(0.0, arguments.interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        print("已停止系统状态发送。")
    finally:
        client.close()


if __name__ == "__main__":
    main()
