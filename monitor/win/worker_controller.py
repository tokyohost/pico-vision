"""Windows 后台监控进程控制器。"""

import json
import logging
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

from .constants import APPLICATION_NAME, MONITOR_DIRECTORY
from .settings import apply_worker_arguments

LOGGER = logging.getLogger("pico-monitor.windows-update")

# 主运行日志允许占用的最大磁盘空间，超限后仅保留末尾的最新内容。
MAXIMUM_LOG_SIZE = 15 * 1024 * 1024


class WorkerControllerMixin:
    """为托盘应用提供独立的业务能力。"""

    @staticmethod
    def _parse_worker_result(line, prefix, fallback_message):
        """从后台输出行中解析结构化 JSON 结果，兼容后续日志粘连到同一行的情况。"""
        payload = line[len(prefix):].strip()
        try:
            result, _ = json.JSONDecoder().raw_decode(payload)
        except json.JSONDecodeError:
            return {"status": "error", "message": fallback_message}
        if not isinstance(result, dict):
            return {"status": "error", "message": fallback_message}
        return result

    def _worker_command(self):
        """构造应用当前托盘配置后的后台监控命令。"""
        arguments = apply_worker_arguments(self.worker_arguments, self.settings)
        if getattr(sys, "frozen", False):
            return [sys.executable, *arguments]
        return [sys.executable, str(MONITOR_DIRECTORY / "pico_monitor.py"), *arguments]

    def _device_probe_command(self):
        """构造仅执行一次 Pico 设备探测的子进程命令。"""
        return [argument for argument in self._worker_command() if argument != "--worker"] + ["--pico-info"]

    def _start_worker(self):
        """启动后台监控进程，并创建日志收集线程。"""
        environment = os.environ.copy()
        environment.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"})
        environment["PICO_MONITOR_SETTINGS_PATH"] = str(self.settings_store.path)
        environment["PICO_MONITOR_SCREENSHOT_DIR"] = str(self.screenshot_directory)
        environment["PICO_MONITOR_ERROR_LOG_PATH"] = str(
            self.data_directory / "pico-monitor-error.log"
        )
        self.worker_process = subprocess.Popen(
            self._worker_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            creationflags=0x08000000, env=environment,
        )
        threading.Thread(target=self._collect_output, name="日志收集", daemon=True).start()

    def _stop_worker(self):
        """优雅停止后台监控，超时后再逐级终止并回收进程句柄。"""
        process = self.worker_process
        if process is None or process.poll() is not None:
            self.worker_process = None
            return
        try:
            if process.stdin is not None:
                process.stdin.write("EXIT\n")
                process.stdin.flush()
            process.wait(timeout=5)
        except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
            try:
                process.terminate()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                    process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    LOGGER.warning("后台监控进程无法在退出期限内结束：PID=%s", process.pid)
        finally:
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
            self.worker_process = None

    def _restart_worker(self):
        """停止并重新启动后台监控进程。"""
        self._stop_worker()
        if not self.stopping.is_set():
            self._start_worker()

    def _apply_display_settings(self):
        """向运行中的 Monitor 下发显示配置，避免重启后台进程。"""
        process = self.worker_process
        if process is None or process.poll() is not None or process.stdin is None:
            return False
        payload = {
            "lcd_style": self.settings["lcd_style"],
            "screen_rotation": self.settings["screen_rotation"],
            "lcd_brightness": self.settings["lcd_brightness"],
            "network_unit": self.settings["network_unit"],
        }
        try:
            process.stdin.write(
                "DISPLAY_CONFIG:{}\n".format(
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                )
            )
            process.stdin.flush()
            return True
        except (BrokenPipeError, OSError):
            return False

    def _apply_dev_settings(self):
        """向运行中的 Monitor 下发开发模式配置，避免重启后台进程。"""
        process = self.worker_process
        if process is None or process.poll() is not None or process.stdin is None:
            return False
        payload = {"enabled": bool(self.settings.get("dev"))}
        try:
            process.stdin.write(
                "DEV_CONFIG:{}\n".format(
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                )
            )
            process.stdin.flush()
            return True
        except (BrokenPipeError, OSError):
            return False

    def _activate_custom_data_plugin(self, name):
        """通知运行中的 Monitor 将指定自定义数据插件加入采集任务。"""
        process = self.worker_process
        if process is None or process.poll() is not None or process.stdin is None:
            return False
        payload = {"name": name}
        try:
            process.stdin.write(
                "CUSTOM_DATA_ACTIVATE:{}\n".format(
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                )
            )
            process.stdin.flush()
            return True
        except (BrokenPipeError, OSError):
            return False

    def _collect_output(self):
        """收集工作进程日志，并在 Pico 样式清单变化后刷新托盘菜单。"""
        process = self.worker_process
        self.log_path.touch(exist_ok=True)
        with self.log_path.open("r+b") as log_file:
            log_file.seek(0, os.SEEK_END)
            for line in process.stdout:
                log_file.write(line.encode("utf-8"))
                log_file.flush()
                self._truncate_log_file(log_file)
                if self.custom_style_upload_active.is_set():
                    self.custom_style_upload_logs.put(line.rstrip("\r\n"))
                if "STYLE_CATALOG_UPDATED" in line:
                    self._reload_style_catalog()
                    if self.icon is not None:
                        self.icon.update_menu()
                if line.startswith("DEVICE_REBOOT_RESULT:"):
                    result = self._parse_worker_result(
                        line, "DEVICE_REBOOT_RESULT:", "设备返回了无效响应",
                    )
                    self.device_management_messages.put(result)
                if line.startswith("CUSTOM_STYLE_LIST_RESULT:"):
                    result = self._parse_worker_result(
                        line, "CUSTOM_STYLE_LIST_RESULT:", "设备返回了无效响应",
                    )
                    self.custom_style_messages.put(result)
                if line.startswith("CUSTOM_STYLE_UPLOAD_RESULT:"):
                    result = self._parse_worker_result(
                        line, "CUSTOM_STYLE_UPLOAD_RESULT:", "设备返回了无效响应",
                    )
                    self.custom_style_upload_messages.put(result)
                    self.custom_style_upload_active.clear()
                if line.startswith("CUSTOM_STYLE_DELETE_RESULT:"):
                    result = self._parse_worker_result(
                        line, "CUSTOM_STYLE_DELETE_RESULT:", "设备返回了无效响应",
                    )
                    self.custom_style_delete_messages.put(result)
                if line.startswith("SCREENSHOT_RESULT:"):
                    result = self._parse_worker_result(
                        line, "SCREENSHOT_RESULT:", "设备返回了无效截图响应",
                    )
                    self._handle_screenshot_result(result)
                if "[串口关闭]" in line or "监控通信异常：" in line:
                    self._update_device_connection({"connected": False})
                connection = re.search(
                    r"\[串口连接\].*握手成功：开发板=(.*)，LCD=(.*)，屏幕方案=(.*)，固件版本=(.*)，分辨率=(.*)$",
                    line.strip(),
                )
                if connection:
                    self._update_device_connection({
                        "connected": True,
                        "board_model": connection.group(1),
                        "lcd_device_type": connection.group(2),
                        "screen_color_profile": connection.group(3),
                        "firmware_version": connection.group(4),
                        "screen_resolution": connection.group(5),
                    })
        return_code = process.wait()
        if not self.stopping.is_set() and process is self.worker_process and self.icon is not None:
            self.icon.notify("后台监控已退出，返回码：{}".format(return_code), APPLICATION_NAME)

    @staticmethod
    def _truncate_log_file(log_file, maximum_size=MAXIMUM_LOG_SIZE):
        """在日志超过限制时删除最旧内容，并保留完整 UTF-8 编码的最新内容。"""
        if log_file.tell() <= maximum_size:
            return
        log_file.seek(-maximum_size, os.SEEK_END)
        latest_content = log_file.read(maximum_size)
        while latest_content and latest_content[0] & 0xC0 == 0x80:
            latest_content = latest_content[1:]
        log_file.seek(0)
        log_file.write(latest_content)
        log_file.truncate()
        log_file.seek(0, os.SEEK_END)

    def _update_device_connection(self, connection):
        """保存最新设备连接快照，并通知已打开的设备管理窗口。"""
        snapshot = dict(connection)
        with self.device_connection_lock:
            self.current_device_connection = snapshot
        self.device_connection_messages.put(snapshot)

    def _handle_screenshot_result(self, result):
        """提示截图结果，并在成功时打开截图目录。"""
        if result.get("status") != "ok":
            if self.icon is not None:
                self.icon.notify(
                    "屏幕截图失败：{}".format(result.get("message", "未知错误")),
                    APPLICATION_NAME,
                )
            return
        path = Path(result["path"])
        try:
            subprocess.Popen(["explorer", str(path.parent)])
        except OSError as error:
            LOGGER.warning("打开截图目录失败：%s", error)
        if self.icon is not None:
            self.icon.notify("屏幕截图已保存：{}".format(path.name), APPLICATION_NAME)

    def _take_screenshot(self, icon=None, item=None):
        """通知 Monitor 工作进程向 Pico 下发 screenshot 命令。"""
        del item
        process = self.worker_process
        if process is None or process.poll() is not None or process.stdin is None:
            if icon is not None:
                icon.notify("后台监控未运行，无法截图", APPLICATION_NAME)
            return
        try:
            process.stdin.write("SCREENSHOT\n")
            process.stdin.flush()
            if icon is not None:
                icon.notify("正在截取 LCD 屏幕", APPLICATION_NAME)
        except (BrokenPipeError, OSError) as error:
            if icon is not None:
                icon.notify("截图请求失败：{}".format(error), APPLICATION_NAME)

    def _get_device_connection(self):
        """返回当前设备连接状态的独立快照。"""
        with self.device_connection_lock:
            return dict(self.current_device_connection)
