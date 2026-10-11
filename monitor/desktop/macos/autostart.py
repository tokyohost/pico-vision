"""macOS 12 及以上用户级 LaunchAgent 启动项管理。"""

import os
import plistlib
import subprocess
from pathlib import Path


LAUNCH_AGENT_LABEL = "com.omniwatch.monitor"


class MacOsAutostart:
    """只管理当前用户的启动项，不申请 root 权限或安装系统守护进程。"""

    def __init__(self, command, directory=None):
        """保存绝对启动命令及用户 LaunchAgents 目录。"""
        self.command = [str(argument) for argument in command]
        self.path = Path(directory or Path.home() / "Library" / "LaunchAgents") / (LAUNCH_AGENT_LABEL + ".plist")

    def is_enabled(self):
        """仅将内容匹配当前应用的有效 plist 视为已启用。"""
        try:
            values = plistlib.loads(self.path.read_bytes())
            return values.get("Label") == LAUNCH_AGENT_LABEL and values.get("ProgramArguments") == self.command
        except (OSError, ValueError, plistlib.InvalidFileException):
            return False

    def set_enabled(self, enabled):
        """写入或移除自己的启动项，并同步用户 launchd 注册状态。"""
        domain = "gui/{}".format(os.getuid())
        if not enabled:
            subprocess.run(["/bin/launchctl", "bootout", domain + "/" + LAUNCH_AGENT_LABEL],
                           capture_output=True, timeout=15, check=False)
            self.path.unlink(missing_ok=True)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise RuntimeError("启动项路径是符号链接，拒绝覆盖")
        previous = self.path.read_bytes() if self.path.exists() else None
        values = {"Label": LAUNCH_AGENT_LABEL, "ProgramArguments": self.command,
                  "RunAtLoad": True, "KeepAlive": False, "ProcessType": "Interactive"}
        self.path.write_bytes(plistlib.dumps(values))
        self.path.chmod(0o600)
        try:
            # 去掉旧注册后重新加载，以便应用移动路径后更新启动命令。
            subprocess.run(["/bin/launchctl", "bootout", domain + "/" + LAUNCH_AGENT_LABEL],
                           capture_output=True, timeout=15, check=False)
            subprocess.run(["/bin/launchctl", "bootstrap", domain, str(self.path)],
                           capture_output=True, timeout=15, check=True)
        except Exception:
            if previous is None:
                self.path.unlink(missing_ok=True)
            else:
                self.path.write_bytes(previous)
                subprocess.run(["/bin/launchctl", "bootstrap", domain, str(self.path)],
                               capture_output=True, timeout=15, check=False)
            raise
