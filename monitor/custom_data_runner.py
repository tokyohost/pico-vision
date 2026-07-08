#!/usr/bin/env python3
"""在隔离子进程中加载自定义数据插件并输出协议 JSON。"""

import importlib.util
import contextlib
import json
import sys
import traceback
from pathlib import Path


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


def _collect(script_path):
    """执行插件 collect 方法并校验返回值可序列化。"""
    with contextlib.redirect_stdout(sys.stderr):
        module = _load_module(script_path)
        collect = getattr(module, "collect", None)
        if not callable(collect):
            raise RuntimeError("插件入口必须定义 collect() 方法")
        result = collect()
    json.dumps(result, ensure_ascii=False)
    return result


def main():
    """执行插件并仅向标准输出写入一条协议 JSON。"""
    if len(sys.argv) != 2:
        print(json.dumps({"ok": False, "error": "缺少插件入口路径"}, ensure_ascii=False))
        return 2
    try:
        data = _collect(Path(sys.argv[1]).resolve())
        print(json.dumps({"ok": True, "data": data}, ensure_ascii=False))
        return 0
    except Exception:
        print(json.dumps({"ok": False, "error": traceback.format_exc()}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
