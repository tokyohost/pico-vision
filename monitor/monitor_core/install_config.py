"""DEB 安装阶段迁移配置到服务可写的专用目录，不依赖应用模块缓存。"""

import os
from pathlib import Path
import shutil
import tempfile


def migrate_config(legacy_path, target_path):
    """首次迁移旧配置，已有目标配置（含手动修复配置）始终保留。"""
    legacy = Path(legacy_path)
    target = Path(target_path)
    if target.is_file():
        return False
    if target.exists() or target.is_symlink():
        raise RuntimeError("目标配置不是有效文件：{}".format(target))
    if not legacy.is_file():
        raise RuntimeError("缺少旧配置或安装包默认配置：{}".format(legacy))
    target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".config-migration-", dir=target.parent)
    try:
        # mkstemp 创建的文件权限为 0600，避免配置中的访问凭据被其他用户读取。
        with os.fdopen(descriptor, "wb") as output, legacy.open("rb") as source:
            shutil.copyfileobj(source, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


if __name__ == "__main__":
    migrate_config("/etc/pico-monitor.conf", "/etc/pico-monitor/config.yaml")
