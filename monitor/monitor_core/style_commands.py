"""Pico 样式、截图与热配置命令处理。"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import serial

from .console import configure_logging

LOGGER = logging.getLogger("pico-monitor")
BUILTIN_LCD_STYLES = (
    "default", "disk", "diskv2", "diskv3", "diskv4", "horizontal_disk",
    "horizontal_diskv2", "horizontal_disk4x", "horizontal_disk4x_qb",
    "horizontal_disk6x", "simple", "fpstest", "fps_simple", "game",
)


class StyleCommandMixin:
    """提供样式管理、截图和运行时显示配置能力。"""

    def _synchronize_style_catalog(self):
        """接收 Pico 样式清单并更新 monitor 的 JSON 配置文件。"""
        catalog = getattr(self.client, "styles", None) or []
        if not catalog:
            return
        names = set(BUILTIN_LCD_STYLES)
        names.update({
            item.get("name") for item in catalog
            if isinstance(item, dict) and item.get("name")
        })
        if not names:
            return
        self.available_styles = names
        settings_path = os.getenv("PICO_MONITOR_SETTINGS_PATH")
        if settings_path:
            from win.settings import TraySettingsStore, normalize_style_catalog

            normalized = normalize_style_catalog(catalog)
            if normalized:
                store = TraySettingsStore(settings_path)
                settings = store.load()
                settings["styles"] = normalized
                if settings["lcd_style"] not in names:
                    settings["lcd_style"] = normalized[0]["name"]
                    self.arguments.lcd_style = settings["lcd_style"]
                store.save(settings)
        LOGGER.info("STYLE_CATALOG_UPDATED：已同步 %d 个 Pico 样式", len(names))

    def request_reboot_and_stop(self):
        """让主循环退出，并在释放串口前请求 Pico 重启。"""
        LOGGER.info("收到托盘退出请求，将在停止监控前重启 Pico")
        self.reboot_requested.set()
        self.stopping.set()

    def request_custom_style_catalog(self):
        """安排主循环在当前串口交互结束后查询自定义样式。"""
        self.custom_style_catalog_requested.set()

    def request_screenshot(self):
        """安排主循环在当前串口交互完成后截取 LCD 画面。"""
        self.screenshot_requested.set()

    def _publish_screenshot(self):
        """接收 Pico 截图、转换为 PNG，并把保存结果输出给托盘。"""
        self.screenshot_requested.clear()
        try:
            from PIL import Image

            metadata, pixels = self.client.screenshot()
            width = int(metadata["width"])
            height = int(metadata["height"])
            # Pillow 的 BGR;16 解码器读取小端 RGB565，Pico 回传的是 LCD 使用的
            # 大端字节序，因此先按像素交换高低字节再生成 PNG。
            little_endian_pixels = bytearray(len(pixels))
            little_endian_pixels[0::2] = pixels[1::2]
            little_endian_pixels[1::2] = pixels[0::2]
            image = Image.frombytes(
                "RGB", (width, height), bytes(little_endian_pixels), "raw", "BGR;16"
            )
            screenshot_directory = Path(
                os.getenv("PICO_MONITOR_SCREENSHOT_DIR", Path.cwd() / "screenshot")
            )
            screenshot_directory.mkdir(parents=True, exist_ok=True)
            path = screenshot_directory / datetime.now().strftime(
                "screenshot_%Y%m%d_%H%M%S_%f.png"
            )
            image.save(path, "PNG")
            result = {"status": "ok", "path": str(path.resolve())}
        except (KeyError, OSError, RuntimeError, ValueError, serial.SerialException) as error:
            result = {"status": "error", "message": str(error)}
        print(
            "SCREENSHOT_RESULT:"
            + json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            flush=True,
        )

    def _publish_custom_style_catalog(self):
        """通过 Pico 指令查询自定义样式并输出给托盘进程。"""
        self.custom_style_catalog_requested.clear()
        try:
            catalog = self.client.request_style_catalog_info()
            result = {
                "status": "ok",
                "styles": catalog["styles"],
                "flash": catalog["flash"],
            }
        except (OSError, RuntimeError, serial.SerialException) as error:
            result = {"status": "error", "message": str(error), "styles": []}
        print(
            "CUSTOM_STYLE_LIST_RESULT:"
            + json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            flush=True,
        )

    def request_custom_style_upload(self, payload):
        """安排主循环在串口空闲时上传一个已校验的自定义样式。"""
        self.custom_style_uploads.put(dict(payload))

    def _publish_custom_style_upload(self):
        """执行待处理的自定义样式上传并向托盘输出结构化结果。"""
        payload = self.custom_style_uploads.get_nowait()
        try:
            import base64

            content = base64.b64decode(payload["content"], validate=True)
            data = self.client.upload_style(
                payload["filename"],
                payload["style_name"],
                content,
                overwrite=payload.get("overwrite") is True,
            )
            result = {"status": "ok", "data": data}
            self.client.styles = self.client.request_style_catalog()
            self._synchronize_style_catalog()
        except (KeyError, ValueError, OSError, RuntimeError, serial.SerialException) as error:
            result = {"status": "error", "message": str(error)}
        print(
            "CUSTOM_STYLE_UPLOAD_RESULT:"
            + json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            flush=True,
        )

    def request_custom_style_delete(self, payload):
        """安排主循环删除指定自定义样式。"""
        self.custom_style_deletes.put(dict(payload))

    def _publish_custom_style_delete(self):
        """删除 Pico 自定义样式并向托盘发布重启状态。"""
        payload = self.custom_style_deletes.get_nowait()
        try:
            data = self.client.delete_style(
                payload["filename"], payload["style_name"],
            )
            result = {"status": "ok", "data": data}
        except (KeyError, ValueError, OSError, RuntimeError, serial.SerialException) as error:
            result = {"status": "error", "message": str(error)}
        print(
            "CUSTOM_STYLE_DELETE_RESULT:"
            + json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            flush=True,
        )
        if result["status"] == "ok":
            # Pico 已由删除命令复位，关闭旧串口以立即进入 PONG 重连流程。
            self.client.close()

    def apply_display_config(self, payload):
        """校验并热更新 Windows 托盘下发的显示配置。"""
        brightness = int(payload.get("lcd_brightness", self.arguments.lcd_brightness))
        rotation = int(payload.get("screen_rotation", self.arguments.screen_rotation))
        style = payload.get("lcd_style", self.arguments.lcd_style)
        network_unit = payload.get("network_unit", self.arguments.network_unit)
        if not 1 <= brightness <= 100:
            raise ValueError("LCD 背光亮度必须为 1 至 100")
        if rotation not in (0, 180):
            raise ValueError("屏幕旋转角度仅支持 0 或 180")
        if style not in self.available_styles:
            raise ValueError("不支持的 LCD 样式")
        if network_unit not in ("MB", "Mbps"):
            raise ValueError("不支持的网络速率单位")
        self.arguments.lcd_brightness = brightness
        self.arguments.screen_rotation = rotation
        self.arguments.lcd_style = style
        self.arguments.network_unit = network_unit
        LOGGER.info(
            "显示设置已热更新：亮度=%d%%，旋转=%d°，样式=%s，网络单位=%s",
            brightness, rotation, style, network_unit,
        )

    def apply_dev_config(self, payload):
        """热更新开发模式开关，不重启 Monitor 工作进程。"""
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError("开发模式开关必须为布尔值")
        self.arguments.dev = enabled
        configure_logging("DEBUG" if enabled else self.arguments.log_level)
        LOGGER.info("开发模式已热更新：%s", "开启" if enabled else "关闭")

    def stop(self, signum=None, frame=None):
        """请求主循环停止，由通信线程在退出阶段统一关闭串口。"""
        del signum, frame
        LOGGER.info("收到停止请求，正在关闭监控程序")
        # Windows 的 PySerial 正在 ReadFile 时不能由其他线程执行 close，
        # 否则内部 OVERLAPPED 事件会被置空并触发 ctypes.byref(None) 异常。
        self.stopping.set()

