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
import hashlib
import importlib.util
import json
import pathlib
import re
import zipfile


CONFIG_ASSIGNMENT_PATTERN = r"(?m)^{}\s*=\s*[\"'][^\"']*[\"']\s*$"
CONFIG_VALUE_PATTERN = re.compile(r"^[a-z0-9_]+$")
VERSION_VALUE_PATTERN = re.compile(r"^[0-9A-Za-z.+_-]+$")


def load_supported_targets(source_directory):
    """从固件模块读取受支持的开发板型号和规范屏幕方案。"""
    targets = []
    for module_name, file_name, function_name in (
        ("pico_board_manager", "board_manager.py", "available_board_models"),
        ("pico_color_manager", "color_manager.py", "available_color_profiles"),
    ):
        spec = importlib.util.spec_from_file_location(
            module_name, source_directory / file_name
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        targets.append(tuple(getattr(module, function_name)()))
    return tuple(targets)


def configure_firmware(
    data, board_model=None, screen_color_profile=None, firmware_version=None
):
    """在内存中写入目标硬件配置，避免修改源码目录。"""
    text = data.decode("utf-8")
    replacements = {}
    if board_model and screen_color_profile:
        replacements.update({
            "BOARD_MODEL": board_model,
            "SCREEN_COLOR_PROFILE": screen_color_profile,
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
    source_directory, board_model=None, screen_color_profile=None,
    firmware_version=None,
):
    """收集固件目录内允许发布的 Python 文件并生成清单。"""
    files = []
    for path in sorted(source_directory.rglob("*.py")):
        relative = path.relative_to(source_directory).as_posix()
        data = path.read_bytes()
        if relative == "config.py":
            data = configure_firmware(
                data, board_model, screen_color_profile, firmware_version
            )
        files.append({"path": relative, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return files


def build_package(
    source_directory, output_path, version,
    board_model=None, screen_color_profile=None,
):
    """写入固件文件与确定性 JSON 清单，并返回升级包摘要。"""
    if bool(board_model) != bool(screen_color_profile):
        raise ValueError("开发板型号与屏幕色彩方案必须同时指定")
    if board_model:
        board_models, screen_profiles = load_supported_targets(source_directory)
        if board_model not in board_models:
            raise ValueError("不支持的开发板型号：{}".format(board_model))
        if screen_color_profile not in screen_profiles:
            raise ValueError(
                "不支持的屏幕色彩方案：{}".format(screen_color_profile)
            )
    files = collect_files(
        source_directory, board_model, screen_color_profile, version
    )
    if not files:
        raise ValueError("Pico 固件目录内没有 Python 文件")
    manifest = {"format": 1, "version": version, "files": files}
    if board_model:
        manifest["target"] = {
            "board_model": board_model,
            "screen_color_profile": screen_color_profile,
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        for item in files:
            source_path = source_directory / item["path"]
            data = source_path.read_bytes()
            if item["path"] == "config.py":
                data = configure_firmware(
                    data, board_model, screen_color_profile, version
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
    parser.add_argument("--screen-color-profile", help="写入升级包的屏幕色彩方案")
    arguments = parser.parse_args()
    digest = build_package(
        arguments.source.resolve(), arguments.output.resolve(), arguments.version,
        arguments.board_model, arguments.screen_color_profile,
    )
    checksum_path = arguments.output.with_suffix(arguments.output.suffix + ".sha256")
    checksum_path.write_text("{}  {}\n".format(digest, arguments.output.name), encoding="utf-8", newline="\n")
    print("升级包生成完成：{}，SHA-256={}".format(arguments.output, digest))


if __name__ == "__main__":
    main()
