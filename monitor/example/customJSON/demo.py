#!/usr/bin/env python3
"""自定义 JSON 数据采集示例。"""


# JSON 中 ext 节点下使用的字段名，必须在所有自定义脚本中唯一。
CUSTOM_DATA_KEY = "demo"

# monitor 调用 collect 的间隔，单位为秒，必须大于 0。
CUSTOM_DATA_INTERVAL = 5


def collect():
    """返回固定的 JSON 示例数据。"""
    return {
        "name": "custom-json-demo",
        "enabled": True,
        "count": 1,
        "message": "这是一个固定 JSON 示例",
    }
