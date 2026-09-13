"""验证 WebSocket 原生数据面与 Python 传输策略的协作边界。"""

import sys
import types
import unittest
from pathlib import Path
from unittest import mock


ESP32_ROOT = Path(__file__).resolve().parents[1]
if str(ESP32_ROOT) not in sys.path:
    sys.path.insert(0, str(ESP32_ROOT))

from net import websocket


class FakeWifiManager:
    """提供始终在线的 Wi-Fi 状态。"""

    def is_connected(self):
        """返回固定连接状态。"""
        return True

    def update(self):
        """模拟无需推进的 Wi-Fi 状态机。"""
        return None

    def status(self):
        """返回最小网络状态。"""
        return {"connected": True}


class FakeSocket:
    """提供原生数据面接管所需的最小 socket 接口。"""

    connected = True

    def fileno(self):
        """返回稳定的模拟文件描述符。"""
        return 23

    def close(self):
        """记录测试关闭操作。"""
        self.connected = False


class FakeServer:
    """提供不会产生新候选连接的监听 socket。"""

    def accept(self):
        """模拟非阻塞监听器当前没有待接入连接。"""
        raise OSError(11)

    def close(self):
        """忽略测试关闭操作。"""
        return None


class NativeWebSocketTransportTest(unittest.TestCase):
    """确认 C 层接收后 Python 只读取完整消息队列。"""

    def setUp(self):
        """创建可记录 attach、读取和发送行为的原生模块替身。"""
        self.frames = [b"PV1:PING:0:0000:\n"]
        self.sent = []
        self.native = types.SimpleNamespace(
            api_version=lambda: 1,
            attach=mock.Mock(),
            detach=mock.Mock(),
            connected=lambda: True,
            frames_available=lambda: len(self.frames),
            receive_activity=lambda: 0,
            read_frame=lambda: self.frames.pop(0) if self.frames else None,
            read_error=lambda: None,
            send=lambda payload, opcode: self.sent.append((bytes(payload), opcode))
            or len(payload),
        )

    def test_native_receive_queue_matches_cdc_complete_frame_interface(self):
        """原生接管后必须直接返回完整 PV1 帧而非 Python 半包。"""
        transport = websocket.WebSocketTransport(FakeWifiManager())
        transport._client = FakeSocket()
        transport._http_buffer = None
        transport._server = FakeServer()

        with mock.patch.object(websocket, "_native_websocket", self.native):
            self.assertTrue(transport._attach_native())
            self.native.attach.assert_called_once_with(23)
            self.assertTrue(transport.uses_complete_frame_queue())
            self.assertEqual(1, transport.available())
            self.assertEqual(b"PV1:PING:0:0000:\n", transport.read_frame())
            self.assertEqual(0, transport.available())
            self.assertEqual("native", transport.status()["websocket_backend"])

    def test_update_does_not_read_socket_after_native_takeover(self):
        """C 任务接管后主循环不得再对同一 socket 执行 recv。"""
        transport = websocket.WebSocketTransport(FakeWifiManager())
        transport._client = FakeSocket()
        transport._http_buffer = None
        transport._server = FakeServer()

        with mock.patch.object(websocket, "_native_websocket", self.native):
            transport._attach_native()
            with mock.patch.object(transport, "_read_socket") as read_socket:
                transport.update()
            read_socket.assert_not_called()

    def test_native_send_and_detach_share_the_owned_socket_lifecycle(self):
        """业务帧发送和关闭必须全部经过原生模块。"""
        transport = websocket.WebSocketTransport(FakeWifiManager())
        transport._client = FakeSocket()
        transport._http_buffer = None

        with mock.patch.object(websocket, "_native_websocket", self.native):
            transport._attach_native()
            self.assertEqual(4, transport.write(b"PV1\n"))
            self.assertEqual([(b"PV1\n", 0x2)], self.sent)
            transport.close()
            self.native.detach.assert_called_once_with()

    def test_firmware_module_uses_independent_bsd_socket_receive_task(self):
        """固件源码必须以 FreeRTOS 任务持续接收并提供四槽完整帧队列。"""
        repository_root = ESP32_ROOT.parents[1]
        source = (
            repository_root
            / "micropython/ports/esp32/usermod/fn_websocket/mod_fn_websocket.c"
        ).read_text(encoding="utf-8")
        cmake = (
            repository_root / "micropython/ports/esp32/usermod/micropython.cmake"
        ).read_text(encoding="utf-8")

        self.assertIn("FN_WEBSOCKET_FRAME_QUEUE_DEPTH (4)", source)
        self.assertIn("xTaskCreate(", source)
        self.assertIn("select(fd + 1", source)
        self.assertIn("recv(fd, chunk", source)
        self.assertIn("fn_websocket_feed_byte_locked", source)
        self.assertIn("MP_QSTR_frames_available", source)
        self.assertIn("MP_QSTR_receive_activity", source)
        self.assertIn("MP_QSTR_read_frame", source)
        self.assertIn("MP_QSTR_read_error", source)
        self.assertIn("MP_QSTR_send", source)
        self.assertIn("fn_websocket/micropython.cmake", cmake)


if __name__ == "__main__":
    unittest.main()
