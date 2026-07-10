#!/usr/bin/env python3
"""将 Pico 固件目录打包为包含 SHA-256 清单的可验证升级包。"""


#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.
#
#  Any project, software, or derivative work that uses, modifies, links to,
#  or incorporates this software must make its complete source code publicly
#  available under the same license.
#
#  This software is provided "as is", without warranty of any kind.

import argparse
import ast
import hashlib
import importlib.util
import json
import pathlib
import re
import zipfile


CONFIG_ASSIGNMENT_PATTERN = r"(?m)^{}\s*=\s*[\"'][^\"']*[\"']\s*$"
CONFIG_VALUE_PATTERN = re.compile(r"^[a-z0-9_.-]+$")
VERSION_VALUE_PATTERN = re.compile(r"^[0-9A-Za-z.+_-]+$")


def load_lcd_profiles(source_directory):
    """扫描 lcd 目录源码并提取规范方案、色彩档案和兼容别名。"""
    profiles = {}
    aliases = {}
    for path in sorted((source_directory / "lcd").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        device_type = None
        color_profile = None
        module_aliases = ()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                function_name = getattr(node.func, "id", None)
                if function_name == "LcdPanelProfile" and len(node.args) >= 10:
                    device_type = ast.literal_eval(node.args[0])
                    color_profile = ast.literal_eval(node.args[9])
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
                if any(getattr(target, "id", None) == "LCD_DEVICE_ALIASES" for target in targets):
                    module_aliases = ast.literal_eval(node.value)
        if device_type:
            profiles[device_type] = {"color_profile": color_profile}
            for alias in module_aliases:
                aliases[str(alias).lower()] = device_type
    if not profiles:
        raise ValueError("lcd 目录内没有可用的屏幕方案档案")
    return profiles, aliases


def load_supported_targets(source_directory):
    """从固件模块读取受支持的开发板型号和 LCD 设备类型。"""
    targets = []
    spec = importlib.util.spec_from_file_location(
        "pico_board_manager", source_directory / "board_manager.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    targets.append(tuple(module.available_board_models()))
    lcd_profiles, _ = load_lcd_profiles(source_directory)
    targets.append(tuple(sorted(lcd_profiles)))
    return tuple(targets)


def configure_firmware(
    data, board_model=None, lcd_device_type=None, firmware_version=None,
    screen_color_profile=None,
):
    """在内存中写入目标开发板和 LCD 硬件配置，避免修改源码目录。"""
    text = data.decode("utf-8")
    replacements = {}
    if board_model and lcd_device_type:
        replacements.update({
            "BOARD_MODEL": board_model,
            "LCD_DEVICE_TYPE": lcd_device_type,
        })
    if firmware_version:
        if not VERSION_VALUE_PATTERN.fullmatch(firmware_version):
            raise ValueError("固件版本包含非法字符：{}".format(firmware_version))
        replacements["FIRMWARE_VERSION"] = firmware_version
    for name, value in replacements.items():
        if name != "FIRMWARE_VERSION" and not CONFIG_VALUE_PATTERN.fullmatch(value or ""):
            raise ValueError("{} 包含非法配置值：{}".format(name, value))
        pattern = CONFIG_ASSIGNMENT_PATTERN.format(name)
        text, count = re.subn(pattern, '{} = "{}"'.format(name, value), text)
        if count != 1:
            raise ValueError("config.py 中 {} 配置项数量异常：{}".format(name, count))
    return text.encode("utf-8")


def collect_files(
    source_directory, board_model=None, lcd_device_type=None,
    firmware_version=None, screen_color_profile=None,
):
    """收集固件目录内允许发布的 Python 文件并生成清单。"""
    files = []
    for path in sorted(source_directory.rglob("*.py")):
        relative = path.relative_to(source_directory).as_posix()
        data = path.read_bytes()
        if relative == "config.py":
            data = configure_firmware(
                data, board_model, lcd_device_type, firmware_version,
                screen_color_profile,
            )
        files.append({"path": relative, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return files


def build_package(
    source_directory, output_path, version,
    board_model=None, lcd_device_type=None,
):
    """写入固件文件与确定性 JSON 清单，并返回升级包摘要。"""
    screen_color_profile = None
    lcd_profiles, lcd_aliases = load_lcd_profiles(source_directory)
    requested_lcd_type = str(lcd_device_type or "").lower()
    if requested_lcd_type in lcd_aliases:
        lcd_device_type = lcd_aliases[requested_lcd_type]
    if bool(board_model) != bool(lcd_device_type):
        raise ValueError("开发板型号与 LCD 设备类型必须同时指定")
    if board_model:
        board_models, lcd_device_types = load_supported_targets(source_directory)
        if board_model not in board_models:
            raise ValueError("不支持的开发板型号：{}".format(board_model))
        if lcd_device_type not in lcd_device_types:
            raise ValueError(
                "不支持的 LCD 设备类型：{}".format(lcd_device_type)
            )
    files = collect_files(
        source_directory, board_model, lcd_device_type, version,
        screen_color_profile,
    )
    if not files:
        raise ValueError("Pico 固件目录内没有 Python 文件")
    manifest = {"format": 1, "version": version, "files": files}
    if board_model:
        manifest["target"] = {
            "board_model": board_model,
            "lcd_device_type": lcd_device_type,
            "screen_color_profile": (
                screen_color_profile
                or lcd_profiles[lcd_device_type]["color_profile"]
            ),
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        for item in files:
            source_path = source_directory / item["path"]
            data = source_path.read_bytes()
            if item["path"] == "config.py":
                data = configure_firmware(
                    data, board_model, lcd_device_type, version,
                    screen_color_profile,
                )
            archive.writestr(item["path"], data)
    return hashlib.sha256(output_path.read_bytes()).hexdigest()


def main():
    """解析命令行参数并输出升级包及同名 SHA-256 文件。"""
    parser = argparse.ArgumentParser(description="生成 Pico 串口升级包")
    parser.add_argument("--source", type=pathlib.Path, required=True, help="Pico 固件源码目录")
    parser.add_argument("--output", type=pathlib.Path, required=True, help="输出 ZIP 路径")
    parser.add_argument("--version", required=True, help="升级包版本")
    parser.add_argument("--board-model", help="写入升级包的开发板型号")
    parser.add_argument("--lcd-device-type", help="写入升级包的 LCD 设备类型")
    parser.add_argument("--screen-color-profile", help="兼容旧命令的屏幕色彩方案")
    arguments = parser.parse_args()
    lcd_device_type = arguments.lcd_device_type or arguments.screen_color_profile
    digest = build_package(
        arguments.source.resolve(), arguments.output.resolve(), arguments.version,
        arguments.board_model, lcd_device_type,
    )
    checksum_path = arguments.output.with_suffix(arguments.output.suffix + ".sha256")
    checksum_path.write_text("{}  {}\n".format(digest, arguments.output.name), encoding="utf-8", newline="\n")
    print("升级包生成完成：{}，SHA-256={}".format(arguments.output, digest))


if __name__ == "__main__":
    main()
