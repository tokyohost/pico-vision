#!/usr/bin/env python3
"""通过 mpremote 将本地 Pico 工程逐文件复制到指定串口设备。"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath


DEFAULT_SOURCE = Path(r"E:\WorkSpace\fn-vision\pico-project\picoRP2040")
REMOTE_MANIFEST_PREFIX = "MPREMOTE_FILE:"
REMOTE_MANIFEST_BATCH_SIZE = 40


class MpremoteStreamCopier:
    """使用 mpremote 命令逐目录、逐文件复制 Pico 工程。"""

    def __init__(self, port: str, source: Path, remote_root: str = "/") -> None:
        """初始化复制器，并保存串口、本地目录及设备端目标目录。"""
        self.port = port
        self.source = source.resolve()
        self.remote_root = self._normalize_remote_root(remote_root)
        self.mpremote_command = [sys.executable, "-m", "mpremote"]

    @staticmethod
    def _normalize_remote_root(remote_root: str) -> PurePosixPath:
        """将设备端目标目录规范化为绝对 POSIX 路径。"""
        normalized = "/" + remote_root.strip().strip("/")
        return PurePosixPath(normalized)

    def _remote_path(self, local_path: Path) -> str:
        """根据本地相对路径生成 mpremote 使用的设备端路径。"""
        relative_path = local_path.relative_to(self.source)
        remote_path = self.remote_root.joinpath(*relative_path.parts)
        return f":{remote_path.as_posix()}"

    def _run_mpremote(self, arguments: list[str], description: str) -> None:
        """执行 mpremote 子命令，并将命令输出实时转发到当前终端。"""
        command = [*self.mpremote_command, "connect", self.port, *arguments]
        print(f"  {description}", flush=True)
        try:
            result = subprocess.run(command, check=False)
        except KeyboardInterrupt:
            print("\n复制已由用户中止。", file=sys.stderr)
            raise
        if result.returncode != 0:
            raise RuntimeError(
                f"mpremote 执行失败，退出码为 {result.returncode}：{description}"
            )

    def _capture_mpremote(
        self,
        arguments: list[str],
        description: str,
    ) -> str:
        """执行 mpremote 子命令，并返回设备端标准输出。"""
        command = [*self.mpremote_command, "connect", self.port, *arguments]
        print(f"  {description}", flush=True)
        try:
            result = subprocess.run(
                command,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except KeyboardInterrupt:
            print("\n复制已由用户中止。", file=sys.stderr)
            raise
        if result.returncode != 0:
            output = result.stdout.strip()
            details = f"\n{output}" if output else ""
            raise RuntimeError(
                f"mpremote 执行失败，退出码为 {result.returncode}："
                f"{description}{details}"
            )
        return result.stdout

    @staticmethod
    def _local_fingerprint(local_file: Path) -> tuple[int, str]:
        """计算本地文件大小和 SHA-256 指纹。"""
        digest = hashlib.sha256()
        size = 0
        with local_file.open("rb") as source:
            while True:
                block = source.read(4096)
                if not block:
                    break
                size += len(block)
                digest.update(block)
        return size, digest.hexdigest()

    @staticmethod
    def _parse_remote_manifest(output: str) -> dict[str, tuple[int, str]]:
        """从 mpremote 输出中解析设备文件大小和 SHA-256 指纹。"""
        manifest: dict[str, tuple[int, str]] = {}
        for line in output.splitlines():
            marker_index = line.find(REMOTE_MANIFEST_PREFIX)
            if marker_index < 0:
                continue
            payload = line[marker_index + len(REMOTE_MANIFEST_PREFIX):]
            try:
                path_hex, size_text, digest = payload.strip().split(":", 2)
                remote_path = bytes.fromhex(path_hex).decode("utf-8")
                manifest[remote_path] = (int(size_text), digest.lower())
            except (UnicodeDecodeError, ValueError):
                continue
        return manifest

    def _read_remote_manifest(
        self,
        files: list[Path],
    ) -> dict[str, tuple[int, str]]:
        """分批读取设备端目标文件的大小和 SHA-256 指纹。"""
        remote_paths = [self._remote_path(file)[1:] for file in files]
        manifest: dict[str, tuple[int, str]] = {}
        for offset in range(0, len(remote_paths), REMOTE_MANIFEST_BATCH_SIZE):
            batch = tuple(remote_paths[offset:offset + REMOTE_MANIFEST_BATCH_SIZE])
            code = (
                "try:\n"
                " import uhashlib as hashlib\n"
                "except ImportError:\n"
                " import hashlib\n"
                "import binascii\n"
                f"paths={batch!r}\n"
                "for p in paths:\n"
                " try:\n"
                "  f=open(p,'rb')\n"
                " except OSError:\n"
                "  continue\n"
                " h=hashlib.sha256()\n"
                " size=0\n"
                " try:\n"
                "  while True:\n"
                "   b=f.read(1024)\n"
                "   if not b: break\n"
                "   size+=len(b)\n"
                "   h.update(b)\n"
                " finally:\n"
                "  f.close()\n"
                f" print('{REMOTE_MANIFEST_PREFIX}'+"
                "binascii.hexlify(p.encode()).decode()+':' +"
                "str(size)+':'+binascii.hexlify(h.digest()).decode())\n"
            )
            output = self._capture_mpremote(
                ["exec", code],
                "校验设备文件 {}/{}".format(
                    min(offset + len(batch), len(remote_paths)),
                    len(remote_paths),
                ),
            )
            manifest.update(self._parse_remote_manifest(output))
        return manifest

    def _check_environment(self) -> None:
        """检查源目录和 mpremote 模块是否可用。"""
        if not self.source.exists():
            raise FileNotFoundError(f"源目录不存在：{self.source}")
        if not self.source.is_dir():
            raise NotADirectoryError(f"源路径不是目录：{self.source}")

        result = subprocess.run(
            [*self.mpremote_command, "--version"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "未找到 mpremote，请先执行：python -m pip install mpremote"
            )
        version = result.stdout.strip()
        if version:
            print(f"检测到 {version}")

    def _ensure_remote_directory(self, remote_directory: PurePosixPath) -> None:
        """在设备端创建目录；目录已经存在时保持不变。"""
        directory_literal = repr(remote_directory.as_posix())
        code = (
            "import os\n"
            f"p={directory_literal}\n"
            "try:\n"
            " os.mkdir(p)\n"
            "except OSError:\n"
            " try:\n"
            "  os.listdir(p)\n"
            " except OSError:\n"
            "  raise\n"
        )
        self._run_mpremote(
            ["exec", code],
            f"确认设备目录 {remote_directory.as_posix()}",
        )

    def _prepare_remote_directories(self, directories: list[Path]) -> None:
        """按照层级顺序创建目标根目录及全部子目录。"""
        current = PurePosixPath("/")
        for part in self.remote_root.parts[1:]:
            current /= part
            self._ensure_remote_directory(current)

        for directory in directories:
            self._ensure_remote_directory(
                PurePosixPath(self._remote_path(directory)[1:])
            )

    def copy(self, force: bool = False, restart: bool = True) -> None:
        """增量复制工程，并可在全部操作完成后复位设备。"""
        self._check_environment()
        all_items = sorted(
            (
                item
                for item in self.source.rglob("*")
                if "__pycache__" not in item.parts
                   and item.suffix.lower() not in {".pyc", ".pyo"}
            ),
            key=lambda item: (
                len(item.relative_to(self.source).parts),
                item.as_posix(),
            ),
        )
        directories = [item for item in all_items if item.is_dir()]
        files = [item for item in all_items if item.is_file()]

        print(f"源目录：{self.source}")
        print(f"目标设备：{self.port}{self.remote_root.as_posix()}")
        print(f"待复制：{len(directories)} 个目录，{len(files)} 个文件")

        started_at = time.monotonic()
        self._prepare_remote_directories(directories)
        if force:
            print("已启用强制模式，将上传全部文件。")
            remote_manifest: dict[str, tuple[int, str]] = {}
        else:
            print("正在校验设备端文件内容……")
            remote_manifest = self._read_remote_manifest(files)

        local_fingerprints = {
            file: self._local_fingerprint(file)
            for file in files
        }
        total_bytes = sum(size for size, _ in local_fingerprints.values())
        processed_bytes = 0
        copied_bytes = 0
        copied_files = 0
        skipped_files = 0

        for index, file in enumerate(files, start=1):
            file_size, local_digest = local_fingerprints[file]
            relative_path = file.relative_to(self.source)
            print(
                f"[{index}/{len(files)}] {relative_path} ({file_size} 字节)",
                flush=True,
            )
            remote_path = self._remote_path(file)
            remote_fingerprint = remote_manifest.get(remote_path[1:])
            local_fingerprint = (file_size, local_digest)
            if not force and remote_fingerprint == local_fingerprint:
                skipped_files += 1
                print("  跳过：设备端内容一致", flush=True)
            else:
                self._run_mpremote(
                    ["fs", "cp", str(file), remote_path],
                    f"复制到 {remote_path[1:]}",
                )
                copied_files += 1
                copied_bytes += file_size
            processed_bytes += file_size
            percent = (
                100.0
                if total_bytes == 0
                else processed_bytes * 100 / total_bytes
            )
            print(
                f"  校验进度：{processed_bytes}/{total_bytes} 字节"
                f"（{percent:.1f}%）",
                flush=True,
            )

        if restart:
            self._run_mpremote(
                ["reset"],
                "部署完成，复位设备并重新运行 main.py",
            )

        elapsed = time.monotonic() - started_at
        print(
            "增量复制完成：上传 {} 个文件（{} 字节），跳过 {} 个文件，"
            "耗时 {:.1f} 秒。".format(
                copied_files,
                copied_bytes,
                skipped_files,
                elapsed,
            )
        )


def parse_arguments() -> argparse.Namespace:
    """解析命令行中的串口、源目录和设备端目标目录。"""
    parser = argparse.ArgumentParser(
        description="通过 mpremote 将 Pico 工程逐文件复制到指定 COM 口。"
    )
    parser.add_argument("port", help="设备串口，例如 COM3")
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"本地源目录，默认：{DEFAULT_SOURCE}",
    )
    parser.add_argument(
        "--remote-root",
        default="/",
        help="设备端目标目录，默认：/",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="跳过内容校验并强制上传全部文件",
    )
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="上传完成后不复位设备，保留当前 mpremote 会话状态",
    )
    return parser.parse_args()


def main() -> int:
    """执行命令行入口，并以明确的退出码报告复制结果。"""
    arguments = parse_arguments()
    try:
        copier = MpremoteStreamCopier(
            port=arguments.port,
            source=arguments.source,
            remote_root=arguments.remote_root,
        )
        copier.copy(force=arguments.force, restart=not arguments.no_reset)
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
