#!/usr/bin/env python3
"""自定义 JSON 数据采集示例。"""


# JSON 中 ext 节点下使用的字段名，必须在所有自定义脚本中唯一。
CUSTOM_DATA_KEY = "demo"

# 采集任务英文标识，用于 collection_tasks.intervals 配置，必须在所有自定义脚本中唯一。
CUSTOM_DATA_NAME = "demo"

# 采集任务中文名称，用于 Windows 配置页和日志展示。
CUSTOM_DATA_ZH_NAME = "演示数据"

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
