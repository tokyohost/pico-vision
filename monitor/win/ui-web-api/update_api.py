"""Web 界面的应用、固件和 SDK 在线更新接口。"""

import logging
import sys
import threading

from build_info import GITHUB_REPOSITORY, MONITOR_VERSION
from sdk_flash import inspect_sdk_image
from windows_update import WindowsReleaseUpdater

from .config import SDK_RELEASE_REPOSITORY


LOGGER = logging.getLogger("pico-monitor.web-ui")


def _inspect_sdk_image(path):
    """调用 SDK 镜像检查器，并兼容旧入口上的测试替换。"""
    facade_name = __package__.rsplit(".", 1)[0] + ".ui_web"
    facade = sys.modules.get(facade_name)
    checker = getattr(facade, "inspect_sdk_image", inspect_sdk_image)
    return checker(path)


class UpdateApiMixin:
    """处理在线版本检查、下载、安装和进度查询。"""

    __slots__ = ()

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

    def _run_firmware_release_update(self, updater, asset, latest_version, port):
        """下载并安装设备固件发布包，结束后恢复常驻监控。"""
        package_path = None
        try:
            self._set_update_state(
                "firmware", "running", 10, "正在下载设备固件", True
            )
            package_path = updater.download(asset, ".zip")
            self._set_update_state("firmware", "running", 45, "固件下载完成，正在暂停监控")
            self._application._stop_worker()
            self._set_update_state("firmware", "running", 50, "正在通过 mpremote 更新设备固件")

            def report_progress(message, percent):
                """把 mpremote 的逐行输出和字节进度同步到 Web 更新页。"""
                progress = None if percent is None else 50 + int(percent * 0.45)
                self._set_update_state("firmware", "running", progress, message)

            self._application._upgrade_pico_from_package(
                package_path, port, report_progress
            )
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
            try:
                if not self._application.stopping.is_set() and (
                    self._application.worker_process is None
                    or self._application.worker_process.poll() is not None
                ):
                    self._application._start_worker()
            except Exception as error:
                LOGGER.exception("在线固件更新后恢复后台监控失败：%s", error)
                self._set_update_state(
                    "firmware",
                    "error",
                    None,
                    "固件更新结束，但恢复后台监控失败：{}".format(error),
                )
            finally:
                self._application.update_lock.release()

    def _run_sdk_release_update(self, updater, asset, connection):
        """下载 SDK 发布镜像并通过受控 USB 模式立即刷写。"""
        image_path = None
        delegated = False
        try:
            self._set_update_state("sdk", "running", 10, "正在下载 SDK 镜像", True)
            image_path = updater.download(asset, ".bin")
            self._set_update_state("sdk", "running", 30, "SDK 镜像下载完成，正在校验")
            information = _inspect_sdk_image(image_path)
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
                port = self._application._mpremote_repl_port(connection)
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
                arguments = (updater, asset, latest_version, port)
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

