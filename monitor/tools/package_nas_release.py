"""生成带版本清单的群晖、QNAP 和 TrueNAS 发布压缩包。"""

import argparse
import json
import shutil
import tarfile
import tempfile
from pathlib import Path


SUPPORTED_TARGETS = {
    "synology": "DSM 7.2+",
    "qnap": "QTS 5.1+ / QuTS hero h5.1+",
    "truenas": "TrueNAS SCALE 24.10+",
}
PACKAGE_FORMAT_VERSION = 1
ROOT_FILES = (
    "install-linux.sh",
    "requirements.txt",
    "README.md",
    "NAS_INSTALL.md",
)
RUNTIME_DIRECTORIES = (
    "collectTask",
    "custom_data",
    "monitor_core",
    "net",
)
SUPPORT_DIRECTORIES = (
    "bin",
    "debian",
    "packaging",
)


def _validate_version(version):
    """校验发布版本不为空且不包含路径分隔符。"""
    normalized = str(version or "").strip().lstrip("v")
    if not normalized or "/" in normalized or "\\" in normalized:
        raise ValueError("NAS 发布版本无效")
    return normalized


def _copy_release_files(source_root, package_root):
    """复制 NAS 运行所需源码、配置、静态资源和安装文件。"""
    for source_path in source_root.glob("*.py"):
        shutil.copy2(source_path, package_root / source_path.name)
    for filename in ROOT_FILES:
        shutil.copy2(source_root / filename, package_root / filename)
    for directory in RUNTIME_DIRECTORIES + SUPPORT_DIRECTORIES:
        shutil.copytree(
            source_root / directory,
            package_root / directory,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    web_dist = source_root / "win" / "ui-web" / "dist"
    if web_dist.is_dir():
        shutil.copytree(web_dist, package_root / "win" / "ui-web" / "dist")


def build_package(source_root, output_directory, target, version):
    """为指定 NAS 目标生成包含版本清单的 tar.gz 发布包。"""
    if target not in SUPPORTED_TARGETS:
        raise ValueError("不支持的 NAS 发布目标：{}".format(target))
    source_root = Path(source_root).resolve()
    output_directory = Path(output_directory).resolve()
    normalized_version = _validate_version(version)
    package_name = "OmniWatch-{}-noarch-v{}".format(target, normalized_version)
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / (package_name + ".tar.gz")
    with tempfile.TemporaryDirectory(prefix="omniwatch-nas-package-") as temporary_directory:
        package_root = Path(temporary_directory) / package_name
        package_root.mkdir()
        _copy_release_files(source_root, package_root)
        (package_root / "build_info.py").write_text(
            '"""保存构建时写入的 Monitor 版本及 GitHub 仓库信息。"""\n\n'
            'MONITOR_VERSION = "{}"\n'
            'GITHUB_REPOSITORY = "tokyohost/omniwatch-doc"\n'.format(normalized_version),
            encoding="utf-8",
        )
        manifest = {
            "format": PACKAGE_FORMAT_VERSION,
            "application": "OmniWatch Monitor",
            "version": normalized_version,
            "target": target,
            "supported_system": SUPPORTED_TARGETS[target],
            "architecture": "noarch",
            "installer": "install-linux.sh",
        }
        (package_root / "nas-package.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        with tarfile.open(output_path, "w:gz") as archive:
            archive.add(package_root, arcname=package_name)
    return output_path


def main():
    """解析命令行参数并生成 NAS 发布包。"""
    parser = argparse.ArgumentParser(description="生成 OmniWatch NAS 发布包")
    parser.add_argument("--source", required=True, help="Monitor 源码目录")
    parser.add_argument("--output-directory", required=True, help="发布包输出目录")
    parser.add_argument("--target", required=True, choices=tuple(SUPPORTED_TARGETS))
    parser.add_argument("--version", required=True, help="Monitor 发布版本")
    arguments = parser.parse_args()
    output_path = build_package(
        arguments.source,
        arguments.output_directory,
        arguments.target,
        arguments.version,
    )
    print(output_path)


if __name__ == "__main__":
    main()
