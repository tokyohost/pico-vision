"""POSIX 桌面单实例锁；持有文件句柄期间锁始终有效。"""

from pathlib import Path


class SingleInstanceLock:
    """通过系统文件锁阻止同一用户启动重复桌面和采集进程。"""

    def __init__(self, path):
        """保存锁文件位置，不在导入阶段加载 POSIX 扩展。"""
        self.path = Path(path)
        self._stream = None

    def acquire(self):
        """非阻塞获取文件锁，锁冲突返回 False，权限错误交给调用者。"""
        import fcntl

        if self._stream is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            stream.close()
            return False
        except Exception:
            stream.close()
            raise
        self._stream = stream
        return True

    def close(self):
        """释放锁句柄，不删除锁文件，避免其他进程锁定不同 inode。"""
        if self._stream is not None:
            self._stream.close()
            self._stream = None
