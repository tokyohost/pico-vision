"""为设备端历史序列补齐缺失秒，并允许真实采样覆盖保持值。"""


def _is_history_field(name):
    """判断字段名称是否表示固定时间格历史序列。"""
    return name == "history" or str(name).endswith("_history")


def _history_values(value):
    """把可识别历史序列转换为列表，其他值返回空值。"""
    if isinstance(value, (list, tuple)):
        return list(value)
    return None


def _item_identity(value):
    """返回列表字典元素的稳定标识，便于磁盘等数组按对象匹配。"""
    if not isinstance(value, dict):
        return None
    for name in ("id", "name", "device", "mountpoint"):
        identity = value.get(name)
        if identity is not None:
            return name, str(identity)
    return None


class HistoryIncrease:
    """按本地时间秒推进全部历史字段，并用最近值填充缺失采样。"""

    def __init__(self):
        """创建尚未绑定时间秒的历史推进器。"""
        self.reset()

    def reset(self):
        """清除已经处理的时间秒，使下一份快照重新建立基准。"""
        self._processed_second = None

    def receive(self, previous, incoming, elapsed_second):
        """补齐真实快照到达前的缺秒，并用本秒真实值覆盖保持值。"""
        if elapsed_second is None:
            return incoming
        elapsed_second = max(0, int(elapsed_second))
        if previous is None or self._processed_second is None:
            self._processed_second = elapsed_second
            return incoming
        self.increase(previous, elapsed_second)
        return self._overlay_real_histories(previous, incoming)

    def increase(self, snapshot, elapsed_second):
        """把快照中的全部历史序列推进到指定秒，缺失时间格复制末值。"""
        if snapshot is None or elapsed_second is None:
            return snapshot
        elapsed_second = max(0, int(elapsed_second))
        if self._processed_second is None or elapsed_second < self._processed_second:
            self._processed_second = elapsed_second
            return snapshot
        missing_seconds = elapsed_second - self._processed_second
        if missing_seconds <= 0:
            return snapshot
        self._fill_histories(snapshot, missing_seconds)
        self._processed_second = elapsed_second
        return snapshot

    @classmethod
    def _fill_histories(cls, container, missing_seconds):
        """递归右移所有历史序列，并按缺失秒数追加最近值。"""
        if isinstance(container, dict):
            for name, value in container.items():
                history = _history_values(value) if _is_history_field(name) else None
                if history is not None:
                    if history:
                        latest_value = history[-1]
                        shift = min(missing_seconds, len(history))
                        history = history[shift:] + [latest_value] * shift
                    container[name] = history
                else:
                    cls._fill_histories(value, missing_seconds)
        elif isinstance(container, list):
            for item in container:
                cls._fill_histories(item, missing_seconds)

    @classmethod
    def _overlay_real_histories(cls, previous, incoming):
        """递归复制新快照，并仅用真实序列末值覆盖当前秒保持值。"""
        if not isinstance(incoming, dict):
            return incoming
        previous = previous if isinstance(previous, dict) else {}
        result = dict(incoming)
        for name, value in incoming.items():
            previous_value = previous.get(name)
            if _is_history_field(name):
                real_history = _history_values(value)
                local_history = _history_values(previous_value)
                if (
                    real_history is not None
                    and local_history is not None
                    and len(real_history) == len(local_history)
                    and local_history
                ):
                    local_history[-1] = real_history[-1]
                    result[name] = local_history
                continue
            if isinstance(value, dict):
                result[name] = cls._overlay_real_histories(previous_value, value)
            elif isinstance(value, list):
                result[name] = cls._overlay_real_list(previous_value, value)
        return result

    @classmethod
    def _overlay_real_list(cls, previous, incoming):
        """按稳定标识或原索引合并列表元素中的嵌套历史字段。"""
        previous_items = previous if isinstance(previous, list) else []
        identities = {
            _item_identity(item): item
            for item in previous_items
            if _item_identity(item) is not None
        }
        result = []
        for index, item in enumerate(incoming):
            if not isinstance(item, dict):
                result.append(item)
                continue
            previous_item = identities.get(_item_identity(item))
            if previous_item is None and index < len(previous_items):
                previous_item = previous_items[index]
            result.append(cls._overlay_real_histories(previous_item, item))
        return result
