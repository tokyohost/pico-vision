"""管理 OmniWatch SensorHost 外部进程与 Named Pipe 通信。"""

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    import win32api
    import win32con
    import win32file
    import win32job
    import win32pipe
except ImportError:  # pragma: no cover - 非 Windows 或缺少 pywin32 时不可用
    win32api = None
    win32con = None
    win32file = None
    win32job = None
    win32pipe = None
import platform

LOGGER = logging.getLogger("pico-monitor.sensor-host")
DEFAULT_PIPE_NAME = "omniwatch.sensorhost"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 2.0


class SensorHostError(RuntimeError):
    """表示 SensorHost 进程管理或管道通信失败。"""


class SensorHostManager:
    """负责启动、探活、请求和关闭 SensorHost 进程。"""

    def __init__(self, executable_path=None, pipe_name=DEFAULT_PIPE_NAME):
        """保存宿主可执行文件路径、命名管道名称和进程状态。"""
        self.executable_path = self._resolve_executable_path(executable_path)
        self.pipe_name = pipe_name or DEFAULT_PIPE_NAME
        self.process = None
        self.job = None
        self.dependency_unavailable_message = self._dependency_unavailable_reason()
        self.available = self.dependency_unavailable_message is None and self.executable_path is not None
        self._unavailable_logged = False

    def start(self):
        """启动 SensorHost 并把子进程加入 Job Object。"""
        if not self.available:
            self._log_unavailable_once()
            return False
        if self.process is not None and self.process.poll() is None:
            return True
        command = [str(self.executable_path), "--pipe", self.pipe_name]
        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._attach_job_object()
            LOGGER.info("SensorHost 已启动：pid=%s，pipe=%s", self.process.pid, self.pipe_name)
            return True
        except (OSError, SensorHostError) as error:
            LOGGER.warning("SensorHost 启动失败：%s", error)
            self.available = False
            self.close()
            return False

    def snapshot(self, timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS):
        """请求一次 SensorHost 硬件传感器快照。"""
        if not self.start():
            return None
        try:
            return self._request("snapshot", timeout)
        except SensorHostError as error:
            LOGGER.warning("SensorHost 快照请求失败：%s", error)
            return None

    def close(self):
        """优雅关闭 SensorHost，失败时终止 Job Object 或进程。"""
        process = self.process
        if process is None:
            self._close_job_handle()
            return
        if process.poll() is None:
            try:
                self._request("shutdown", timeout=1.0)
                process.wait(timeout=2.0)
            except (SensorHostError, subprocess.TimeoutExpired, OSError):
                self._terminate_process_tree(process)
        self.process = None
        self._close_job_handle()

    def _request(self, command, timeout):
        """通过 Named Pipe 发送命令并返回响应 data 字段。"""
        handle = self._open_pipe(timeout)
        try:
            payload = json.dumps({"command": command}, ensure_ascii=False).encode("utf-8") + b"\n"
            win32file.WriteFile(handle, payload)
            response = self._read_response(handle)
        finally:
            win32file.CloseHandle(handle)
        if not response.get("ok"):
            raise SensorHostError("{}: {}".format(response.get("error"), response.get("message")))
        return response.get("data")

    def _open_pipe(self, timeout):
        """在指定超时时间内打开 SensorHost 命名管道。"""
        pipe_path = r"\\.\pipe\{}".format(self.pipe_name)
        deadline = time.monotonic() + max(0.1, float(timeout))
        while True:
            try:
                return win32file.CreateFile(
                    pipe_path,
                    win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                    0,
                    None,
                    win32con.OPEN_EXISTING,
                    0,
                    None,
                )
            except Exception as error:
                if time.monotonic() >= deadline:
                    raise SensorHostError("连接命名管道超时：{}".format(pipe_path)) from error
                try:
                    win32pipe.WaitNamedPipe(pipe_path, 250)
                except Exception:
                    time.sleep(0.05)

    @staticmethod
    def _read_response(handle):
        """读取单行 JSON 响应。"""
        chunks = []
        while True:
            _, data = win32file.ReadFile(handle, 4096)
            chunks.append(data)
            joined = b"".join(chunks)
            if b"\n" in joined:
                line = joined.split(b"\n", 1)[0]
                return json.loads(line.decode("utf-8"))

    def _attach_job_object(self):
        """创建 Job Object，并设置父进程退出时自动结束 SensorHost。"""
        if self.process is None or win32job is None:
            return
        try:
            self.job = win32job.CreateJobObject(None, "")
            info = win32job.QueryInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation)
            info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32job.SetInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation, info)
            handle = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, False, self.process.pid)
            try:
                win32job.AssignProcessToJobObject(self.job, handle)
            finally:
                win32api.CloseHandle(handle)
        except Exception as error:
            LOGGER.warning("SensorHost Job Object 绑定失败，将回退到普通进程关闭：%s", error)
            self._close_job_handle()

    def _terminate_process_tree(self, process):
        """终止 SensorHost 进程树。"""
        if self.job is not None:
            try:
                win32job.TerminateJobObject(self.job, 1)
                return
            except Exception as error:
                LOGGER.warning("SensorHost Job Object 终止失败，回退到 process.kill：%s", error)
        try:
            process.kill()
        except OSError:
            pass

    def _close_job_handle(self):
        """关闭 Job Object 句柄。"""
        if self.job is None or win32api is None:
            self.job = None
            return
        try:
            win32api.CloseHandle(self.job)
        finally:
            self.job = None

    def _log_unavailable_once(self):
        """只记录一次 SensorHost 不可用原因。"""
        if self._unavailable_logged:
            return
        if self.dependency_unavailable_message is not None:
            LOGGER.info("SensorHost 未启用：%s", self.dependency_unavailable_message)
        else:
            LOGGER.info("SensorHost 未启用：未找到可执行文件，请检查 sensorhost/OmniWatch.SensorHost.exe 是否随程序发布")
        self._unavailable_logged = True

    @staticmethod
    def _dependency_unavailable_reason():
        """返回 Windows 与 pywin32 能力缺失原因；可用时返回 None。"""
        if platform.system() != "Windows":
            return "当前环境不是 Windows"
        missing_modules = [
            name
            for name, module in (
                ("win32api", win32api),
                ("win32con", win32con),
                ("win32file", win32file),
                ("win32job", win32job),
                ("win32pipe", win32pipe),
            )
            if module is None
        ]
        if missing_modules:
            return "缺少 pywin32 模块：{}".format("、".join(missing_modules))
        return None

    @classmethod
    def _resolve_executable_path(cls, executable_path):
        """按显式参数、环境变量和常见打包目录查找 SensorHost 可执行文件。"""
        candidates = []
        for value in (executable_path, os.getenv("PICO_MONITOR_SENSOR_HOST_PATH")):
            if value:
                candidates.append(Path(value))
        for base_directory in cls._candidate_base_directories():
            candidates.extend(cls._executable_candidates_from_base(base_directory))
        for candidate in candidates:
            try:
                if candidate.is_file():
                    return candidate
            except OSError:
                continue
        return None

    @staticmethod
    def _candidate_base_directories():
        """生成源码运行、测试脚本运行和 PyInstaller 打包运行的搜索根目录。"""
        module_path = Path(__file__).resolve()
        base_directories = []

        def append_directory(directory):
            """按顺序加入目录并去重，避免重复检查相同路径。"""
            if directory is None:
                return
            try:
                resolved = Path(directory).resolve()
            except OSError:
                resolved = Path(directory)
            if resolved not in base_directories:
                base_directories.append(resolved)

        if getattr(sys, "frozen", False):
            append_directory(getattr(sys, "_MEIPASS", None))
            append_directory(Path(sys.executable).resolve().parent)
        append_directory(module_path.parents[1])
        append_directory(module_path.parents[2])
        append_directory(module_path.parents[3])
        append_directory(Path.cwd())
        return base_directories

    @staticmethod
    def _executable_candidates_from_base(base_directory):
        """按一个基准目录生成 SensorHost 可执行文件候选路径。"""
        return (
            base_directory / "sensorhost" / "OmniWatch.SensorHost.exe",
            base_directory / "monitor" / "sensorhost" / "OmniWatch.SensorHost.exe",
            base_directory / "pico-project" / "monitor" / "sensorhost" / "OmniWatch.SensorHost.exe",
            base_directory / "OmniWatch.SensorHost.exe",
            base_directory / "omniwatch-sensor-host" / "OmniWatch.SensorHost.exe",
            base_directory / "omniwatch-sensor-host" / "src" / "OmniWatch.SensorHost" / "bin" / "Release" / "net8.0-windows" / "win-x64" / "publish" / "OmniWatch.SensorHost.exe",
            base_directory / "omniwatch-sensor-host" / "src" / "OmniWatch.SensorHost" / "bin" / "Release" / "net8.0-windows" / "OmniWatch.SensorHost.exe",
            base_directory / "omniwatch-sensor-host" / "src" / "OmniWatch.SensorHost" / "bin" / "Debug" / "net8.0-windows" / "OmniWatch.SensorHost.exe",
        )
