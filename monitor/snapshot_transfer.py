"""生成 PV1 快照事务分片，按确认基线发送嵌套数组与增量字段。"""

import json
import uuid


def encode(value):
    """按线路实际使用的 ASCII 转义和紧凑格式序列化。"""
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


class SnapshotSender:
    """维护设备已确认的快照基线，构建有序且有大小上限的事务。"""

    def __init__(self, limit=4096, max_parts=4096, max_bytes=1048576):
        """保存协商上限并初始化独立连接会话。"""
        self.limit = min(4096, int(limit))
        self.max_parts = min(4096, int(max_parts))
        self.max_bytes = int(max_bytes)
        self.session = uuid.uuid4().hex[:16]
        self.sequence = 0
        self.baseline = None
        self.batch = None
        self.pending = None

    def reset(self):
        """放弃未确认数据和增量基线，下次发送完整快照。"""
        self.baseline = self.batch = self.pending = None

    def prepare(self, snapshot, request_id):
        """生成完整批次，每片包含路径、数组偏移、总长度和最终请求标识。"""
        # JSON 往返提供稳定副本，采集线程后续修改对象不会污染确认基线。
        target = json.loads(encode(snapshot))
        if not isinstance(target, dict):
            raise ValueError("快照必须为对象")
        self.sequence += 1
        batch = "{}-{}".format(self.session, self.sequence)
        base = self.batch
        template = {"mode": "snapshot_chunk", "version": 1, "batch": batch,
                    "base": base, "seq": self.max_parts, "count": self.max_parts,
                    "request_id": request_id, "ops": []}
        operations = []
        operation_sizes = []
        envelope_size = len(encode(template))

        def fits(ops):
            """按保守的最大序号信封检查实际字节数。"""
            return len(encode(dict(template, ops=ops))) <= self.limit

        def emit(op):
            """加入单个操作，拒绝无法装入单帧的路径或标量。"""
            if not fits([op]):
                raise ValueError("快照字段或路径超过分片上限：{}".format(op.get("path")))
            operations.append(op)
            operation_sizes.append(len(encode(op)))

        def put(path, value):
            """优先整体赋值，超限对象及数组递归拆分，长字符串按片写入。"""
            op = {"op": "set", "path": path, "value": value}
            if fits([op]):
                emit(op)
            elif isinstance(value, dict):
                emit({"op": "set", "path": path, "value": {}})
                for key, item in value.items():
                    put(path + [key], item)
            elif isinstance(value, list):
                emit({"op": "resize", "path": path, "length": len(value), "reset": True})
                index = 0
                while index < len(value):
                    # 连续数组项共用路径和偏移，降低 ESP32 JSON 节点数及操作调度次数。
                    part = {"op": "items", "path": path, "start": index,
                            "length": len(value), "values": [value[index]]}
                    if not fits([part]):
                        put(path + [index], value[index])
                        index += 1
                        continue
                    low, high = 1, 2
                    remaining = len(value) - index
                    # 先指数探测当前片容量，避免每一片都编码剩余数组的一大半。
                    while high <= remaining and fits([dict(part, values=value[index:index + high])]):
                        low = high
                        high *= 2
                    high = min(high - 1, remaining)
                    while low < high:
                        middle = (low + high + 1) // 2
                        if fits([dict(part, values=value[index:index + middle])]):
                            low = middle
                        else:
                            high = middle - 1
                    emit(dict(part, values=value[index:index + low]))
                    index += low
            elif isinstance(value, str):
                emit({"op": "set", "path": path, "value": ""})
                start = 0
                while start < len(value):
                    low, high = 1, min(self.limit, len(value) - start)
                    while low < high:
                        middle = (low + high + 1) // 2
                        part = {"op": "text", "path": path, "start": start,
                                "length": len(value), "value": value[start:start + middle]}
                        if fits([part]):
                            low = middle
                        else:
                            high = middle - 1
                    emit({"op": "text", "path": path, "start": start,
                          "length": len(value), "value": value[start:start + low]})
                    start += low
            else:
                emit(op)

        def diff(path, old, new):
            """递归生成变更，数组追加、缩短及末根 K 线更新不重发已有历史。"""
            if type(old) is type(new) and encode(old) == encode(new):
                return
            if isinstance(old, dict) and isinstance(new, dict):
                for key in old:
                    if key not in new:
                        emit({"op": "delete", "path": path + [key]})
                for key, value in new.items():
                    if key in old:
                        diff(path + [key], old[key], value)
                    else:
                        put(path + [key], value)
            elif isinstance(old, list) and isinstance(new, list):
                # 有固定窗口的 K 线移出旧数据时，用 shift 保留重叠历史。
                shift = 0
                if old and new and isinstance(new[0], dict):
                    identity = new[0].get("time") or new[0].get("date")
                    if identity:
                        for index, item in enumerate(old):
                            if isinstance(item, dict) and (item.get("time") or item.get("date")) == identity:
                                shift = index
                                break
                if shift:
                    emit({"op": "shift", "path": path, "start": shift, "length": len(new)})
                    old = old[shift:]
                if len(old) != len(new):
                    emit({"op": "resize", "path": path, "length": len(new), "reset": False})
                for index, value in enumerate(new):
                    if index < len(old):
                        diff(path + [index], old[index], value)
                    else:
                        put(path + [index], value)
            else:
                put(path, new)

        if self.baseline is None:
            put([], target)
        else:
            diff([], self.baseline, target)
        groups, current = [], []
        current_size = envelope_size
        for op, op_size in zip(operations, operation_sizes):
            required = op_size + int(bool(current))
            if current and current_size + required > self.limit:
                groups.append(current)
                current = []
                current_size = envelope_size
            current_size += op_size + int(bool(current))
            current.append(op)
        groups.append(current)
        if len(groups) > self.max_parts:
            raise ValueError("快照分片数量超过设备上限")
        payloads = [encode(dict(template, seq=index, count=len(groups), ops=ops))
                    for index, ops in enumerate(groups)]
        if sum(map(len, payloads)) > self.max_bytes:
            raise ValueError("快照事务超过设备内存预算")
        self.pending = (batch, target)
        return payloads

    def confirm(self):
        """收到设备最终确认后才推进增量基线。"""
        if self.pending is not None:
            self.batch, self.baseline = self.pending
            self.pending = None
