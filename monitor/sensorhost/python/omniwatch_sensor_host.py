"""OmniWatch SensorHost 进程管理与 Named Pipe 客户端。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    import win32api
    import win32con
    import win32file
    import win32job
    import win32pipe
    import win32process
except ImportError:  # pragma: no cover - 仅 Windows monitor 环境需要 pywin32
    win32api = None
    win32con = None
    win32file = None
    win32job = None
    win32pipe = None
    win32process = None


DEFAULT_PIPE_NAME = "omniwatch.sensorhost"


class SensorHostError(RuntimeError):
    """表示 SensorHost 启动、通信或响应失败。"""


class SensorHostProcess:
    """使用 subprocess 启动 SensorHost，并用 Windows Job Object 绑定生命周期。"""

    def __init__(self, executable: str | os.PathLike[str], pipe_name: str = DEFAULT_PIPE_NAME):
        """保存可执行文件路径和命名管道名称。"""
        self.executable = Path(executable)
        self.pipe_name = pipe_name
        self.process: subprocess.Popen[str] | None = None
        self.job = None

    def start(self) -> None:
        """启动宿主进程并把进程加入 Job Object。"""
        self._ensure_windows_dependencies()
        if self.process and self.process.poll() is None:
            return
        command = [str(self.executable), "--pipe", self.pipe_name]
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            text=True,
        )
        self._attach_job_object()

    def stop(self, timeout: float = 2.0) -> None:
        """优雅关闭宿主进程，超时后终止整个 Job Object。"""
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            try:
                SensorHostClient(self.pipe_name).request("shutdown", timeout=timeout)
            except SensorHostError:
                pass
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if self.job is not None:
                    win32job.TerminateJobObject(self.job, 1)
                else:
                    process.kill()
        self.process = None
        if self.job is not None:
            win32api.CloseHandle(self.job)
            self.job = None

    def __enter__(self) -> "SensorHostProcess":
        """进入上下文时启动宿主进程。"""
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """离开上下文时关闭宿主进程。"""
        self.stop()

    def _attach_job_object(self) -> None:
        """创建 Job Object，并设置父进程退出时自动杀死子进程。"""
        if self.process is None:
            raise SensorHostError("SensorHost 进程尚未启动。")
        self.job = win32job.CreateJobObject(None, "")
        info = win32job.QueryInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation)
        info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation, info)
        handle = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, False, self.process.pid)
        try:
            win32job.AssignProcessToJobObject(self.job, handle)
        finally:
            win32api.CloseHandle(handle)

    @staticmethod
    def _ensure_windows_dependencies() -> None:
        """确认当前环境具备 pywin32 和 Windows Job Object 支持。"""
        if sys.platform != "win32" or win32job is None:
            raise SensorHostError("SensorHost 进程管理需要 Windows 与 pywin32。")


class SensorHostClient:
    """通过 Windows Named Pipe 与 SensorHost 交换行分隔 JSON 请求。"""

    def __init__(self, pipe_name: str = DEFAULT_PIPE_NAME):
        """保存命名管道名称。"""
        self.pipe_name = pipe_name

    def snapshot(self, timeout: float = 2.0) -> dict[str, Any]:
        """请求一次传感器快照。"""
        data = self.request("snapshot", timeout=timeout)
        if not isinstance(data, dict):
            raise SensorHostError("SensorHost 返回的快照不是对象。")
        return data

    def ping(self, timeout: float = 1.0) -> bool:
        """检测宿主进程是否可响应。"""
        try:
            data = self.request("ping", timeout=timeout)
        except SensorHostError:
            return False
        return isinstance(data, dict) and data.get("status") == "ok"

    def request(self, command: str, timeout: float = 2.0) -> Any:
        """发送单个命令并返回响应 data 字段。"""
        self._ensure_windows_dependencies()
        handle = self._open_pipe(timeout)
        try:
            payload = json.dumps({"command": command}, ensure_ascii=False).encode("utf-8") + b"\n"
            win32file.WriteFile(handle, payload)
            line = self._read_line(handle, timeout)
            response = json.loads(line.decode("utf-8"))
        finally:
            win32file.CloseHandle(handle)
        if not response.get("ok"):
            raise SensorHostError("{}: {}".format(response.get("error"), response.get("message")))
        return response.get("data")

    def _open_pipe(self, timeout: float):
        """在超时窗口内打开命名管道。"""
        deadline = time.monotonic() + max(0.0, timeout)
        path = r"\\.\pipe\{}".format(self.pipe_name)
        while True:
            try:
                return win32file.CreateFile(
                    path,
                    win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                    0,
                    None,
                    win32con.OPEN_EXISTING,
                    0,
                    None,
                )
            except win32file.error as error:
                if time.monotonic() >= deadline:
                    raise SensorHostError("连接 SensorHost Named Pipe 超时。") from error
                try:
                    win32pipe.WaitNamedPipe(path, 250)
                except win32pipe.error:
                    time.sleep(0.05)

    @staticmethod
    def _read_line(handle: object, timeout: float) -> bytes:
        """读取一行 UTF-8 响应数据。"""
        deadline = time.monotonic() + max(0.0, timeout)
        chunks: list[bytes] = []
        while time.monotonic() < deadline:
            _, data = win32file.ReadFile(handle, 4096)
            chunks.append(data)
            joined = b"".join(chunks)
            if b"\n" in joined:
                return joined.split(b"\n", 1)[0]
        raise SensorHostError("读取 SensorHost 响应超时。")

    @staticmethod
    def _ensure_windows_dependencies() -> None:
        """确认当前环境具备 pywin32 Named Pipe 支持。"""
        if sys.platform != "win32" or win32file is None:
            raise SensorHostError("SensorHost Named Pipe 客户端需要 Windows 与 pywin32。")


def main(argv: list[str] | None = None) -> int:
    """从命令行直接请求已手动启动的 SensorHost Named Pipe。"""
    parser = argparse.ArgumentParser(description="测试已启动 SensorHost 的 Named Pipe 响应。")
    parser.add_argument("--pipe", default=DEFAULT_PIPE_NAME, help="Named Pipe 名称，默认 omniwatch.sensorhost")
    parser.add_argument("--timeout", type=float, default=2.0, help="连接和读取超时时间，单位秒")
    parser.add_argument(
        "--command",
        choices=("ping", "snapshot", "shutdown"),
        default="snapshot",
        help="要发送给 SensorHost 的命令，默认 snapshot",
    )
    parser.add_argument("--pretty", action="store_true", help="按缩进格式输出 JSON 结果")
    args = parser.parse_args(argv)

    client = SensorHostClient(args.pipe)
    try:
        if args.command == "ping":
            data = client.request("ping", timeout=args.timeout)
        elif args.command == "snapshot":
            data = client.snapshot(timeout=args.timeout)
        else:
            data = client.request("shutdown", timeout=args.timeout)
    except SensorHostError as error:
        print("SensorHost 请求失败：{}".format(error), file=sys.stderr)
        return 1

    result = {
        "ok": True,
        "pipe": args.pipe,
        "command": args.command,
        "data": data,
    }
    indent = 2 if args.pretty else None
    print(json.dumps(result, ensure_ascii=False, indent=indent))
    return 0


if __name__ == "__main__":
     raise SystemExit(main())
    # main()
