#!/usr/bin/env python3
"""提供自定义数据功能的稳定兼容入口。

具体职责已拆分到支持、运行时调度和生命周期管理模块；现有调用方仍可继续
通过 ``import custom_data`` 使用原有公开接口。
"""

import shutil
import time

import custom_data_support as _support
from custom_data_manager import CustomDataManager, get_manager
from custom_data_runtime import (
    CustomDataCollectionCoordinator,
    CustomDataCollectionTask,
    CustomDataWorker,
)
from custom_data_support import (
    CUSTOM_DATA_COLLECTION_POOL_CORE_WORKERS,
    CUSTOM_DATA_COLLECTION_POOL_MAX_WORKERS,
    CUSTOM_DATA_COLLECTION_QUEUE_CAPACITY,
    CUSTOM_DATA_DETAIL_MAX_BYTES,
    CUSTOM_DATA_DIRECTORY_NAME,
    CUSTOM_DATA_ENVIRONMENT_DIRECTORY_NAME,
    CUSTOM_DATA_KEY_PATTERN,
    CUSTOM_DATA_MANIFEST_NAME,
    CUSTOM_DATA_PLACEHOLDER,
    CUSTOM_DATA_PREVIEW_EXTENSIONS,
    CUSTOM_DATA_PREVIEW_MAX_BYTES,
    CUSTOM_DATA_REMOVE_RETRY_COUNT,
    CUSTOM_DATA_REMOVE_RETRY_DELAY_SECONDS,
    CUSTOM_DATA_REQUIREMENTS_NAME,
    CUSTOM_DATA_SLOW_TASK_WARNING_SECONDS,
    CUSTOM_DATA_TASK_PREFIX,
    CUSTOM_DATA_TEMPLATE_DIRECTORY_NAME,
    DEFAULT_SCRIPT_TIMEOUT_SECONDS,
    PLUGIN_PROTOCOL_VERSION,
    CustomDataDefinition,
    CustomDataDuplicateError,
    CustomDataError,
    CustomDataState,
    custom_data_panels,
    get_custom_data_directory,
    get_data_root,
    get_environment_root,
    get_runtime_python,
    normalize_plugin_configs,
)

_create_plugin_template = _support._create_plugin_template
_environment_python = _support._environment_python
_load_definition = _support._load_definition
_normalize_config_panel = _support._normalize_config_panel
_normalize_field_value = _support._normalize_field_value
_rmtree_with_retry = _support._rmtree_with_retry
_safe_extract_zip = _support._safe_extract_zip
_validate_identifier = _support._validate_identifier
_validate_preview_content = _support._validate_preview_content


def custom_data_task_defaults():
    """返回自定义数据任务完整标识到默认采集频率的映射。"""
    return {
        definition.task_name: definition.interval
        for definition in get_manager().task_definitions()
    }


def custom_data_task_zh_names():
    """返回自定义数据任务完整标识到中文名称的映射。"""
    return {
        definition.task_name: definition.zh_name
        for definition in get_manager().task_definitions()
    }
