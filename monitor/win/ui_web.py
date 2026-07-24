"""pywebview 界面桥接层，统一承载 Windows 桌面端全部页面。"""

import base64
import json
import logging
import os
import queue
import re
import subprocess
import threading
import time

import custom_data
from serial.tools import list_ports
from build_info import GITHUB_REPOSITORY, MONITOR_VERSION
from qbittorrent_monitor import QbittorrentApiClient
from sdk_flash import (
    inspect_sdk_image,
    is_espressif_usb_port,
    wait_for_esp32s3_bootloader_port,
)
from windows_update import WindowsReleaseUpdater

from .constants import APPLICATION_NAME
from .settings import (
    COLLECTION_TASK_ZH_NAMES,
    DEFAULT_COLLECTION_TASK_INTERVALS,
    normalize_collection_task_intervals,
    style_names,
)
from .ui.device_window import (
    format_connection_method,
)
from .ui.wifi_window import (
    merge_wifi_networks,
    wifi_security_label,
    wifi_state_label,
)


LOGGER = logging.getLogger("pico-monitor.web-ui")
SDK_IMAGE_FILE_TYPES = ("SDK 镜像 (*.bin)", "所有文件 (*.*)")
SDK_RELEASE_REPOSITORY = "tokyohost/pico-vision-micropython-sdk"


class WebViewBridge:
    """向 Vue 界面公开单一 action 调用入口，不创建任何 HTTP 服务。"""

    __slots__ = ("_application", "_sdk_lock", "_sdk_state", "_update_states")

    def __init__(self, application):
        """保存托盘应用引用，供桥接动作复用现有业务能力。"""
        # pywebview 会递归暴露公开属性；宿主对象必须保持私有，避免扫描到
        # settings_window.native.browser.webview 并跨线程读取 WebView2 COM 属性。
        self._application = application
        self._sdk_lock = threading.Lock()
        self._sdk_state = {
            "busy": False,
            "status": "idle",
            "message": "",
            "image_path": None,
            "image": None,
            "logs": [],
        }
        self._update_states = {
            category: {
                "busy": False,
                "status": "idle",
                "message": "",
                "progress": 0,
                "logs": [],
            }
            for category in ("firmware", "sdk", "application")
        }

    def invoke(self, action, payload=None):
        """按动作名称调用受控业务方法，并返回可 JSON 序列化结果。"""
        payload = payload if isinstance(payload, dict) else {}
        handlers = {
            "app.bootstrap": self._bootstrap,
            "settings.save": self._save_settings,
            "settings.verifyQbittorrent": self._verify_qbittorrent,
            "update.check": self._check_update,
            "update.install": self._install_update,
            "update.status": self._update_status,
            "device.status": self._device_status,
            "device.probe": self._probe_device,
            "device.screenshot": self._take_screenshot,
            "device.reboot": self._reboot_device,
            "device.sdk.select": self._select_sdk_image,
            "device.sdk.ports": self._sdk_ports,
            "device.sdk.flash": self._start_sdk_flash,
            "device.sdk.status": self._sdk_status,
            "wifi.list": self._wifi_list,
            "wifi.connect": self._wifi_connect,
            "wifi.forget": self._wifi_forget,
            "websocket.list": self._websocket_list,
            "websocket.update": self._websocket_update,
            "style.list": self._style_list,
            "style.upload": self._style_upload,
            "style.delete": self._style_delete,
            "data.list": self._custom_data_list,
            "data.import": self._custom_data_import,
            "data.importDirectory": self._custom_data_import_directory,
            "data.installDependencies": self._custom_data_install_dependencies,
            "data.activate": self._custom_data_activate,
            "data.test": self._custom_data_test,
            "data.delete": self._custom_data_delete,
            "log.read": self._read_log,
            "log.clear": self._clear_log,
            "log.export": self._export_log,
            "system.openDataDirectory": self._open_data_directory,
        }
        handler = handlers.get(str(action))
        if handler is None:
            return self._error("不支持的界面动作：{}".format(action))
        try:
            result = handler(payload)
            if isinstance(result, dict) and "ok" in result:
                return result
            return {"ok": True, "data": result}
        except Exception as error:
            LOGGER.exception("执行界面动作失败：%s", action)
            return self._error(str(error) or "操作失败")

    @staticmethod
    def _error(message):
        """构造统一的桥接错误响应。"""
        return {"ok": False, "message": str(message)}

    @staticmethod
    def _drain_queue(target):
        """读取队列中最新一条结果，丢弃已经过时的历史结果。"""
        latest = None
        while True:
            try:
                latest = target.get_nowait()
            except queue.Empty:
                return latest

    def _bootstrap(self, payload):
        """返回首屏所需配置、样式、任务名称和设备状态。"""
        del payload
        application = self._application
        settings = dict(application.settings)
        settings["collection_task_intervals"] = normalize_collection_task_intervals(
            settings.get("collection_task_intervals")
        )
        qr_path = application._resource_path("assert", "fishQr.png")
        qr_data_url = ""
        if qr_path.is_file():
            qr_data_url = "data:image/png;base64," + base64.b64encode(
                qr_path.read_bytes()
            ).decode("ascii")
        return {
            "applicationName": APPLICATION_NAME,
            "version": MONITOR_VERSION,
            "settings": settings,
            "styles": application.settings.get("styles", []),
            "taskNames": COLLECTION_TASK_ZH_NAMES,
            "defaultTasks": list(DEFAULT_COLLECTION_TASK_INTERVALS),
            "device": application._get_device_connection(),
            "dataDirectory": str(application.data_directory),
            "about": {
                "author": "tokyohost",
                "wechat": "hi2024FL",
                "repository": GITHUB_REPOSITORY,
                "qrDataUrl": qr_data_url,
            },
        }

    def _save_settings(self, payload):
        """校验并保存 Vue 表单提交的完整设置。"""
        incoming = payload.get("settings")
        if not isinstance(incoming, dict):
            raise ValueError("缺少有效配置")
        current = self._application.settings
        updated = dict(current)
        allowed = set(current)
        updated.update({key: incoming[key] for key in incoming if key in allowed})
        updated["port"] = str(updated.get("port") or "").strip()
        updated["websocket_client_name"] = str(
            updated.get("websocket_client_name") or ""
        ).strip()[:64]
        updated["ping_target"] = str(updated.get("ping_target") or "").strip()
        updated["interval"] = float(updated["interval"])
        updated["reconnect_interval"] = float(updated["reconnect_interval"])
        updated["serial_probe_interval"] = float(updated["serial_probe_interval"])
        updated["qbittorrent_interval"] = float(updated["qbittorrent_interval"])
        if updated.get("network_unit") == "Mb":
            updated["network_unit"] = "Mbps"
        if updated.get("network_unit") not in ("MB", "Mbps"):
            raise ValueError("网络速率单位无效")
        updated["idle_timeout"] = int(updated["idle_timeout"])
        updated["screen_rotation"] = int(updated["screen_rotation"])
        updated["lcd_brightness"] = int(updated["lcd_brightness"])
        updated["adaptive_transmit"] = bool(updated["adaptive_transmit"])
        updated["force_usb_cdc"] = bool(updated.get("force_usb_cdc", False))
        updated["collection_task_logs"] = bool(updated["collection_task_logs"])
        updated["qbittorrent_enabled"] = bool(updated["qbittorrent_enabled"])
        updated["collection_task_intervals"] = normalize_collection_task_intervals(
            updated.get("collection_task_intervals")
        )
        if updated["lcd_style"] not in style_names(updated, idle=False):
            raise ValueError("界面样式无效")
        if updated["idle_style"] not in style_names(updated, idle=True):
            raise ValueError("待机样式无效")
        intervals = (
            updated["interval"],
            updated["reconnect_interval"],
            updated["serial_probe_interval"],
            updated["qbittorrent_interval"],
        )
        if (
            not updated["websocket_client_name"]
            or not updated["ping_target"]
            or updated["interval"] < 0.3
            or min(intervals[1:]) <= 0
            or updated["idle_timeout"] <= 0
            or not 1 <= updated["lcd_brightness"] <= 100
        ):
            raise ValueError("请检查设备名称、地址、亮度和时间间隔")
        if updated["qbittorrent_enabled"] and not all(
            (
                updated.get("qbittorrent_address"),
                updated.get("qbittorrent_username"),
                updated.get("qbittorrent_password"),
            )
        ):
            raise ValueError("启用 qBittorrent 后必须填写地址、用户名和密码")
        self._application.settings = updated
        self._application.settings_store.save(updated)
        if not self._application._apply_runtime_settings(wait=True):
            raise RuntimeError("后台监控未运行，配置将在下次启动时生效")
        if self._application.icon is not None:
            self._application.icon.update_menu()
            self._application.icon.notify("配置已保存并生效", APPLICATION_NAME)
        return {"saved": True}

    def _verify_qbittorrent(self, payload):
        """验证 qBittorrent WebUI 账号配置。"""
        client = QbittorrentApiClient(
            str(payload.get("address") or "").strip(),
            str(payload.get("username") or "").strip(),
            str(payload.get("password") or ""),
        )
        client.login()
        return {"verified": True}

    @staticmethod
    def _find_release_asset(assets, expected_name):
        """按不区分大小写的完整文件名查找发布资源。"""
        expected = str(expected_name or "").lower()
        return next(
            (
                item for item in assets
                if str(item.get("name") or "").lower() == expected
            ),
            None,
        )

    def _check_update(self, payload):
        """按类别检查设备固件、设备 SDK 或 OmniWatch 应用更新。"""
        category = str(payload.get("category") or "").strip()
        connection = self._application._get_device_connection()
        if category == "firmware":
            if not connection.get("connected"):
                raise RuntimeError("设备未连接，无法检查设备固件版本")
            current_version = str(connection.get("firmware_version") or "未知")
            updater = WindowsReleaseUpdater(GITHUB_REPOSITORY, current_version)
            latest_version, assets, notes = updater.latest_release(
                self._application.settings.get("update_url") or None,
                include_notes=True,
            )
            board_model = str(connection.get("board_model") or "").strip()
            lcd_type = str(connection.get("lcd_device_type") or "").strip()
            asset_name = "OmniWatch-pico-upgrade-v{}-{}-{}.zip".format(
                latest_version, board_model, lcd_type,
            )
            asset = self._find_release_asset(assets, asset_name)
            return {
                "category": category,
                "currentVersion": current_version,
                "latestVersion": latest_version,
                "updateAvailable": updater.firmware_update_available(
                    current_version, latest_version
                ),
                "applicable": True,
                "assetAvailable": asset is not None,
                "assetName": asset.get("name") if asset else asset_name,
                "notes": notes,
            }
        if category == "sdk":
            if not connection.get("connected"):
                raise RuntimeError("设备未连接，无法检查设备 SDK 版本")
            current_version = str(connection.get("sdk_version") or "未知")
            board_model = str(connection.get("board_model") or "").lower().replace("_", "-")
            if "esp32-s3" not in board_model:
                return {
                    "category": category,
                    "currentVersion": current_version,
                    "latestVersion": "不适用",
                    "updateAvailable": False,
                    "applicable": False,
                    "assetAvailable": False,
                    "assetName": "",
                    "notes": "当前开发板不使用 ESP32-S3 MicroPython SDK 镜像。",
                }
            updater = WindowsReleaseUpdater(SDK_RELEASE_REPOSITORY, current_version)
            latest_version, assets, notes = updater.latest_release(include_notes=True)
            asset_name = "micropython-ESP32_GENERIC_S3-N8R8-v{}.bin".format(
                latest_version
            )
            asset = self._find_release_asset(assets, asset_name)
            return {
                "category": category,
                "currentVersion": current_version,
                "latestVersion": latest_version,
                "updateAvailable": (
                    current_version.lstrip("v") != latest_version.lstrip("v")
                ),
                "applicable": True,
                "assetAvailable": asset is not None,
                "assetName": asset.get("name") if asset else asset_name,
                "notes": notes,
            }
        if category == "application":
            updater = WindowsReleaseUpdater(GITHUB_REPOSITORY, MONITOR_VERSION)
            latest_version, assets, notes = updater.latest_release(
                self._application.settings.get("update_url") or None,
                include_notes=True,
            )
            try:
                asset = updater.select_monitor_asset(assets, latest_version)
            except RuntimeError:
                asset = None
            return {
                "category": category,
                "currentVersion": MONITOR_VERSION,
                "latestVersion": latest_version,
                "updateAvailable": updater.update_available(latest_version),
                "applicable": True,
                "assetAvailable": asset is not None,
                "assetName": asset.get("name") if asset else "",
                "notes": notes,
            }
        raise ValueError("不支持的更新检查类别：{}".format(category))

    def _run_firmware_release_update(self, updater, asset, latest_version):
        """下载并安装设备固件发布包，结束后恢复常驻监控。"""
        package_path = None
        try:
            self._set_update_state(
                "firmware", "running", 10, "正在下载设备固件", True
            )
            package_path = updater.download(asset, ".zip")
            self._set_update_state("firmware", "running", 45, "固件下载完成，正在暂停监控")
            self._application._stop_worker()
            self._set_update_state("firmware", "running", 65, "正在安装设备固件")
            self._application._upgrade_pico_from_package(package_path)
            self._set_update_state(
                "firmware",
                "success",
                100,
                "设备固件已更新至 {}".format(latest_version),
            )
            LOGGER.info("设备固件已立即更新至 %s", latest_version)
        except Exception as error:
            self._set_update_state(
                "firmware",
                "error",
                None,
                "设备固件立即更新失败：{}".format(error),
            )
            LOGGER.exception("设备固件立即更新失败：%s", error)
        finally:
            if package_path is not None:
                updater.remove_file(package_path)
            if not self._application.stopping.is_set() and (
                self._application.worker_process is None
                or self._application.worker_process.poll() is not None
            ):
                self._application._start_worker()
            self._application.update_lock.release()

    def _run_sdk_release_update(self, updater, asset, connection):
        """下载 SDK 发布镜像并通过受控 USB 模式立即刷写。"""
        image_path = None
        delegated = False
        try:
            self._set_update_state("sdk", "running", 10, "正在下载 SDK 镜像", True)
            image_path = updater.download(asset, ".bin")
            self._set_update_state("sdk", "running", 30, "SDK 镜像下载完成，正在校验")
            information = inspect_sdk_image(image_path)
            # 在线下载可能持续数秒，期间后台监控可能重连并更换 COM 号。
            # 必须丢弃点击“立即更新”时的旧快照，使用刷写前的当前 USB 身份。
            connection = self._current_sdk_usb_connection()
            with self._sdk_lock:
                self._sdk_state.update({
                    "busy": True,
                    "status": "running",
                    "message": "正在下载并刷写最新 SDK，请勿断电或拔线",
                    "image_path": image_path,
                    "image": self._sdk_image_payload(information),
                    "logs": [],
                })
            delegated = True
            self._run_sdk_flash_task(information, connection, False, "")
        except Exception as error:
            self._set_update_state(
                "sdk", "error", None, "SDK 立即更新失败：{}".format(error)
            )
            LOGGER.exception("SDK 立即更新失败：%s", error)
            with self._sdk_lock:
                self._sdk_state.update({
                    "busy": False,
                    "status": "error",
                    "message": "SDK 立即更新失败：{}".format(error),
                })
        finally:
            if image_path is not None:
                updater.remove_file(image_path)
                with self._sdk_lock:
                    if self._sdk_state.get("image_path") == image_path:
                        self._sdk_state["image_path"] = None
            if not delegated:
                self._application.update_lock.release()

    def _install_update(self, payload):
        """按更新类别立即启动应用、设备固件或 SDK 更新。"""
        category = str(payload.get("category") or "").strip()
        if category == "application":
            self._set_update_state("application", "running", 10, "正在打开应用更新流程", True)
            self._application._check_for_updates(self._application.icon)
            self._set_update_state("application", "success", 100, "应用更新流程已打开")
            return {"category": category, "started": True}

        connection = self._application._get_device_connection()
        if not connection.get("connected"):
            raise RuntimeError("设备未连接，无法立即更新")
        if not self._application.update_lock.acquire(blocking=False):
            raise RuntimeError("已有更新任务正在执行，请稍候")
        try:
            if category == "firmware":
                current_version = str(connection.get("firmware_version") or "未知")
                updater = WindowsReleaseUpdater(GITHUB_REPOSITORY, current_version)
                latest_version, assets = updater.latest_release(
                    self._application.settings.get("update_url") or None
                )
                if not updater.firmware_update_available(current_version, latest_version):
                    raise RuntimeError("设备固件已是最新版本")
                board_model = str(connection.get("board_model") or "").strip()
                lcd_type = str(connection.get("lcd_device_type") or "").strip()
                asset_name = "OmniWatch-pico-upgrade-v{}-{}-{}.zip".format(
                    latest_version, board_model, lcd_type,
                )
                asset = self._find_release_asset(assets, asset_name)
                if asset is None:
                    raise RuntimeError("当前发布中缺少适配设备固件：{}".format(asset_name))
                target = self._run_firmware_release_update
                arguments = (updater, asset, latest_version)
            elif category == "sdk":
                if not self._sdk_flash_allowed(connection):
                    raise RuntimeError("当前连接不支持 ESP32-S3 SDK 受控更新")
                current_version = str(connection.get("sdk_version") or "未知")
                updater = WindowsReleaseUpdater(SDK_RELEASE_REPOSITORY, current_version)
                latest_version, assets = updater.latest_release()
                if current_version.lstrip("v") == latest_version.lstrip("v"):
                    raise RuntimeError("设备 SDK 已是最新版本")
                asset_name = "micropython-ESP32_GENERIC_S3-N8R8-v{}.bin".format(
                    latest_version
                )
                asset = self._find_release_asset(assets, asset_name)
                if asset is None:
                    raise RuntimeError("当前发布中缺少适配 SDK 镜像：{}".format(asset_name))
                target = self._run_sdk_release_update
                arguments = (updater, asset, connection)
            else:
                raise ValueError("不支持的立即更新类别：{}".format(category))
            self._set_update_state(
                category, "running", 1, "更新任务已启动，正在准备", True
            )
            threading.Thread(
                target=target,
                args=arguments,
                name="Web 立即更新-{}".format(category),
                daemon=True,
            ).start()
            return {"category": category, "started": True}
        except Exception:
            self._application.update_lock.release()
            raise

    def _set_update_state(
        self, category, status, progress, message, reset_logs=False
    ):
        """更新指定在线更新任务的进度，并把阶段消息追加到实时日志。"""
        with self._sdk_lock:
            state = self._update_states[category]
            if reset_logs:
                state["logs"] = []
            state["status"] = status
            state["busy"] = status == "running"
            if progress is not None:
                state["progress"] = max(0, min(100, int(progress)))
            state["message"] = str(message)
            if message:
                state["logs"].append(str(message))
                del state["logs"][:-1000]

    def _update_status(self, payload):
        """返回全部或指定类别在线更新任务的进度与实时日志快照。"""
        category = str(payload.get("category") or "").strip()
        with self._sdk_lock:
            categories = (category,) if category else tuple(self._update_states)
            result = {}
            for name in categories:
                if name not in self._update_states:
                    raise ValueError("不支持的更新状态类别：{}".format(name))
                state = self._update_states[name]
                result[name] = {
                    "busy": state["busy"],
                    "status": state["status"],
                    "message": state["message"],
                    "progress": state["progress"],
                    "logs": "\n".join(state["logs"]),
                }
            return result[category] if category else result

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
            and is_espressif_usb_port(connection.get("address"))
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
        information = inspect_sdk_image(path)
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
            source_device, previous_ports, timeout=15.0
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
        information = inspect_sdk_image(image_path)
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

    def _wait_worker_result(self, target, timeout=12, expected_action=None):
        """等待匹配 action 的异步结果，并忽略队列中的陈旧响应。"""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("等待设备响应超时，请确认设备连接和固件功能")
            try:
                result = target.get(timeout=remaining)
            except queue.Empty as error:
                raise RuntimeError(
                    "等待设备响应超时，请确认设备连接和固件功能"
                ) from error
            if (
                expected_action is not None
                and result.get("action") != expected_action
            ):
                continue
            if result.get("status") != "ok":
                raise RuntimeError(result.get("message") or "设备操作失败")
            return result

    def _wifi_list(self, payload):
        """扫描并返回设备附近 Wi-Fi 列表。"""
        del payload
        self._drain_queue(self._application.wifi_messages)
        if not self._application._request_wifi_list():
            raise RuntimeError("后台监控未运行")
        result = self._wait_worker_result(
            self._application.wifi_messages, 22, "list"
        )
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        networks = merge_wifi_networks(data.get("networks"), data.get("wifi"))
        for network in networks:
            network["state_label"] = wifi_state_label(network)
            network["security_label"] = wifi_security_label(
                network.get("security")
            )
        return {
            "action": "list",
            "networks": networks,
            "wifi": data.get("wifi") or {},
        }

    def _wifi_connect(self, payload):
        """请求设备连接指定 Wi-Fi。"""
        self._drain_queue(self._application.wifi_messages)
        if not self._application._request_wifi_connect(
            str(payload.get("ssid") or ""), str(payload.get("password") or "")
        ):
            raise RuntimeError("后台监控未运行")
        result = self._wait_worker_result(
            self._application.wifi_messages, 25, "connect"
        )
        return result.get("data") or {}

    def _wifi_forget(self, payload):
        """请求设备忘记指定 Wi-Fi。"""
        self._drain_queue(self._application.wifi_messages)
        if not self._application._request_wifi_forget(str(payload.get("ssid") or "")):
            raise RuntimeError("后台监控未运行")
        result = self._wait_worker_result(
            self._application.wifi_messages, 15, "forget"
        )
        return result.get("data") or {}

    def _websocket_list(self, payload):
        """读取设备保存的 WebSocket 客户端策略。"""
        del payload
        self._drain_queue(self._application.websocket_client_messages)
        if not self._application._request_websocket_client_list():
            raise RuntimeError("后台监控未运行")
        result = self._wait_worker_result(
            self._application.websocket_client_messages, 12, "list"
        )
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        clients = []
        for client in data.get("clients", ()):
            if not isinstance(client, dict) or not client.get("id"):
                continue
            normalized = dict(client)
            normalized["enabled"] = bool(client.get("enabled", True))
            normalized["active"] = bool(client.get("active", False))
            try:
                normalized["priority"] = int(client.get("priority", 0))
            except (TypeError, ValueError):
                normalized["priority"] = 0
            try:
                normalized["connections"] = int(client.get("connections", 0))
            except (TypeError, ValueError):
                normalized["connections"] = 0
            clients.append(normalized)
        return {"action": "list", "clients": clients}

    def _websocket_update(self, payload):
        """更新一个 WebSocket 客户端的启用状态和优先级。"""
        self._drain_queue(self._application.websocket_client_messages)
        if not self._application._request_websocket_client_update(
            payload.get("id"),
            payload.get("enabled"),
            payload.get("priority"),
        ):
            raise RuntimeError("后台监控未运行")
        result = self._wait_worker_result(
            self._application.websocket_client_messages, 12, "update"
        )
        return result.get("data") or {}

    def _style_list(self, payload):
        """刷新并返回设备样式目录。"""
        del payload
        self._drain_queue(self._application.custom_style_messages)
        if not self._application.request_custom_style_catalog():
            raise RuntimeError("后台监控未运行")
        result = self._wait_worker_result(
            self._application.custom_style_messages, 10
        )
        self._application._reload_style_catalog()
        result["catalog"] = self._application.settings.get("styles", [])
        return result

    def _select_file(self, file_types):
        """通过 pywebview 原生文件选择器选择单个文件。"""
        import webview

        window = getattr(self._application, "webview_window", None)
        if window is None:
            raise RuntimeError("界面窗口尚未就绪")
        dialog_enum = getattr(webview, "FileDialog", None)
        dialog_type = (
            dialog_enum.OPEN
            if dialog_enum is not None
            else webview.OPEN_DIALOG
        )
        result = window.create_file_dialog(
            dialog_type,
            allow_multiple=False,
            file_types=file_types,
        )
        return result[0] if result else None

    def _select_directory(self):
        """通过 pywebview 原生目录选择器选择单个文件夹。"""
        import webview

        window = getattr(self._application, "webview_window", None)
        if window is None:
            raise RuntimeError("界面窗口尚未就绪")
        dialog_enum = getattr(webview, "FileDialog", None)
        dialog_type = (
            dialog_enum.FOLDER
            if dialog_enum is not None
            else webview.FOLDER_DIALOG
        )
        result = window.create_file_dialog(dialog_type, allow_multiple=False)
        if isinstance(result, str):
            return result
        return result[0] if result else None

    def _style_upload(self, payload):
        """选择、校验并上传一个自定义屏幕样式文件。"""
        path = self._select_file(("Python 样式文件 (*.py)",))
        if not path:
            return {"cancelled": True}
        self._drain_queue(self._application.custom_style_upload_messages)
        validated = self._application.request_custom_style_upload(
            path,
            set(payload.get("existingNames") or ()),
            bool(payload.get("overwrite")),
        )
        result = self._wait_worker_result(
            self._application.custom_style_upload_messages, 90
        )
        result["filename"] = validated.filename
        self._application._reload_style_catalog()
        return result

    def _style_delete(self, payload):
        """删除设备中的指定自定义屏幕样式。"""
        self._drain_queue(self._application.custom_style_delete_messages)
        self._application.request_custom_style_delete(
            str(payload.get("name") or ""),
            str(payload.get("filename") or ""),
        )
        return self._wait_worker_result(
            self._application.custom_style_delete_messages, 30
        )

    def _custom_data_list(self, payload):
        """返回自定义数据插件、运行状态和加载错误。"""
        del payload
        manager = custom_data.get_manager()
        states, errors = manager.list_items()
        items = []
        for state in states:
            definition = state.definition
            items.append(
                {
                    "name": definition.name,
                    "key": definition.key,
                    "taskName": definition.task_name,
                    "chineseName": definition.zh_name,
                    "interval": definition.interval,
                    "path": str(definition.plugin_directory),
                    "environment": manager.environment_status(definition),
                    "enabled": bool(state.runtime_enabled),
                    "error": state.error or state.environment_error,
                }
            )
        return {
            "items": items,
            "errors": [
                {"path": str(path), "message": str(error)}
                for path, error in errors.items()
            ],
        }

    def _custom_data_import(self, payload):
        """选择 ZIP 插件包并导入自定义数据插件。"""
        path = (
            str(payload.get("sourcePath") or "").strip()
            if payload.get("overwrite")
            else self._select_file(("自定义数据插件 (*.zip)",))
        )
        if not path:
            return {"cancelled": True}
        return self._import_custom_data_source(path, payload)

    def _custom_data_import_directory(self, payload):
        """选择包含 plugin.json 的本地目录并导入自定义数据插件。"""
        path = (
            str(payload.get("sourcePath") or "").strip()
            if payload.get("overwrite")
            else self._select_directory()
        )
        if not path:
            return {"cancelled": True}
        return self._import_custom_data_source(path, payload)

    @staticmethod
    def _import_custom_data_source(path, payload):
        """导入指定插件来源，并把重复冲突转换为可确认的界面结果。"""
        manager = custom_data.get_manager()
        try:
            definition = manager.import_plugin(path, bool(payload.get("overwrite")))
        except custom_data.CustomDataDuplicateError as error:
            return {
                "requiresOverwrite": True,
                "message": str(error),
                "sourcePath": str(path),
                "conflicts": [
                    {
                        "name": conflict.zh_name,
                        "key": conflict.key,
                        "taskName": conflict.task_name,
                    }
                    for conflict in error.conflicts
                ],
            }
        return {"name": definition.name, "chineseName": definition.zh_name}

    def _custom_data_activate(self, payload):
        """激活指定插件并同步通知后台工作进程。"""
        name = str(payload.get("name") or "")
        custom_data.get_manager().activate_plugin(name)
        applied = self._application._activate_custom_data_plugin(name)
        return {"activated": True, "applied": applied}

    def _custom_data_install_dependencies(self, payload):
        """创建指定插件的独立环境并安装依赖。"""
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("缺少插件名称")
        logs = []

        def append_log(message):
            """收集环境安装进度，并同步写入应用日志。"""
            text = str(message)
            logs.append(text)
            LOGGER.info("自定义数据环境安装：插件=%s，%s", name, text)

        status = custom_data.get_manager().install_dependencies(name, append_log)
        return {"status": status, "output": "\n".join(logs)}

    def _custom_data_test(self, payload):
        """测试执行指定自定义数据插件。"""
        result = custom_data.get_manager().test_plugin(
            str(payload.get("name") or "")
        )
        return {"output": result}

    def _custom_data_delete(self, payload):
        """删除指定自定义数据插件目录和独立环境。"""
        custom_data.get_manager().delete_plugin(str(payload.get("path") or ""))
        return {"deleted": True}

    def _read_log(self, payload):
        """读取最近日志并按 UTF-8 解码。"""
        maximum = min(max(int(payload.get("maximum", 300000)), 1000), 1048576)
        return {
            "content": self._application._read_recent_log(maximum).decode(
                "utf-8", errors="replace"
            )
        }

    def _clear_log(self, payload):
        """清空应用运行日志。"""
        del payload
        self._application._clear_log()
        return {"cleared": True}

    def _export_log(self, payload):
        """导出包含脱敏配置快照的日志。"""
        del payload
        path = self._application._export_log(self._application.icon)
        return {"path": str(path)}

    def _open_data_directory(self, payload):
        """使用资源管理器打开用户数据目录。"""
        del payload
        self._application.data_directory.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(
            ["explorer.exe", str(self._application.data_directory)],
            creationflags=0x08000000,
        )
        return {"opened": True}


class WebUiMixin:
    """把原有多个 Tk 窗口替换为单一 pywebview Vue 应用。"""

    def _prepare_webview_icon(self):
        """将统一 PNG 应用图标转换为 Windows WebView 可识别的 ICO。"""
        from PIL import Image

        source_path = self._resource_path("icon", "icon.png")
        target_path = self.data_directory / "icon.ico"
        icon_sizes = (
            (16, 16),
            (24, 24),
            (32, 32),
            (48, 48),
            (64, 64),
            (128, 128),
            (256, 256),
        )
        with Image.open(source_path) as source_image:
            source_image.convert("RGBA").save(
                target_path,
                format="ICO",
                sizes=icon_sizes,
            )
        return target_path

    def _initialize_webview(self):
        """在主线程创建常驻隐藏窗口，保证 Windows GUI 消息循环合法。"""
        import webview

        entry = self._resource_path("win", "ui-web", "dist", "index.html")
        if not entry.is_file():
            raise FileNotFoundError("Web 界面构建产物不存在：{}".format(entry))
        bridge = WebViewBridge(self)
        window = webview.create_window(
            "{} — 控制中心".format(APPLICATION_NAME),
            entry.resolve().as_uri(),
            js_api=bridge,
            width=1120,
            height=760,
            min_size=(920, 640),
            background_color="#0b1020",
            confirm_close=False,
            hidden=True,
        )

        def hide_instead_of_closing():
            """把用户关闭操作转换为隐藏，保持托盘和主 GUI 循环运行。"""
            if self.stopping.is_set():
                return True
            window.hide()
            return False

        window.events.closing += hide_instead_of_closing
        self.webview_window = window
        self.settings_window = window
        return window

    def _start_webview_loop(self):
        """使用统一应用图标启动 Edge WebView2 消息循环。"""
        import webview

        webview.start(
            gui="edgechromium",
            debug=False,
            private_mode=False,
            icon=str(self._prepare_webview_icon()),
        )

    def _show_web_page(self, page="settings"):
        """恢复常驻 Web 窗口并导航到指定页面。"""
        window = getattr(self, "webview_window", None)
        if window is None:
            if self.icon is not None:
                self.icon.notify("界面尚未就绪，请稍后重试", APPLICATION_NAME)
            return
        try:
            window.evaluate_js(
                "window.dispatchEvent(new CustomEvent('omniwatch:navigate',"
                " {detail: %s}))" % json.dumps(page)
            )
            window.show()
            window.restore()
        except Exception as error:
            LOGGER.exception("恢复 Web 界面失败：%s", error)
            if self.icon is not None:
                self.icon.notify("界面恢复失败：{}".format(error), APPLICATION_NAME)

    def _show_settings(self, icon=None, item=None):
        """打开 Web 设置页。"""
        del icon, item
        self._show_web_page("settings")

    def _show_device_probe(self, icon=None, item=None):
        """打开 Web 设备管理页。"""
        del icon, item
        self._show_web_page("device")

    def _show_custom_style(self, icon=None, item=None):
        """打开 Web 屏幕样式页。"""
        del icon, item
        self._show_web_page("styles")

    def _show_custom_data(self, icon=None, item=None):
        """打开 Web 自定义数据页。"""
        del icon, item
        self._show_web_page("data")

    def _show_log(self, icon=None, item=None):
        """打开 Web 日志页。"""
        del icon, item
        self._show_web_page("logs")

    def _show_about(self, icon=None, item=None):
        """打开 Web 关于页。"""
        del icon, item
        self._show_web_page("about")
