"""通过不可变引用替换向 JSON 发送线程发布最新采样结果。"""


class LockFreeSnapshotStore:
    """使用原子字段替换维护最新快照，并为发送方创建隔离视图。"""

    def __init__(self, initial_snapshot):
        """保存首个结构完整的快照，确保启动阶段可立即读取。"""
        self._snapshot = dict(initial_snapshot)

    def snapshot(self):
        """无锁返回最近一次发布的完整快照对象。"""
        return dict(self._snapshot)

    def publish(self, fragment):
        """合并单个任务结果并原子发布新快照，避免修改发送中的旧对象。"""
        for name, value in fragment.items():
            self._snapshot[name] = value
        return self.snapshot()
