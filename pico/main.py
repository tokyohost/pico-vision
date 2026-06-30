"""启动 Pico 系统监控屏并编排接收与渲染循环。"""

import sys
import time

from config import RENDER_INTERVAL_MS
from dashboard import DashboardRenderer
from lcd import LcdDevice
from protocol import JsonProtocol, create_poller


def main():
    """初始化屏幕并按固定 0.5 秒周期渲染最新 JSON 快照。"""
    lcd = LcdDevice()
    lcd.initialize()
    renderer = DashboardRenderer(lcd)
    protocol = JsonProtocol()
    poller = create_poller(sys.stdin)
    latest_snapshot = None
    next_render = time.ticks_ms()
    protocol.write(b"BOOT:PICO_LCD_READY\n")

    while True:
        now = time.ticks_ms()
        remaining = max(0, time.ticks_diff(next_render, now))
        if poller is None:
            snapshot = protocol.receive()
        elif poller.poll(min(remaining, 50)):
            snapshot = protocol.receive()
        else:
            snapshot = None
        if snapshot is not None:
            latest_snapshot = snapshot

        now = time.ticks_ms()
        if time.ticks_diff(now, next_render) >= 0:
            renderer.render(latest_snapshot)
            next_render = time.ticks_add(next_render, RENDER_INTERVAL_MS)
            if time.ticks_diff(now, next_render) >= 0:
                next_render = time.ticks_add(now, RENDER_INTERVAL_MS)


if __name__ == "__main__":
    main()
