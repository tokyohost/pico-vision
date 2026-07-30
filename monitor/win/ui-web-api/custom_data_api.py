"""Web 界面的自定义数据插件管理接口。"""

import base64
import json
import logging
import mimetypes
import queue

import custom_data


LOGGER = logging.getLogger("pico-monitor.web-ui")


class CustomDataApiMixin:
    """处理自定义数据插件的完整生命周期。"""

    __slots__ = ()

    def _custom_data_list(self, payload):
        """返回自定义数据插件、运行状态和加载错误。"""
        del payload
        manager = custom_data.get_manager()
        states, errors = manager.list_items()
        items = []
        for state in states:
            definition = state.definition
            preview_data_url = ""
            if definition.preview_path:
                mime_type = mimetypes.guess_type(definition.preview_path.name)[0] or "image/png"
                preview_data_url = "data:{};base64,{}".format(
                    mime_type,
                    base64.b64encode(definition.preview_path.read_bytes()).decode("ascii"),
                )
            items.append(
                {
                    "name": definition.name,
                    "key": definition.key,
                    "version": definition.version,
                    "taskName": definition.task_name,
                    "chineseName": definition.zh_name,
                    "interval": definition.interval,
                    "boundStyle": definition.style_filename,
                    "hasDetail": bool(definition.detail_path),
                    "detailFilename": definition.detail_filename,
                    "previewFilename": definition.preview_filename,
                    "previewDataUrl": preview_data_url,
                    "path": str(definition.plugin_directory),
                    "environment": manager.environment_status(definition),
                    "enabled": bool(
                        self._application.settings.get(
                            "custom_data_enabled", {}
                        ).get(definition.name, state.runtime_enabled)
                    ),
                    "hasUninstall": definition.has_uninstall,
                    "hasActions": bool(definition.actions),
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
            else self._select_file(("插件包 (*.zip)",))
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

    def _import_custom_data_source(self, path, payload):
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
        enabled = dict(
            custom_data.normalize_plugin_enabled(
                self._application.settings.get("custom_data_enabled")
            )
        )
        enabled[definition.name] = False
        self._application.settings["custom_data_enabled"] = enabled
        self._application.settings["custom_data_configs"] = (
            custom_data.normalize_plugin_configs(
                self._application.settings.get("custom_data_configs")
            )
        )
        self._application.settings_store.save(self._application.settings)
        return {"name": definition.name, "chineseName": definition.zh_name}

    def _custom_data_activate(self, payload):
        """兼容旧界面激活动作，并转为持久启用状态。"""
        result = self._custom_data_set_enabled(
            {"name": payload.get("name"), "enabled": True}
        )
        return {"activated": True, "applied": True, **result}

    def _custom_data_set_enabled(self, payload):
        """持久化指定插件启用状态并热更新 Monitor 采集任务。"""
        name = str(payload.get("name") or "").strip()
        enabled = bool(payload.get("enabled"))
        definitions = {
            definition.name: definition
            for definition in custom_data.get_manager().list_definitions()
        }
        if name not in definitions:
            raise ValueError("插件不存在或尚未加载")
        states = dict(
            custom_data.normalize_plugin_enabled(
                self._application.settings.get("custom_data_enabled")
            )
        )
        states[name] = enabled
        self._application.settings["custom_data_enabled"] = states
        self._application.settings_store.save(self._application.settings)
        custom_data.get_manager().set_plugin_enabled(name, enabled)
        if not self._application._apply_runtime_settings(wait=True):
            raise RuntimeError("后台监控未运行，启用状态将在下次启动时生效")
        return {"name": name, "enabled": enabled}

    def _custom_data_invoke_action(self, payload):
        """调用插件清单公开动作，并返回受校验的配置补丁。"""
        name = str(payload.get("name") or "").strip()
        action = str(payload.get("action") or "").strip()
        config = payload.get("config")
        if not isinstance(config, dict):
            raise ValueError("插件动作缺少有效配置快照")
        return custom_data.get_manager().invoke_action(name, action, config)

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

    def _custom_data_detail(self, payload):
        """读取指定插件绑定的 UTF-8 HTML 简介。"""
        name = str(payload.get("name") or "").strip()
        definitions = {
            definition.name: definition
            for definition in custom_data.get_manager().list_definitions()
        }
        definition = definitions.get(name)
        if definition is None:
            raise ValueError("插件不存在或尚未加载")
        if not definition.detail_path:
            raise ValueError("该插件没有绑定简介 HTML")
        return {
            "title": "{} · 插件简介".format(definition.zh_name),
            "content": definition.detail_path.read_text(encoding="utf-8-sig"),
        }

    def _custom_data_sync_style(self, payload):
        """校验插件绑定样式并将其同步到当前连接设备。"""
        name = str(payload.get("name") or "").strip()
        definitions = {
            definition.name: definition
            for definition in custom_data.get_manager().list_definitions()
        }
        definition = definitions.get(name)
        if definition is None:
            raise ValueError("插件不存在或尚未加载")
        if not definition.bind_style or not definition.style_path:
            raise ValueError("该插件没有绑定可同步的屏幕样式")
        existing_names = {
            str(item.get("name") or "")
            for item in self._application.settings.get("styles", ())
            if isinstance(item, dict) and item.get("type") == "custom"
        }
        self._drain_queue(self._application.custom_style_upload_messages)
        validated = self._application.request_custom_style_upload(
            str(definition.style_path),
            existing_names,
            bool(payload.get("overwrite")),
        )
        result = self._wait_worker_result(
            self._application.custom_style_upload_messages, 90
        )
        result["filename"] = validated.filename
        self._application._reload_style_catalog()
        result["catalog"] = self._application.settings.get("styles", [])
        return result

    def _custom_data_sync_style_progress(self, payload):
        """返回绑定样式上传期间设备已确认的最新发送进度。"""
        del payload
        active = self._application.custom_style_upload_active.is_set()
        progresses = []
        while True:
            try:
                line = self._application.custom_style_upload_logs.get_nowait()
            except queue.Empty:
                break
            if not line.startswith("CUSTOM_STYLE_UPLOAD_PROGRESS:"):
                continue
            if not active:
                continue
            try:
                progresses.append(
                    json.loads(line.split(":", 1)[1])
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                LOGGER.warning("忽略无法解析的样式上传进度：%s", line)
        return {
            "active": active,
            "progresses": progresses,
        }

    def _custom_data_delete(self, payload):
        """执行插件卸载钩子并删除插件目录和独立环境。"""
        manager = custom_data.get_manager()
        path = str(payload.get("path") or "")
        definitions = {
            str(definition.plugin_directory): definition
            for definition in manager.list_definitions()
        }
        definition = definitions.get(path)
        if definition is None:
            raise ValueError("插件不存在或尚未加载")
        configs = self._application.settings.get("custom_data_configs", {})
        enabled = dict(self._application.settings.get("custom_data_enabled", {}))
        was_enabled = bool(enabled.get(definition.name, True))
        enabled[definition.name] = False
        self._application.settings["custom_data_enabled"] = enabled
        applied = self._application._apply_runtime_settings(wait=True)
        process = getattr(self._application, "worker_process", None)
        if (
            not applied
            and process is not None
            and process.poll() is None
        ):
            raise RuntimeError("无法确认后台采集任务已停止，已取消删除")
        try:
            manager.set_plugin_enabled(definition.name, False)
            manager.delete_plugin(path, configs.get(definition.name, {}))
        except Exception:
            enabled[definition.name] = was_enabled
            self._application.settings["custom_data_enabled"] = enabled
            manager.set_plugin_enabled(definition.name, was_enabled)
            self._application._apply_runtime_settings(wait=False)
            raise
        configs = dict(configs)
        enabled.pop(definition.name, None)
        configs.pop(definition.name, None)
        self._application.settings["custom_data_enabled"] = enabled
        self._application.settings["custom_data_configs"] = configs
        self._application.settings_store.save(self._application.settings)
        self._application._apply_runtime_settings(wait=False)
        return {"deleted": True}
