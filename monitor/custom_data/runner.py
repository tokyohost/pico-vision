#!/usr/bin/env python3
"""作为隔离子进程入口加载自定义数据插件并输出协议 JSON。"""

import importlib.util
import contextlib
import json
import sys
import traceback
from pathlib import Path


def _configure_standard_streams():
    """将插件协议标准输入输出统一为 UTF-8，避免 Windows 默认 GBK 导致中文乱码。"""
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _load_module(script_path):
    """从指定入口文件加载插件模块。"""
    plugin_directory = str(Path(script_path).resolve().parent)
    if plugin_directory not in sys.path:
        sys.path.insert(0, plugin_directory)
    specification = importlib.util.spec_from_file_location("omniwatch_custom_data_plugin", script_path)
    if specification is None or specification.loader is None:
        raise RuntimeError("无法加载插件入口模块")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _load_plugin(script_path):
    """加载插件模块并校验必需的 collect 方法。"""
    with contextlib.redirect_stdout(sys.stderr):
        module = _load_module(script_path)
        collect = getattr(module, "collect", None)
        if not callable(collect):
            raise RuntimeError("插件入口必须定义 collect() 方法")
    return module


def _collect(collect, config_json):
    """执行已加载的 collect 方法并校验返回值可序列化。"""
    with contextlib.redirect_stdout(sys.stderr):
        parameters = __import__("inspect").signature(collect).parameters
        result = collect() if not parameters else collect(config_json)
    json.dumps(result, ensure_ascii=False)
    return result


def _invoke(module, method_name, context):
    """调用清单已授权的插件方法并校验返回值可序列化。"""
    with contextlib.redirect_stdout(sys.stderr):
        method = getattr(module, method_name, None)
        if not callable(method):
            raise RuntimeError("插件入口未定义可调用方法：{}".format(method_name))
        result = method(context)
    json.dumps(result, ensure_ascii=False)
    return result


def _uninstall(module, context):
    """调用固定名称的卸载清理钩子并校验返回值。"""
    return _invoke(module, "uninstall", context)


def main():
    """执行插件并仅向标准输出写入一条协议 JSON。"""
    _configure_standard_streams()
    if len(sys.argv) != 2:
        print(json.dumps({"ok": False, "error": "缺少插件入口路径"}, ensure_ascii=False))
        return 2
    try:
        module = _load_plugin(Path(sys.argv[1]).resolve())
    except Exception:
        print(json.dumps({"ok": False, "error": traceback.format_exc()}, ensure_ascii=False), flush=True)
        return 1
    for line in sys.stdin:
        try:
            request = json.loads(line)
            command = request.get("command")
            if command == "stop":
                return 0
            if command == "collect":
                data = _collect(
                    getattr(module, "collect"),
                    request.get("config", "{}"),
                )
            elif command == "invoke":
                data = _invoke(
                    module,
                    str(request.get("method") or ""),
                    request.get("context") or {},
                )
            elif command == "uninstall":
                data = _uninstall(module, request.get("context") or {})
            else:
                raise RuntimeError("不支持的插件进程命令")
            response = {
                "ok": True,
                "request_id": request.get("request_id"),
                "data": data,
            }
        except Exception:
            response = {"ok": False, "error": traceback.format_exc()}
        print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
