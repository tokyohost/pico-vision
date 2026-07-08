#!/usr/bin/env python3
"""自定义 JSON 数据插件示例。"""


def collect():
    """返回固定的 JSON 示例数据。"""
    return {
        "name": "custom-json-demo",
        "enabled": True,
        "count": 1,
        "message": "这是一个固定 JSON 示例",
    }
