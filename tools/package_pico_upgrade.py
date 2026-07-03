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
import json
import pathlib
import zipfile


def collect_files(source_directory):
    """收集固件目录内允许发布的 Python 文件并生成清单。"""
    files = []
    for path in sorted(source_directory.rglob("*.py")):
        relative = path.relative_to(source_directory).as_posix()
        data = path.read_bytes()
        files.append({"path": relative, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return files


def build_package(source_directory, output_path, version):
    """写入固件文件与确定性 JSON 清单，并返回升级包摘要。"""
    files = collect_files(source_directory)
    if not files:
        raise ValueError("Pico 固件目录内没有 Python 文件")
    manifest = {"format": 1, "version": version, "files": files}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        for item in files:
            archive.write(source_directory / item["path"], item["path"])
    return hashlib.sha256(output_path.read_bytes()).hexdigest()


def main():
    """解析命令行参数并输出升级包及同名 SHA-256 文件。"""
    parser = argparse.ArgumentParser(description="生成 Pico 串口升级包")
    parser.add_argument("--source", type=pathlib.Path, required=True, help="Pico 固件源码目录")
    parser.add_argument("--output", type=pathlib.Path, required=True, help="输出 ZIP 路径")
    parser.add_argument("--version", required=True, help="升级包版本")
    arguments = parser.parse_args()
    digest = build_package(arguments.source.resolve(), arguments.output.resolve(), arguments.version)
    checksum_path = arguments.output.with_suffix(arguments.output.suffix + ".sha256")
    checksum_path.write_text("{}  {}\n".format(digest, arguments.output.name), encoding="utf-8", newline="\n")
    print("升级包生成完成：{}，SHA-256={}".format(arguments.output, digest))


if __name__ == "__main__":
    main()
