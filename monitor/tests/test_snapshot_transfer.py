"""验证快照事务分片的完整发送、增量更新和设备端操作语义。"""

import importlib.util
import sys
import json
import random
import time
from types import SimpleNamespace
from unittest import mock
import unittest
from pathlib import Path


MONITOR_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MONITOR_ROOT))

from snapshot_transfer import SnapshotSender


def load_board_module(board, filename):
    """隔离板级配置导入，避免 ESP32 的模块缓存污染 RP2040 测试。"""
    device_root = MONITOR_ROOT.parent / board
    names = ("config", "protocolC", "device_identity", "historyIncrease", "timeIncrease")
    saved = {name: sys.modules.pop(name) for name in names if name in sys.modules}
    sys.path.insert(0, str(device_root))
    try:
        spec = importlib.util.spec_from_file_location("snapshot_" + board.replace("-", "_") + filename[:-3], device_root / filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(device_root))
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


def load_device_protocol(board="esp32-s3"):
    """加载目标固件的真实协议实现与板级限制。"""
    return load_board_module(board, "protocol.py")


class SnapshotTransferTest(unittest.TestCase):
    """覆盖大数组分片、增量 K 线和事务操作安全性。"""

    def test_large_stocks_and_candles_are_split_under_wire_limit(self):
        """股票数组和单只股票 K 线都拆成不超过 4 KB 的事务片。"""
        snapshot = {
            "ext": {"stock_watch": {"stocks": [
                {"code": "600519", "candles": [
                    {"time": str(index), "open": 1, "close": 2,
                     "high": 3, "low": 0, "volume": 4}
                    for index in range(180)
                ]},
                {"code": "000001", "candles": []},
                {"code": "300750", "candles": []},
            ]}}
        }
        sender = SnapshotSender(limit=4096)
        payloads = sender.prepare(snapshot, 11)
        self.assertGreater(len(payloads), 1)
        self.assertLessEqual(max(map(len, payloads)), 4096)
        self.assertTrue(all(b'"mode":"snapshot_chunk"' in item for item in payloads))

    def test_confirmed_baseline_sends_only_changed_values(self):
        """批次确认后，下一次只发送新增股票和变化的 K 线字段。"""
        first = {"ext": {"stock_watch": {"stocks": [
            {"code": "600519", "candles": [{"time": "1", "close": 2}]}
        ]}}}
        second = {"ext": {"stock_watch": {"stocks": [
            {"code": "600519", "candles": [{"time": "1", "close": 2},
                                                {"time": "2", "close": 3}]},
            {"code": "000001", "candles": []},
        ]}}}
        sender = SnapshotSender(limit=4096)
        sender.prepare(first, 1)
        sender.confirm()
        payloads = sender.prepare(second, 2)
        text = b"".join(payloads)
        self.assertIn(b'"base":', text)
        self.assertIn(b'"code":"000001"', text)
        self.assertIn(b'"time":"2"', text)
        self.assertNotIn(b'"time":"1"', text)

    def test_device_applies_array_offsets_and_waits_for_all_parts(self):
        """设备端在收齐分片后提交，重复片幂等且不会覆盖已有数组。"""
        module = load_device_protocol()
        protocol = module.JsonProtocol
        initial = {"ext": {"stock_watch": {"stocks": [{"code": "600519"}]}}}
        operations = [
            {"op": "set", "path": ["ext", "stock_watch", "stocks"], "value": []},
            {"op": "resize", "path": ["ext", "stock_watch", "stocks"], "length": 2, "reset": True},
            {"op": "items", "path": ["ext", "stock_watch", "stocks"], "start": 0,
             "length": 2, "values": [{"code": "600519"}]},
            {"op": "items", "path": ["ext", "stock_watch", "stocks"], "start": 1,
             "length": 2, "values": [{"code": "000001"}]},
        ]
        result = protocol._apply_snapshot_chunk_ops(initial, operations)
        self.assertEqual(["600519", "000001"], [item["code"] for item in result["ext"]["stock_watch"]["stocks"]])

    def test_device_does_not_commit_missing_or_conflicting_duplicate_parts(self):
        """缺片不更新已显示快照，重复片必须内容一致才可幂等接受。"""
        module = load_device_protocol()
        protocol = module.JsonProtocol
        device = protocol.__new__(protocol)
        device._snapshot_chunk_transaction = None
        device._committed_snapshot = {"stocks": []}
        device._committed_batch = None
        device._ticks_ms = lambda: 100
        first = {"mode": "snapshot_chunk", "batch": "b1", "base": None,
                 "seq": 0, "count": 2, "ops": [
                     {"op": "set", "path": ["stocks"], "value": []}]}
        second = dict(first, seq=1, ops=[
            {"op": "resize", "path": ["stocks"], "length": 1, "reset": True},
            {"op": "items", "path": ["stocks"], "start": 0, "values": [{"code": "600519"}]},
        ])
        self.assertIsNone(device._handle_snapshot_chunk(first))
        self.assertIsNone(device._handle_snapshot_chunk(first))
        with self.assertRaises(ValueError):
            device._handle_snapshot_chunk(dict(first, ops=[]))
        # 冲突重复片不应破坏原事务，补发正确片后仍可完成。
        self.assertIsNone(device._handle_snapshot_chunk(first))
        result = device._handle_snapshot_chunk(second)
        self.assertEqual("600519", result["stocks"][0]["code"])

    def test_full_snapshot_resynchronizes_after_late_ack_or_reconnect(self):
        """旧批次已提交但发送端基线失效时，根路径全量批次可重新建立基线。"""
        module = load_device_protocol()
        protocol = module.JsonProtocol
        device = protocol.__new__(protocol)
        device._snapshot_chunk_transaction = None
        device._committed_snapshot = {"stale": True}
        device._committed_batch = "old-batch"
        device._ticks_ms = lambda: 100
        message = {"mode": "snapshot_chunk", "batch": "new-batch", "base": None,
                   "seq": 0, "count": 1, "ops": [
                       {"op": "set", "path": [], "value": {"stocks": [{"code": "300750"}]}}
                   ]}
        result = device._handle_snapshot_chunk(message)
        self.assertEqual("300750", result["stocks"][0]["code"])
        self.assertEqual("new-batch", device._committed_batch)


class SnapshotExtremeTest(unittest.TestCase):
    """同时验证两种固件在异常输入和连续增量下的原子性。"""

    def device(self, board):
        """创建不依赖真实硬件的事务接收端。"""
        protocol = load_device_protocol(board).JsonProtocol
        device = protocol.__new__(protocol)
        device._snapshot_chunk_transaction = None
        device._committed_snapshot = {}
        device._committed_batch = None
        device._ticks_ms = lambda: 100
        return device

    def test_randomized_roundtrip_and_type_changes(self):
        """随机嵌套数组、中文长文本、空值、删除和类型切换逐批完整还原。"""
        for board in ("esp32-s3", "picoRP2040"):
            device = self.device(board)
            sender = SnapshotSender(limit=700)
            rng = random.Random(20260910)
            for index in range(80):
                snapshot = {"value": [True, 1, False, 0, 1.0, None][index % 6],
                            "ext": {"stock": {"rows": [
                                {"time": str(j), "price": rng.random()} for j in range(rng.randrange(35))],
                                "text": "中文😀" * rng.randrange(80)}} if index % 4 else {}}
                payloads = sender.prepare(snapshot, index)
                messages = [json.loads(item) for item in payloads]
                # 首片建立全量事务，后续允许乱序，提交前始终保持旧快照。
                tail = messages[1:]
                rng.shuffle(tail)
                old = json.dumps(device._committed_snapshot, sort_keys=True)
                for position, message in enumerate(messages[:1] + tail):
                    result = device._handle_snapshot_chunk(message)
                    if position < len(messages) - 1:
                        self.assertIsNone(result)
                        self.assertEqual(old, json.dumps(device._committed_snapshot, sort_keys=True))
                        self.assertIsNone(device._handle_snapshot_chunk(message))
                self.assertEqual(json.dumps(snapshot, sort_keys=True), json.dumps(result, sort_keys=True), board)
                sender.confirm()

    def test_header_conflict_invalid_operation_and_recovery(self):
        """头冲突、缺片及非法操作均不能污染已提交数据，重置后可恢复。"""
        for board in ("esp32-s3", "picoRP2040"):
            device = self.device(board)
            first = {"batch": "a", "base": None, "seq": 0, "count": 2,
                     "ops": [{"op": "set", "path": [], "value": {"new": 1}}]}
            self.assertIsNone(device._handle_snapshot_chunk(first))
            for changes in ({"count": 3}, {"base": "wrong"}, {"ops": []}):
                with self.assertRaises(ValueError, msg=board):
                    device._handle_snapshot_chunk(dict(first, **changes))
                self.assertEqual({}, device._committed_snapshot)
            with self.assertRaises(ValueError):
                device._handle_snapshot_chunk(dict(first, seq=1, ops=[{"op": "invalid"}]))
            self.assertEqual({}, device._committed_snapshot)
            result = device._handle_snapshot_chunk(dict(first, batch="recovery", count=1))
            self.assertEqual({"new": 1}, result)

    def test_large_transaction_through_real_frames_and_decompression(self):
        """32KB 和 128KB 完整 JSON 经真实 PV1 校验、解压和组装突破单帧限制。"""
        from pico_protocol import build_jsonz_packet
        for board, rows in (("esp32-s3", 1800), ("picoRP2040", 450)):
            module = load_device_protocol(board)
            device = self.device(board)
            device._buffer = bytearray()
            device._frame_started_ms = None
            device._frame_read_calls = 0
            responses = []
            device._write_frame = lambda kind, payload: responses.append((kind, payload))
            rng = random.Random(17)
            snapshot = {"ext": {"stocks": [{"time": str(i), "name": "中文股票", "price": rng.random(),
                                             "volume": rng.randrange(100000)} for i in range(rows)]}}
            sender = SnapshotSender(max_bytes=module.SNAPSHOT_TRANSACTION_MAX_BYTES)
            self.assertGreater(len(json.dumps(snapshot).encode()), 16384)
            result = None
            for payload in sender.prepare(snapshot, 10):
                self.assertLessEqual(len(payload), 4096)
                packet = build_jsonz_packet(payload)
                # 网络可能把一个消息拆成多个读取块，解析器必须等待完整行。
                for offset in range(0, len(packet), 37):
                    device._buffer.extend(packet[offset:offset + 37])
                    received = device._parse_lines()
                    if received is not None:
                        result = received
            self.assertEqual(snapshot, result, board)
            self.assertEqual([("ACK", b"JSON:10")], responses)
            # 同样数据若塞入单条 JSONZ，压缩再小也必须因解压后超过 16KB 被拒绝。
            packet = build_jsonz_packet(json.dumps({"mode": "snapshot", "data": {"text": "x" * 17000}}).encode())
            device._buffer.extend(packet)
            self.assertIsNone(device._parse_lines())
            self.assertEqual("ERR", responses[-1][0])
            self.assertIn(b"JSON_TOO_LARGE", responses[-1][1])

    def test_network_and_cpu_budget_matrix_with_real_device_parser(self):
        """真实分片接收配合可控网络和 CPU 延迟，验证超时、丢片及全量恢复。"""
        from pico_client import PicoJsonClient, JsonAckTimeoutError
        snapshot = {"ext": {"stocks": [{"time": str(i), "name": "中文股票", "price": i / 7}
                                       for i in range(1800)]}}
        for scenario in ("正常", "网络抖动", "CPU繁忙", "丢片", "提交过慢"):
            with self.subTest(scenario=scenario):
                client = PicoJsonClient()
                client.serial = SimpleNamespace(is_open=True)
                client.snapshot_chunk_info = {"version": 1, "max_bytes": 262144}
                device = self.device("esp32-s3")
                device._buffer = bytearray()
                device._frame_started_ms = None
                device._frame_read_calls = 0
                device._write_frame = lambda kind, payload: client._notify_json_ack((kind, payload))
                clock = [100.0]
                sent = [0]
                recovering = [False]

                def write(packet, *args, **kwargs):
                    """按场景注入链路延迟、板端处理停顿或丢失单片。"""
                    sent[0] += 1
                    state = "正常" if recovering[0] else scenario
                    clock[0] += 0.002 + (0.03 if state == "网络抖动" and sent[0] % 2 else 0.0)
                    if state == "丢片" and sent[0] == 2:
                        return {}
                    device._buffer.extend(packet)
                    result = device._parse_lines()
                    clock[0] += 0.015 if state == "CPU繁忙" else 0.001
                    if result is not None and state == "提交过慢":
                        clock[0] += 0.5
                    return {}

                def wait_ack(request_id, event, timeout):
                    """缺片导致无 ACK 时耗尽剩余预算。"""
                    if not event.is_set():
                        clock[0] += timeout
                        raise JsonAckTimeoutError("模拟链路未收到完整事务 ACK")

                with mock.patch("pico_client.time.monotonic", side_effect=lambda: clock[0]), \
                        mock.patch.object(client, "_drain_json_responses"), \
                        mock.patch.object(client, "_write_packet", side_effect=write), \
                        mock.patch.object(client, "_complete_json_ack_timing"), \
                        mock.patch.object(client, "_wait_json_ack", side_effect=wait_ack):
                    if scenario != "丢片":
                        client.send(snapshot)
                    else:
                        with self.assertRaises(JsonAckTimeoutError):
                            client.send(snapshot)
                        self.assertIsNone(client._snapshot_sender.baseline)
                        if scenario != "提交过慢":
                            self.assertEqual({}, device._committed_snapshot)
                        recovering[0] = True
                        client.send(snapshot)
                    self.assertEqual(snapshot, client._snapshot_sender.baseline)
                    self.assertEqual(snapshot, device._committed_snapshot)

    def test_coalesced_transactions_preserve_deletion_and_cache_replacement(self):
        """粘包内连续提交及显示缓存均不能复活已删除插件数据。"""
        from pico_protocol import build_jsonz_packet
        for board in ("esp32-s3", "picoRP2040"):
            device = self.device(board)
            device._buffer = bytearray()
            device._frame_started_ms = None
            device._frame_read_calls = 0
            device._write_frame = lambda *args: None
            sender = SnapshotSender()
            old = {"ext": {"stock": {"price": 1}}, "removed": 1}
            new = {"ext": {}}
            first = sender.prepare(old, 1)
            sender.confirm()
            second = sender.prepare(new, 2)
            device._buffer.extend(b"".join(build_jsonz_packet(p) for p in first + second))
            self.assertEqual(new, device._parse_lines())
            receiver = load_board_module(board, "data_receiver.py")
            cache = receiver.SnapshotCache()
            cache.update(old, replace=True)
            cache.update(new, replace=True)
            self.assertEqual({}, cache.snapshot["ext"])
            self.assertNotIn("removed", cache.snapshot)

    def test_corrupt_wire_frame_cannot_commit_and_full_retry_recovers(self):
        """线路帧 CRC 损坏不能提交，后续完整事务可恢复全部内容。"""
        from pico_protocol import build_jsonz_packet
        for board in ("esp32-s3", "picoRP2040"):
            device = self.device(board)
            device._buffer = bytearray()
            device._frame_started_ms = None
            device._frame_read_calls = 0
            responses = []
            device._write_frame = lambda kind, payload: responses.append((kind, payload))
            sender = SnapshotSender()
            snapshot = {"text": "中文股票" * 500}
            packets = [build_jsonz_packet(item) for item in sender.prepare(snapshot, 1)]
            broken = bytearray(packets[1])
            broken[-4] ^= 1
            packets[1] = bytes(broken)
            for packet in packets:
                device._buffer.extend(packet)
                self.assertIsNone(device._parse_lines())
            self.assertEqual({}, device._committed_snapshot)
            self.assertTrue(any(kind == "ERR" for kind, payload in responses))
            self.assertFalse(any(kind == "ACK" for kind, payload in responses))
            sender.reset()
            result = None
            for payload in sender.prepare(snapshot, 2):
                device._buffer.extend(build_jsonz_packet(payload))
                result = device._parse_lines()
            self.assertEqual(snapshot, result)
            self.assertEqual(("ACK", b"JSON:2"), responses[-1])

    def test_device_transaction_budget_and_memory_failure_are_atomic(self):
        """超出事务预算或提交内存不足时保留旧快照，并允许完整恢复。"""
        for board in ("esp32-s3", "picoRP2040"):
            device = self.device(board)
            first = {"batch": "a", "base": None, "seq": 0, "count": 2,
                     "ops": [{"op": "set", "path": [], "value": {"new": 1}}]}
            self.assertIsNone(device._handle_snapshot_chunk(first, payload_size=40000))
            with self.assertRaisesRegex(ValueError, "BYTES_EXCEEDED"):
                device._handle_snapshot_chunk(dict(first, seq=1, ops=[]), payload_size=300000)
            self.assertEqual({}, device._committed_snapshot)
            self.assertIsNone(device._snapshot_chunk_transaction)
            recovery = dict(first, batch="b", count=1)
            with mock.patch.object(device, "_apply_snapshot_chunk_ops", side_effect=MemoryError):
                with self.assertRaises(MemoryError):
                    device._handle_snapshot_chunk(recovery)
            self.assertEqual({}, device._committed_snapshot)
            self.assertEqual({"new": 1}, device._handle_snapshot_chunk(dict(recovery, batch="c")))

    def test_wrong_ack_and_concurrent_send_cannot_confirm(self):
        """迟到 ACK、无序号 ACK 和其他命令 ACK 均不能确认当前事务。"""
        from pico_client import PicoJsonClient
        client = PicoJsonClient()
        client.snapshot_chunk_info = {"version": 1}
        event = client._register_json_ack_waiter(2)
        for payload in (b"JSON:1", b"JSON", b"COMMAND:2"):
            client._notify_json_ack(("ACK", payload))
            self.assertFalse(event.is_set())
        client._notify_json_ack(("ACK", b"JSON:2"))
        self.assertTrue(event.is_set())
        client._snapshot_send_lock.acquire()
        try:
            with self.assertRaisesRegex(RuntimeError, "已有快照"):
                client.send({})
        finally:
            client._snapshot_send_lock.release()

    def test_expired_transaction_requires_full_recovery(self):
        """过期缺片不能和新事务混合，旧基线错误被拒绝后可全量重建。"""
        for board in ("esp32-s3", "picoRP2040"):
            device = self.device(board)
            device._committed_batch = "old"
            first = {"batch": "a", "base": "old", "seq": 0, "count": 2,
                     "ops": [{"op": "set", "path": ["value"], "value": 1}]}
            self.assertIsNone(device._handle_snapshot_chunk(first))
            device._ticks_ms = lambda: 11000
            with self.assertRaisesRegex(ValueError, "BASE_MISMATCH"):
                device._handle_snapshot_chunk(dict(first, batch="bad", base="wrong"))
            self.assertEqual({}, device._committed_snapshot)
            reset = dict(first, batch="new", base=None, count=1,
                         ops=[{"op": "set", "path": [], "value": {"value": 2}}])
            self.assertEqual({"value": 2}, device._handle_snapshot_chunk(reset))

    def test_sender_limits_and_unconfirmed_mutation(self):
        """超大事务、非有限数被拒绝，外部修改不污染确认基线。"""
        for kwargs in ({"max_bytes": 10}, {"limit": 40}, {"limit": 300, "max_parts": 1}):
            sender = SnapshotSender(**kwargs)
            with self.assertRaises(ValueError):
                sender.prepare({"text": "中文" * 1000}, 1)
            self.assertIsNone(sender.pending)
        sender = SnapshotSender()
        with self.assertRaises(ValueError):
            sender.prepare({"value": float("nan")}, 1)
        snapshot = {"array": [1]}
        sender.prepare(snapshot, 1)
        snapshot["array"].append(2)
        sender.confirm()
        self.assertEqual({"array": [1]}, sender.baseline)

    def test_plugin_mode_filters_only_send_view(self):
        """样式切换只过滤发送副本，原始插件缓存继续更新且可立即恢复。"""
        from monitor_core.runtime_operations import RuntimeOperationsMixin
        service = RuntimeOperationsMixin()
        service._latest_collected_snapshot = {"ext": {"stock": {"price": 1}, "sensor": 2}}
        service._display_configuration_snapshot = mock.Mock(return_value={"style": "other"})
        service.custom_data_manager = SimpleNamespace(list_definitions=lambda: [
            SimpleNamespace(data_mode="active_style", key="stock", style_filename="style_stocks.py"),
            SimpleNamespace(data_mode="always", key="sensor")])
        self.assertEqual({"sensor": 2}, service._snapshot_for_sending()["ext"])
        service._latest_collected_snapshot["ext"]["stock"]["price"] = 3
        service._display_configuration_snapshot.return_value = {"style": "stocks"}
        self.assertEqual(3, service._snapshot_for_sending()["ext"]["stock"]["price"])

    def test_slow_transaction_and_ack_failure(self):
        """慢速构帧和写入不限制整批时长，ACK 失败仍清理基线。"""
        from pico_client import PicoJsonClient, JsonAckTimeoutError
        for fail_stage in ("build", "write", "ack", "success"):
            client = PicoJsonClient()
            client.serial = SimpleNamespace(is_open=True)
            client.snapshot_chunk_info = {"version": 1}
            clock = [10.0]
            original = client._snapshot_sender.prepare

            def prepare(snapshot, request_id):
                """模拟构帧耗时。"""
                result = original(snapshot, request_id)
                clock[0] += 20.0 if fail_stage == "build" else 0.05
                return result

            def write(*args, **kwargs):
                """模拟驱动写入耗时。"""
                self.assertIsNone(kwargs.get("deadline"))
                clock[0] += 20.0 if fail_stage == "write" else 0.1
                return {}

            def ack(request_id, event, timeout):
                """确认 ACK 具有独立等待窗口，并模拟无响应。"""
                self.assertEqual(timeout, 8.0)
                if fail_stage == "ack":
                    raise JsonAckTimeoutError("模拟设备无响应")
                clock[0] += 0.05

            with mock.patch("pico_client.time.monotonic", side_effect=lambda: clock[0]), \
                    mock.patch.object(client, "_drain_json_responses"), \
                    mock.patch.object(client._snapshot_sender, "prepare", side_effect=prepare), \
                    mock.patch.object(client, "_write_packet", side_effect=write), \
                    mock.patch.object(client, "_complete_json_ack_timing"), \
                    mock.patch.object(client, "_wait_json_ack", side_effect=ack):
                if fail_stage != "ack":
                    client.send({"value": 1})
                    self.assertEqual({"value": 1}, client._snapshot_sender.baseline)
                else:
                    with self.assertRaises(JsonAckTimeoutError):
                        client.send({"value": 1})
                    self.assertIsNone(client._snapshot_sender.baseline)
                self.assertEqual({}, client._json_ack_events)


if __name__ == "__main__":
    unittest.main()
