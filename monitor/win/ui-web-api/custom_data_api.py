"""Web 界面的自定义数据插件管理接口。"""

import base64
import logging
import mimetypes

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

    def _custom_data_delete(self, payload):
        """删除指定自定义数据插件目录和独立环境。"""
        custom_data.get_manager().delete_plugin(str(payload.get("path") or ""))
        return {"deleted": True}
