#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.

"""封装 Pico 的 Wi-Fi、重启、截图和自定义样式业务命令。"""

import base64
import json
import logging
import time


STYLE_UPLOAD_CHUNK_SIZE = 512
LOGGER = logging.getLogger("pico-monitor.serial")


class PicoCommandMixin:
    """为 Pico 客户端提供面向业务的设备命令。"""

    def request_wifi_list(self, timeout=20.0):
        """请求设备扫描附近 Wi-Fi 并返回网络列表和当前状态。"""
        request_id = "wifi-list-{}".format(int(time.monotonic() * 1000))
        packet = self.build_command_packet("wifi.list", request_id=request_id)
        self._write_packet(packet, "Wi-Fi 搜索")
        return self._wait_command_result(request_id, timeout, "Wi-Fi 搜索", "Wi-Fi 搜索失败")

    def set_wifi(self, ssid, password="", timeout=20.0):
        """请求设备连接指定 Wi-Fi，并返回明确的成功或失败结果。"""
        request_id = "wifi-set-{}".format(int(time.monotonic() * 1000))
        packet = self.build_command_packet(
            "wifi.set",
            params={"ssid": ssid, "password": password, "timeout_ms": int(timeout * 1000)},
            request_id=request_id,
        )
        self._write_packet(packet, "Wi-Fi 连接")
        return self._wait_command_result(request_id, timeout + 2.0, "Wi-Fi 连接", "Wi-Fi 连接失败")

    def forget_wifi(self, ssid, timeout=10.0):
        """请求设备忘记指定的已保存 Wi-Fi。"""
        request_id = "wifi-forget-{}".format(int(time.monotonic() * 1000))
        packet = self.build_command_packet(
            "wifi.forget",
            params={"ssid": ssid},
            request_id=request_id,
        )
        self._write_packet(packet, "忘记 Wi-Fi")
        return self._wait_command_result(request_id, timeout, "忘记 Wi-Fi", "忘记 Wi-Fi 失败")

    def request_websocket_clients(self, timeout=5.0):
        """请求设备返回曾连接的 WebSocket 客户端清单。"""
        request_id = "websocket-clients-{}".format(int(time.monotonic() * 1000))
        packet = self.build_command_packet(
            "websocket.clients.list",
            request_id=request_id,
        )
        self._write_packet(packet, "WebSocket 客户端清单")
        return self._wait_command_result(
            request_id,
            timeout,
            "WebSocket 客户端清单",
            "WebSocket 客户端清单查询失败",
        )

    def update_websocket_client(self, client_id, enabled=None, priority=None, timeout=5.0):
        """请求设备修改 WebSocket 客户端的启用状态或优先级。"""
        params = {"id": str(client_id)}
        if enabled is not None:
            params["enabled"] = bool(enabled)
        if priority is not None:
            params["priority"] = int(priority)
        request_id = "websocket-client-update-{}".format(int(time.monotonic() * 1000))
        packet = self.build_command_packet(
            "websocket.client.update",
            params=params,
            request_id=request_id,
        )
        self._write_packet(packet, "WebSocket 客户端策略")
        return self._wait_command_result(
            request_id,
            timeout,
            "WebSocket 客户端策略",
            "WebSocket 客户端策略更新失败",
        )

    def reboot(self, timeout=30.0):
        """请求 Pico 执行软重启，并在指定秒数内等待设备确认。"""
        if not self.is_connected:
            raise RuntimeError("Pico 串口尚未连接")
        LOGGER.info("[Monitor -> Pico][%s][命令 reboot]", self.port_name)
        packet = self.build_command_packet("reboot", request_id="reboot")
        self._write_packet(packet, "reboot")
        deadline = time.monotonic() + max(0.1, float(timeout))
        while time.monotonic() < deadline:
            frame = self._read_protocol_frame("reboot")
            if frame and frame[0] == "COMMAND":
                result = json.loads(frame[1].decode("utf-8"))
                if result.get("command") == "reboot" and result.get("status") == "ok":
                    LOGGER.info("[Pico -> Monitor][%s][命令成功 reboot]", self.port_name)
                    return
            if frame and frame[0] == "ERR":
                raise RuntimeError(frame[1].decode("utf-8", errors="replace"))
        raise RuntimeError("设备无响应，请重新拔插设备注册")

    def screenshot(self, timeout=30.0):
        """请求 Pico 分块返回 LCD 画面，并重组为大端 RGB565 数据。"""
        if not self.is_connected:
            raise RuntimeError("Pico 串口尚未连接")
        request_id = "screenshot-{}".format(int(time.time() * 1000))
        packet = self.build_command_packet("screenshot", request_id=request_id)
        self._write_packet(packet, "screenshot")
        chunks = {}
        deadline = time.monotonic() + max(0.1, float(timeout))
        while time.monotonic() < deadline:
            frame = self._read_protocol_frame("screenshot")
            if not frame or frame[0] != "COMMAND":
                if frame and frame[0] == "ERR":
                    raise RuntimeError(frame[1].decode("utf-8", errors="replace"))
                continue
            result = json.loads(frame[1].decode("utf-8"))
            if result.get("request_id") != request_id:
                continue
            if result.get("status") == "chunk":
                data = result.get("data") or {}
                sequence = int(data["sequence"])
                chunks[sequence] = base64.b64decode(data["pixels"], validate=True)
                continue
            if result.get("status") != "ok":
                raise RuntimeError(result.get("error") or "Pico 截图失败")
            metadata = result.get("data") or {}
            expected_chunks = int(metadata.get("chunks", 0))
            if sorted(chunks) != list(range(expected_chunks)):
                raise RuntimeError("Pico 截图数据不完整")
            pixels = b"".join(chunks[index] for index in range(expected_chunks))
            expected_bytes = int(metadata["width"]) * int(metadata["height"]) * 2
            if len(pixels) != expected_bytes:
                raise RuntimeError("Pico 截图像素长度不正确")
            return metadata, pixels
        raise RuntimeError("等待 Pico 截图响应超时")

    def request_style_catalog_info(self, timeout=5.0):
        """请求 Pico 返回自定义样式清单及 Flash 空间信息。"""
        if not self.is_connected:
            raise RuntimeError("Pico 串口尚未连接")
        request_id = "style-list-{}".format(int(time.time() * 1000))
        build_started = time.monotonic()
        packet = self.build_command_packet("style.list", request_id=request_id)
        build_elapsed_ms = (time.monotonic() - build_started) * 1000
        LOGGER.info(
            "[样式清单][%s] request_id=%s，命令帧=%d 字节，timeout=%.1f 秒",
            self.port_name,
            request_id,
            len(packet),
            timeout,
        )
        self._write_packet(packet, "style.list", build_elapsed_ms)
        result = self._wait_command_result(request_id, timeout, "style.list", "样式清单查询失败")
        data = result.get("data") or {}
        styles = data.get("styles", [])
        flash = data.get("flash") or {}
        return {
            "styles": [item for item in styles if isinstance(item, dict)],
            "flash": {
                "free_bytes": max(0, int(flash.get("free_bytes", 0))),
                "total_bytes": max(0, int(flash.get("total_bytes", 0))),
            },
        }

    def request_style_catalog(self, timeout=5.0):
        """请求 Pico 返回自定义样式清单并保持原有列表返回格式。"""
        return self.request_style_catalog_info(timeout)["styles"]

    def delete_style(self, filename, style_name, timeout=5.0):
        """请求 Pico 删除一个自定义样式文件并重启设备。"""
        if not self.is_connected:
            raise RuntimeError("Pico 串口尚未连接")
        request_id = "style-delete-{}".format(int(time.time() * 1000))
        packet = self.build_command_packet(
            "style.delete",
            params={"filename": filename, "style_name": style_name},
            request_id=request_id,
        )
        self._write_packet(packet, "style.delete")
        result = self._wait_command_result(
            request_id,
            timeout,
            "style.delete",
            "自定义样式删除失败",
        )
        return result.get("data") or {}

    def upload_style(self, filename, style_name, content, timeout=10.0, overwrite=False):
        """把样式源码分块写入 Pico 的 Flash 临时文件并完成校验。"""
        if not self.is_connected:
            raise RuntimeError("Pico 串口尚未连接")
        upload_id = filename
        request_prefix = "style-upload-{}".format(int(time.time() * 1000))
        LOGGER.info(
            "[样式上传][%s] filename=%s，style_name=%s，原始=%d 字节，分块=%d 字节，request_id=%s，timeout=%.1f 秒",
            self.port_name,
            filename,
            style_name,
            len(content),
            STYLE_UPLOAD_CHUNK_SIZE,
            request_prefix,
            timeout,
        )
        self._send_style_upload_action(
            request_prefix + "-begin",
            {
                "action": "begin",
                "filename": filename,
                "style_name": style_name,
                "size": len(content),
                "overwrite": bool(overwrite),
            },
            timeout,
            "begin",
        )
        try:
            for sequence, offset in enumerate(range(0, len(content), STYLE_UPLOAD_CHUNK_SIZE)):
                chunk = content[offset:offset + STYLE_UPLOAD_CHUNK_SIZE]
                self._send_style_upload_action(
                    request_prefix + "-data-{}".format(sequence),
                    {
                        "action": "data",
                        "upload_id": upload_id,
                        "sequence": sequence,
                        "content": base64.b64encode(chunk).decode("ascii"),
                    },
                    timeout,
                    "data-{}".format(sequence),
                )
            result = self._send_style_upload_action(
                request_prefix + "-finish",
                {"action": "finish", "upload_id": upload_id},
                timeout,
                "finish",
            )
            return result.get("data") or {}
        except Exception:
            try:
                self._send_style_upload_action(
                    request_prefix + "-abort",
                    {"action": "abort", "upload_id": upload_id},
                    min(timeout, 2.0),
                    "abort",
                )
            except Exception:
                LOGGER.warning("[样式上传][%s] Flash 临时文件清理请求失败", self.port_name)
            raise

    def _send_style_upload_action(self, request_id, params, timeout, action):
        """发送一个低内存占用的样式上传动作并等待 Pico 确认。"""
        build_started = time.monotonic()
        packet = self.build_command_packet("uploadStyle", params=params, request_id=request_id)
        build_elapsed_ms = (time.monotonic() - build_started) * 1000
        label = "uploadStyle." + action
        self._write_packet(packet, label, build_elapsed_ms)
        return self._wait_command_result(request_id, timeout, label, "自定义样式上传失败")
