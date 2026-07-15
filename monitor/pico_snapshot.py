#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.

"""负责系统快照的精简、分片和 PV1 数据包构建。"""

import json

from pico_protocol import build_jsonz_packet


SNAPSHOT_JSON_CHUNK_SIZE = 4 * 1024


def wire_snapshot(snapshot):
    """生成线路快照对象，并移除 Pico 端不需要的重复字段。"""
    if snapshot.get("physical_disks") is None or "disks" not in snapshot:
        return snapshot
    # physical_disks 已包含 Pico 样式所需指标，不修改采集器持有的原始快照。
    result = dict(snapshot)
    result.pop("disks", None)
    return result


def build_json_payload(snapshot):
    """生成实际在线路上传输的紧凑 JSON 字节串。"""
    return json.dumps(
        wire_snapshot(snapshot),
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")


def snapshot_envelope_payload(snapshot, request_id=None):
    """把快照对象封装为 JSONZ 压缩前的信封字节。"""
    envelope = {"mode": "snapshot", "data": snapshot}
    if request_id is not None:
        envelope["request_id"] = request_id
    return json.dumps(envelope, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def split_snapshot_payloads(snapshot, request_id=None):
    """按顶层字段把大快照拆成多份小 JSON 信封。"""
    full_payload = snapshot_envelope_payload(snapshot, request_id=request_id)
    if len(full_payload) <= SNAPSHOT_JSON_CHUNK_SIZE:
        return [full_payload]

    payloads = []
    current = {}
    items = list(snapshot.items())
    for index, (key, value) in enumerate(items):
        candidate = dict(current)
        candidate[key] = value
        candidate_payload = snapshot_envelope_payload(candidate)
        if current and len(candidate_payload) > SNAPSHOT_JSON_CHUNK_SIZE:
            payloads.append(snapshot_envelope_payload(current))
            current = {key: value}
            continue
        current = candidate
        if index == len(items) - 1:
            payloads.append(snapshot_envelope_payload(current))

    if not payloads:
        payloads.append(snapshot_envelope_payload(snapshot))
    if request_id is not None:
        total_payloads = len(payloads)
        for index, payload in enumerate(list(payloads)):
            fragment_snapshot = json.loads(payload.decode("utf-8"))["data"]
            fragment_request_id = request_id
            if index < total_payloads - 1:
                fragment_request_id = "{}.{}/{}".format(request_id, index + 1, total_payloads)
            payloads[index] = snapshot_envelope_payload(
                fragment_snapshot,
                request_id=fragment_request_id,
            )
    return payloads


def build_packet(snapshot, request_id=None):
    """把单份快照编码为带长度与 CRC 的 PV1 数据帧。"""
    payload = snapshot_envelope_payload(wire_snapshot(snapshot), request_id=request_id)
    return build_jsonz_packet(payload)


def build_snapshot_packets(snapshot, request_id=None):
    """构建一份快照对应的一条或多条 JSONZ 帧。"""
    return [
        build_jsonz_packet(payload)
        for payload in split_snapshot_payloads(
            wire_snapshot(snapshot),
            request_id=request_id,
        )
    ]
