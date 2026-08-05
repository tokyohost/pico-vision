"""验证 Windows 固件更新能够定位同设备的 mpremote REPL 串口。"""

import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace


MONITOR_ROOT = Path(__file__).resolve().parents[1]
if str(MONITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(MONITOR_ROOT))

WIN_PACKAGE = types.ModuleType("win")
WIN_PACKAGE.__path__ = [str(MONITOR_ROOT / "win")]
sys.modules.setdefault("win", WIN_PACKAGE)

from win.worker_controller import WorkerControllerMixin


def port(device, location, interface, serial_number="device-1"):
    """创建 pyserial ListPortInfo 所需字段的最小替身。"""
    return SimpleNamespace(
        device=device,
        location=location,
        interface=interface,
        description=interface,
        hwid="",
        serial_number=serial_number,
    )


class WindowsMpremoteUpdateTest(unittest.TestCase):
    """确认 Data CDC 不会被错误地交给 mpremote。"""

    def test_selects_repl_port_at_same_physical_usb_location(self):
        """同一复合 USB 设备应从 Data CDC 切换到 REPL CDC。"""
        ports = [
            port("COM8", "1-3:1.2", "FN Vision Data"),
            port("COM7", "1-3:1.0", "MicroPython REPL"),
            port("COM11", "1-4:1.0", "MicroPython REPL", "device-2"),
        ]

        selected = WorkerControllerMixin._mpremote_repl_port(
            {"transport": "串口", "address": "COM8"}, ports
        )

        self.assertEqual("COM7", selected)

    def test_rejects_websocket_connection(self):
        """WebSocket 没有可供 mpremote 使用的本地串口。"""
        with self.assertRaisesRegex(RuntimeError, "USB 串口"):
            WorkerControllerMixin._mpremote_repl_port(
                {"transport": "WebSocket", "address": "ws://device/pv1"}, []
            )

    def test_rejects_ambiguous_repl_ports(self):
        """缺少物理标识且存在多个 REPL 时不能猜测目标设备。"""
        ports = [
            port("COM8", "", "FN Vision Data", ""),
            port("COM7", "", "MicroPython REPL", ""),
            port("COM11", "", "MicroPython REPL", ""),
        ]
        with self.assertRaisesRegex(RuntimeError, "无法唯一识别"):
            WorkerControllerMixin._mpremote_repl_port(
                {"transport": "串口", "address": "COM8"}, ports
            )


if __name__ == "__main__":
    unittest.main()
