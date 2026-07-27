"""Web 界面的设备管理和 ESP32-S3 SDK 刷写接口。"""

import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time

from serial.tools import list_ports
from sdk_flash import (
    inspect_sdk_image,
    is_espressif_usb_port,
    wait_for_esp32s3_bootloader_port,
)

from ..ui.device_window import format_connection_method
from .config import SDK_IMAGE_FILE_TYPES


LOGGER = logging.getLogger("pico-monitor.web-ui")


def _compat_dependency(name, default):
    """读取旧入口上的依赖替换，保持现有测试和调用兼容。"""
    facade_name = __package__.rsplit(".", 1)[0] + ".ui_web"
    facade = sys.modules.get(facade_name)
    return getattr(facade, name, default)


def _inspect_sdk_image(path):
    """使用兼容入口解析并校验 SDK 镜像。"""
    return _compat_dependency("inspect_sdk_image", inspect_sdk_image)(path)


def _is_espressif_usb_port(port):
    """使用兼容入口判断串口是否属于乐鑫原生 USB 设备。"""
    return _compat_dependency(
        "is_espressif_usb_port", is_espressif_usb_port
    )(port)


class DeviceApiMixin:
    """处理设备状态、控制命令和 SDK 镜像刷写。"""

    __slots__ = ()

    def _device_status(self, payload):
        """返回当前工作进程维护的设备连接快照。"""
        del payload
        return self._application._get_device_connection()

    def _probe_device(self, payload):
        """请求常驻工作进程立即探测，并返回持续保持的连接快照。"""
        del payload
        connection = self._application._get_device_connection()
        if connection.get("connected"):
            return {
                "device": connection,
                "log": "设备已由常驻监控完成握手，保留当前连接。",
            }
        if not self._application._request_device_probe():
            raise RuntimeError("后台监控未运行，无法主动探测设备")
        deadline = time.monotonic() + 35.0
        while time.monotonic() < deadline:
            time.sleep(0.1)
            connection = self._application._get_device_connection()
            if connection.get("connected"):
                return {
                    "device": connection,
                    "log": "主动探测握手成功，连接已交由常驻监控持续使用。",
                }
            worker = self._application.worker_process
            if worker is None or worker.poll() is not None:
                raise RuntimeError("主动探测期间后台监控异常退出")
        raise RuntimeError("主动探测超时，未发现 OmniWatch 设备")

    def _take_screenshot(self, payload):
        """向工作进程发送 LCD 截图命令。"""
        del payload
        self._application._take_screenshot(self._application.icon)
        return {"requested": True}

    def _reboot_device(self, payload):
        """请求工作进程重启当前连接设备。"""
        del payload
        self._drain_queue(self._application.device_management_messages)
        if not self._application._write_worker_command("EXIT_REBOOT\n"):
            raise RuntimeError("后台监控未运行")
        return self._wait_worker_result(
            self._application.device_management_messages, 20
        )

    @staticmethod
    def _sdk_flash_allowed(connection):
        """判断当前连接是否满足 ESP32-S3 原生 USB 受控刷写条件。"""
        if not connection or not connection.get("connected"):
            return False
        board_model = str(connection.get("board_model") or "").lower().replace(
            "_", "-"
        )
        return bool(
            "esp32-s3" in board_model
            and format_connection_method(connection).startswith("USB CDC")
            and connection.get("sdk_update_supported")
            and _is_espressif_usb_port(connection.get("address"))
        )

    def _current_sdk_usb_connection(self):
        """重新读取并返回可执行受控 SDK 刷写的当前 USB 连接。"""
        connection = self._application._get_device_connection()
        if not self._sdk_flash_allowed(connection):
            raise RuntimeError(
                "受控刷写前设备 USB 连接已变化，请保持 USB CDC 连接后重试"
            )
        return connection

    @staticmethod
    def _sdk_image_payload(information):
        """将 SDK 镜像校验结果转换为可供界面展示的安全摘要。"""
        return {
            "name": information.path.name,
            "sdkVersion": information.sdk_version,
            "size": information.size,
            "sha256": information.sha256,
        }

    def _append_sdk_log(self, content):
        """追加 SDK 刷写日志，并限制界面侧缓存的最大行数。"""
        line = str(content).rstrip("\r\n")
        if not line:
            return
        LOGGER.info("[SDK 更新] %s", line)
        with self._sdk_lock:
            self._sdk_state["logs"].append(line)
            del self._sdk_state["logs"][:-1000]
            state = self._update_states["sdk"]
            state["logs"].append(line)
            del state["logs"][:-1000]
            percentage = re.search(
                r"(?:Writing|写入).*?\(?\s*(\d{1,3})\s*%",
                line,
                re.IGNORECASE,
            )
            if percentage:
                state["progress"] = min(95, 35 + int(percentage.group(1)) * 3 // 5)
            state["message"] = line

    def _select_sdk_image(self, payload):
        """选择并严格校验 ESP32-S3 完整合并 SDK 镜像。"""
        del payload
        with self._sdk_lock:
            if self._sdk_state["busy"]:
                raise RuntimeError("SDK 更新正在执行，不能更换镜像")
        path = self._select_file(SDK_IMAGE_FILE_TYPES)
        if not path:
            return {"cancelled": True}
        information = _inspect_sdk_image(path)
        image = self._sdk_image_payload(information)
        with self._sdk_lock:
            self._sdk_state["image_path"] = str(information.path)
            self._sdk_state["image"] = image
        return {"cancelled": False, "image": image}

    def _sdk_ports(self, payload):
        """返回强刷模式可供用户明确选择的串口清单。"""
        del payload
        ports = []
        for port in list_ports.comports():
            device = str(getattr(port, "device", "") or "").strip()
            if not device:
                continue
            vid = getattr(port, "vid", None)
            pid = getattr(port, "pid", None)
            identity = (
                "VID:{:04X} PID:{:04X}".format(vid, pid)
                if vid is not None and pid is not None
                else "VID/PID 未知"
            )
            ports.append({
                "device": device,
                "label": "{} - {} ({})".format(
                    device,
                    str(getattr(port, "description", "") or "未知设备").strip(),
                    identity,
                ),
            })
        return {"ports": ports}

    def _sdk_status(self, payload):
        """返回当前 SDK 更新状态和实时刷写日志快照。"""
        del payload
        with self._sdk_lock:
            return {
                "busy": self._sdk_state["busy"],
                "status": self._sdk_state["status"],
                "message": self._sdk_state["message"],
                "image": self._sdk_state["image"],
                "logs": "\n".join(self._sdk_state["logs"]),
            }

    def _run_sdk_flash_process(self, port, information, before=None):
        """运行隔离的 esptool 子进程，并实时收集标准输出。"""
        process = subprocess.Popen(
            self._application._sdk_flasher_command(
                port, information.path, before=before
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=0x08000000,
            env=dict(
                os.environ,
                PYTHONIOENCODING="utf-8",
                PYTHONUTF8="1",
                PYTHONUNBUFFERED="1",
                NO_COLOR="1",
            ),
        )
        if process.stdout is not None:
            for line in process.stdout:
                self._append_sdk_log(line)
        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError("esptool 刷写失败，返回码 {}".format(return_code))

    def _run_controlled_sdk_flash(self, information, connection):
        """让已连接设备进入 ROM USB 模式后执行受控 SDK 刷写。"""
        # 发送退出应用 USB 命令前再次读取连接，避免在线下载或线程调度期间
        # COM 号发生变化后仍使用旧地址匹配 ROM 重新枚举结果。
        del connection
        connection = self._current_sdk_usb_connection()
        worker = self._application.worker_process
        if worker is None or worker.poll() is not None or worker.stdin is None:
            raise RuntimeError("当前没有可控制的 USB 设备连接")
        source_device = str(connection.get("address") or "").strip()
        if not source_device:
            raise RuntimeError("无法确定当前 USB 设备的串口")
        self._append_sdk_log(
            "受控刷写已刷新当前 USB 串口：{}".format(source_device)
        )
        previous_ports = tuple(list_ports.comports())
        self._drain_queue(self._application.sdk_flash_messages)

        # 提前解除托盘对旧工作进程的所有权，避免正常退出后被日志线程自动拉起。
        self._application.worker_process = None
        worker.stdin.write("EXIT_SDK_BOOTLOADER\n")
        worker.stdin.flush()
        self._append_sdk_log("已发送受控 ROM 下载模式命令，等待设备确认……")
        try:
            result = self._application.sdk_flash_messages.get(timeout=12)
        except queue.Empty as error:
            raise RuntimeError("等待设备进入 ROM USB 下载模式超时") from error
        if result.get("status") != "ok":
            raise RuntimeError(
                result.get("message") or "设备拒绝进入 ROM USB 下载模式"
            )
        self._append_sdk_log(result.get("message") or "设备已确认")
        try:
            worker.wait(timeout=5)
        except subprocess.TimeoutExpired:
            worker.terminate()
            worker.wait(timeout=2)

        self._append_sdk_log("正在等待 ESP32-S3 ROM USB 串口重新枚举……")
        bootloader_port = wait_for_esp32s3_bootloader_port(
            source_device,
            previous_ports,
            timeout=15.0,
        )
        self._append_sdk_log(
            "设备已重新枚举并进入 ROM USB 下载模式：{}".format(bootloader_port)
        )
        self._run_sdk_flash_process(bootloader_port, information)

    def _run_forced_sdk_flash(self, information, port):
        """暂停常驻监控，并在用户指定串口上执行强制 SDK 刷写。"""
        worker = self._application.worker_process
        if worker is not None and worker.poll() is None:
            self._append_sdk_log("正在暂停常驻监控，准备独占串口刷写……")
            self._application._stop_worker()
        self._application.worker_process = None
        self._append_sdk_log("正在通过 {} 强制刷写 SDK……".format(port))
        self._run_sdk_flash_process(port, information, before="default-reset")

    def _run_sdk_flash_task(self, information, connection, force, port):
        """执行 SDK 刷写后台任务，并统一恢复工作进程和更新锁。"""
        controlled_worker = (
            None if force else self._application.worker_process
        )
        try:
            if force:
                self._run_forced_sdk_flash(information, port)
            else:
                self._run_controlled_sdk_flash(information, connection)
            message = "SDK 刷写完成，正在重新连接设备并校验版本"
            self._append_sdk_log(message)
            with self._sdk_lock:
                self._sdk_state["status"] = "success"
                self._sdk_state["message"] = message
            self._set_update_state("sdk", "success", 100, message)
        except Exception as error:
            LOGGER.exception("Web 设备管理 SDK 刷写失败：%s", error)
            message = "SDK 刷写失败：{}".format(error)
            self._append_sdk_log(message)
            with self._sdk_lock:
                self._sdk_state["status"] = "error"
                self._sdk_state["message"] = message
            self._set_update_state("sdk", "error", None, message)
        finally:
            with self._sdk_lock:
                self._sdk_state["busy"] = False
            try:
                if (
                    controlled_worker is not None
                    and controlled_worker.poll() is None
                ):
                    try:
                        controlled_worker.terminate()
                        controlled_worker.wait(timeout=2)
                    except (OSError, subprocess.TimeoutExpired):
                        controlled_worker.kill()
                if not self._application.stopping.is_set():
                    self._application._start_worker()
            except Exception as error:
                LOGGER.exception("SDK 刷写后恢复后台监控失败：%s", error)
                message = "SDK 刷写结束，但恢复后台监控失败：{}".format(error)
                self._append_sdk_log(message)
                with self._sdk_lock:
                    self._sdk_state["status"] = "error"
                    self._sdk_state["message"] = message
            finally:
                self._application.update_lock.release()

    def _start_sdk_flash(self, payload):
        """复核镜像和连接条件后启动受控刷写或手动强刷任务。"""
        force = bool(payload.get("force"))
        port = str(payload.get("port") or "").strip()
        with self._sdk_lock:
            image_path = self._sdk_state["image_path"]
            busy = self._sdk_state["busy"]
        if busy:
            raise RuntimeError("SDK 更新正在执行，请稍候")
        if not image_path:
            raise ValueError("请先选择并校验 SDK 镜像")
        information = _inspect_sdk_image(image_path)
        connection = self._application._get_device_connection()
        if force:
            available_ports = {
                str(getattr(item, "device", "") or "").strip()
                for item in list_ports.comports()
            }
            if not port or port not in available_ports:
                raise ValueError("请选择当前系统中有效的目标 COM 口")
        elif not self._sdk_flash_allowed(connection):
            raise RuntimeError(
                "当前连接不支持受控 SDK 刷写，请使用 ESP32-S3 原生 USB CDC 连接"
            )
        if not self._application.update_lock.acquire(blocking=False):
            raise RuntimeError("已有更新任务正在执行，请稍候")

        mode = "强刷" if force else "受控刷写"
        with self._sdk_lock:
            self._sdk_state.update({
                "busy": True,
                "status": "running",
                "message": "正在{} SDK，请勿断电或拔线".format(mode),
                "image": self._sdk_image_payload(information),
                "logs": [],
            })
        self._append_sdk_log(
            "开始{} SDK：文件={}，目标版本={}，大小={} 字节，SHA-256={}。".format(
                mode,
                information.path.name,
                information.sdk_version,
                information.size,
                information.sha256,
            )
        )
        threading.Thread(
            target=self._run_sdk_flash_task,
            args=(information, connection, force, port),
            name="Web SDK 更新",
            daemon=True,
        ).start()
        return self._sdk_status({})

