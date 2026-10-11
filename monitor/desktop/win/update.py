"""Windows 应用发布资源适配。"""

import platform
import urllib.request
from desktop.common.release import ReleaseUpdater


class WindowsReleaseUpdater(ReleaseUpdater):
    """保留原有 Windows x86/x64 安装包选择规则。"""

    def select_monitor_asset(self, assets, version):
        """按当前 Python 进程位数和发布版本选择 Windows Monitor 安装包。"""
        architecture = "x64" if platform.architecture()[0] == "64bit" else "x86"
        return self._required_asset(
            assets,
            "OmniWatch-windows-{}-setup-v{}.exe".format(architecture, version),
        )
