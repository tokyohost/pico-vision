"""Web 界面的设备管理和 ESP32-S3 SDK 刷写接口。"""

from i18n import t

import base64
import json
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from desktop.common.platform import subprocess_flags

from serial.tools import list_ports
from build_info import MONITOR_VERSION
from pico_upgrade import PicoFirmwareArchive
from sdk_flash import (
    inspect_sdk_image,
    is_espressif_usb_port,
    wait_for_esp32s3_bootloader_port,
)

from desktop.common.device import format_connection_method
from .config import FIRMWARE_PACKAGE_FILE_TYPES, SDK_IMAGE_FILE_TYPES


LOGGER = logging.getLogger("pico-monitor.web-ui")


def _compat_dependency(name, default):
    """读取旧入口上的依赖替换，保持现有测试和调用兼容。"""
    facade_name = "win.ui_web"
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

    def _registration_api_base(self):
        """从市场页面地址推导若依设备注册API基础地址。"""
        configured_url = str(
            self._application.settings.get("market_url") or ""
        ).strip()
        parsed = urllib.parse.urlsplit(configured_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise RuntimeError(t('message.configure_a_valid_plugin_market_server_url_in_settings'))
        path = parsed.path.rstrip("/")
        if path.endswith("/market"):
            path = path[:-len("/market")]
        if not path:
            # 只有本机开发服务器提供 Vite 的 /dev-api 代理。未指定 API 路径的
            # 远程市场地址始终使用 /prod-api，不能按桌面构建版本误选 HTML 页面。
            path = (
                "/dev-api"
                if MONITOR_VERSION == "development" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
                else "/prod-api"
            )
        return "{}://{}{}".format(parsed.scheme, parsed.netloc, path)

    @staticmethod
    def _read_registration_response(response):
        """解析若依接口响应并将业务失败转换为清晰异常。"""
        try:
            result = json.loads(response.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError(t('message.the_registration_service_returned_an_invalid_response')) from error
        if int(result.get("code", 500)) != 200:
            raise RuntimeError(result.get("msg") or t('message.registration_service_request_failed'))
        return result

    def _request_registration_api(self, path, method="GET", body=None):
        """以JSON方式访问同源设备注册API。"""
        request_body = None
        request_url = self._registration_api_base() + path
        headers = {
            "Accept": "application/json",
            "User-Agent": "OmniWatch-Monitor",
        }
        if body is not None:
            request_body = json.dumps(
                body, ensure_ascii=False
            ).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request_log = (
            t('message.device_registration_method_url_body').format(
                method,
                request_url,
                json.dumps(body, ensure_ascii=False)
                if body is not None
                else "{}",
            )
        )
        LOGGER.info(request_log)
        self._application._append_application_log(request_log)
        request = urllib.request.Request(
            request_url,
            data=request_body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return self._read_registration_response(response)
        except urllib.error.HTTPError as error:
            try:
                return self._read_registration_response(error)
            except RuntimeError:
                raise
        except urllib.error.URLError as error:
            raise RuntimeError(t('message.cannot_connect_to_device_registration_service').format(error.reason)) from error

    def _device_registration_status(self, payload):
        """远程查询当前或指定设备UUID的注册状态。"""
        connection = self._application._get_device_connection()
        uuid = str(payload.get("uuid") or connection.get("device_id") or "").strip()
        if not uuid:
            return {"registered": False, "uuid": ""}
        query = urllib.parse.urlencode({"uuid": uuid})
        result = self._request_registration_api(
            "/device/registration/status?" + query
        )
        return {
            "registered": bool(result.get("registered")),
            "uuid": uuid,
        }

    def _register_device(self, payload):
        """解析用户粘贴的Base64注册码并上送当前设备信息。"""
        connection = self._application._get_device_connection()
        if not connection.get("connected"):
            raise RuntimeError(t('message.device_disconnected_cannot_register_now'))
        uuid = str(connection.get("device_id") or "").strip()
        if not uuid:
            raise RuntimeError(t('message.the_firmware_did_not_provide_a_device_uuid'))
        encoded_code = str(payload.get("registrationCode") or "").strip()
        if not encoded_code:
            raise ValueError(t('message.paste_a_base64_registration_code'))
        try:
            padding = "=" * (-len(encoded_code) % 4)
            registration = json.loads(
                base64.b64decode(encoded_code + padding, validate=True)
                .decode("utf-8")
            )
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(t('message.registration_code_is_not_valid_base64_json')) from error
        if not isinstance(registration, dict):
            raise ValueError(t('message.invalid_registration_json_structure'))
        if str(registration.get("uuid") or "").strip() != uuid:
            raise ValueError(t('message.registration_uuid_does_not_match_this_device'))
        result = self._request_registration_api(
            "/device/registration",
            method="POST",
            body={
                "uuid": uuid,
                "activationCode": registration.get("activationCode"),
                "remark": registration.get("remark"),
                "firmwareVersion": connection.get("firmware_version"),
                "sdkVersion": connection.get("sdk_version"),
            },
        )
        return {
            "registered": True,
            "uuid": uuid,
            "device": result.get("data") or {},
        }

    def _probe_device(self, payload):
        """请求常驻工作进程立即探测，并返回持续保持的连接快照。"""
        del payload
        connection = self._application._get_device_connection()
        if connection.get("connected"):
            return {
                "device": connection,
                "log": t('message.the_device_is_already_connected_to_monitor_keeping_the'),
            }
        if not self._application._request_device_probe():
            raise RuntimeError(t('message.monitor_is_not_running_cannot_scan_devices'))
        deadline = time.monotonic() + 35.0
        while time.monotonic() < deadline:
            time.sleep(0.1)
            connection = self._application._get_device_connection()
            if connection.get("connected"):
                return {
                    "device": connection,
                    "log": t('message.device_handshake_succeeded_monitor_will_keep_this_connection'),
                }
            worker = self._application.worker_process
            if worker is None or worker.poll() is not None:
                raise RuntimeError(t('message.monitor_exited_unexpectedly_during_the_scan'))
        raise RuntimeError(t('message.device_scan_timed_out_no_omniwatch_device_found'))

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
            raise RuntimeError(t('message.monitor_is_not_running'))
        return self._wait_worker_result(
            self._application.device_management_messages, 20
        )

    @staticmethod
    def _validate_firmware_package(path):
        """校验本地固件全量包是安全、可读取且非空的 ZIP 文件。"""
        if not str(path or "").strip():
            raise ValueError(t('message.select_a_full_device_firmware_package_first'))
        package_path = Path(path)
        if package_path.suffix.lower() != ".zip":
            raise ValueError(t('message.select_a_zip_firmware_package'))
        package = PicoFirmwareArchive(package_path)
        package.close()
        return package_path

    def _select_firmware_package(self, payload):
        """选择并校验待写入设备的本地全量固件包。"""
        path = str(payload.get("sourcePath") or "").strip()
        if not path:
            path = self._select_file((t('message.full_firmware_package_zip'), t('message.all_files')))
        if not path:
            return {"cancelled": True}
        package_path = self._validate_firmware_package(path)
        package = PicoFirmwareArchive(package_path)
        try:
            file_count = len(package.files)
        finally:
            package.close()
        return {
            "cancelled": False,
            "package": {
                "path": str(package_path),
                "name": package_path.name,
                "fileCount": file_count,
            },
        }

    @staticmethod
    def _serial_port_payload(port):
        """将 pyserial 串口描述转换为前端可显示的稳定结构。"""
        device = str(getattr(port, "device", "") or "").strip()
        vid = getattr(port, "vid", None)
        pid = getattr(port, "pid", None)
        identity = (
            "VID:{:04X} PID:{:04X}".format(vid, pid)
            if vid is not None and pid is not None
            else t('message.unknown_vid_pid')
        )
        return {
            "device": device,
            "label": "{} - {} ({})".format(
                device,
                str(getattr(port, "description", "") or t('message.unknown_device')).strip(),
                identity,
            ),
        }

    def _firmware_ports(self, payload):
        """返回固件更新可选择的串口及当前设备对应的推荐 REPL 串口。"""
        del payload
        available = tuple(list_ports.comports())
        ports = [
            self._serial_port_payload(port)
            for port in available
            if str(getattr(port, "device", "") or "").strip()
        ]
        recommended_port = ""
        connection = self._application._get_device_connection()
        if connection.get("connected"):
            try:
                recommended_port = self._application._mpremote_repl_port(
                    connection, available
                )
            except RuntimeError:
                recommended_port = ""
        return {"ports": ports, "recommendedPort": recommended_port}

    @staticmethod
    def _validate_selected_firmware_port(selected_port):
        """确认用户选择的固件更新串口仍然存在，并返回规范设备名。"""
        requested = str(selected_port or "").strip()
        if not requested:
            raise ValueError(t('ui.select_the_target_serial_port_for_firmware_update'))
        available = {
            str(getattr(port, "device", "") or "").strip().upper():
            str(getattr(port, "device", "") or "").strip()
            for port in list_ports.comports()
            if str(getattr(port, "device", "") or "").strip()
        }
        port = available.get(requested.upper())
        if not port:
            raise RuntimeError(t('message.selected_firmware_port_disconnected').format(requested))
        return port

    def _run_local_firmware_update(self, package_path, port, force):
        """在后台按所选模式安装本地固件包并恢复常驻监控。"""
        try:
            mode = t('ui.replace_all') if force else t('message.sha_256_incremental')
            self._set_update_state(
                "firmware",
                "running",
                20,
                t('message.local_firmware_validated_mode_pausing_monitor').format(mode),
                True,
            )
            self._application._stop_worker()
            self._set_update_state(
                "firmware",
                "running",
                50,
                t('message.using_mpremote_to_device_firmware').format(mode),
            )

            def report_progress(message, percent):
                """把 mpremote 输出同步到本地固件更新日志。"""
                progress = None if percent is None else 50 + int(percent * 0.45)
                self._set_update_state("firmware", "running", progress, message)

            self._application._install_pico_firmware_archive(
                package_path, port, report_progress, force=force
            )
            self._set_update_state(
                "firmware", "success", 100, t('message.local_firmware_updated_reconnecting_device')
            )
            LOGGER.info("本地设备固件更新完成：%s", package_path.name)
        except Exception as error:
            self._set_update_state(
                "firmware", "error", None, t('message.local_firmware_update_failed').format(error)
            )
            LOGGER.exception("本地设备固件更新失败：%s", error)
        finally:
            try:
                if not self._application.stopping.is_set() and (
                    self._application.worker_process is None
                    or self._application.worker_process.poll() is not None
                ):
                    self._application._start_worker()
            except Exception as error:
                LOGGER.exception("本地固件更新后恢复后台监控失败：%s", error)
                self._set_update_state(
                    "firmware",
                    "error",
                    None,
                    t('message.firmware_update_ended_but_monitor_could_not_resume').format(error),
                )
            finally:
                self._application.update_lock.release()

    def _start_local_firmware_update(self, payload):
        """使用用户选择的固件包、串口和更新模式启动后台任务。"""
        package_path = self._validate_firmware_package(
            payload.get("sourcePath") or payload.get("packagePath")
        )
        port = self._validate_selected_firmware_port(payload.get("port"))
        force = bool(payload.get("force"))
        if not self._application.update_lock.acquire(blocking=False):
            raise RuntimeError(t('message.another_update_is_running_please_wait'))
        try:
            self._set_update_state(
                "firmware", "running", 1, t('message.local_firmware_update_started'), True
            )
            threading.Thread(
                target=self._run_local_firmware_update,
                args=(package_path, port, force),
                name="Web 本地固件更新",
                daemon=True,
            ).start()
        except Exception:
            self._application.update_lock.release()
            raise
        return {
            "started": True,
            "packageName": package_path.name,
            "port": port,
            "force": force,
        }

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
                t('message.usb_connection_changed_keep_usb_cdc_connected_and_try')
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
        with self._sdk_lock:
            if self._sdk_state["busy"]:
                raise RuntimeError(t('message.sdk_update_is_running_cannot_change_the_image'))
        path = str(payload.get("sourcePath") or "").strip()
        if not path:
            path = self._select_file((t('message.sdk_image_bin'), t('message.all_files')))
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
            ports.append(self._serial_port_payload(port))
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
            creationflags=subprocess_flags(),
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
            raise RuntimeError(t('message.esptool_failed_with_exit_code').format(return_code))

    def _run_controlled_sdk_flash(self, information, connection):
        """让已连接设备进入 ROM USB 模式后执行受控 SDK 刷写。"""
        # 发送退出应用 USB 命令前再次读取连接，避免在线下载或线程调度期间
        # COM 号发生变化后仍使用旧地址匹配 ROM 重新枚举结果。
        del connection
        connection = self._current_sdk_usb_connection()
        worker = self._application.worker_process
        if worker is None or worker.poll() is not None or worker.stdin is None:
            raise RuntimeError(t('message.no_controllable_usb_device_connected'))
        source_device = str(connection.get("address") or "").strip()
        if not source_device:
            raise RuntimeError(t('message.cannot_determine_the_current_usb_device_port'))
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
            raise RuntimeError(t('message.timed_out_waiting_for_rom_usb_download_mode')) from error
        if result.get("status") != "ok":
            raise RuntimeError(
                result.get("message") or t('message.device_refused_to_enter_rom_usb_download_mode')
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
            message = t('message.sdk_flashed_reconnecting_and_verifying_version')
            self._append_sdk_log(message)
            with self._sdk_lock:
                self._sdk_state["status"] = "success"
                self._sdk_state["message"] = message
            self._set_update_state("sdk", "success", 100, message)
        except Exception as error:
            LOGGER.exception("Web 设备管理 SDK 刷写失败：%s", error)
            message = t('message.sdk_flash_failed').format(error)
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
                message = t('message.sdk_flashing_ended_but_monitor_could_not_resume').format(error)
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
            raise RuntimeError(t('message.sdk_update_is_running_please_wait'))
        if not image_path:
            raise ValueError(t('message.select_and_validate_an_sdk_image_first'))
        information = _inspect_sdk_image(image_path)
        connection = self._application._get_device_connection()
        if force:
            available_ports = {
                str(getattr(item, "device", "") or "").strip()
                for item in list_ports.comports()
            }
            if not port or port not in available_ports:
                raise ValueError(t('message.select_a_valid_target_com_port'))
        elif not self._sdk_flash_allowed(connection):
            raise RuntimeError(
                t('message.managed_sdk_flashing_requires_an_esp32_s3_native_usb')
            )
        if not self._application.update_lock.acquire(blocking=False):
            raise RuntimeError(t('message.another_update_is_running_please_wait'))

        mode = t('message.force_flash') if force else t('message.managed_flash')
        with self._sdk_lock:
            self._sdk_state.update({
                "busy": True,
                "status": "running",
                "message": t('message.running_for_sdk_do_not_power_off_or_unplug').format(mode),
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
