"""把固件升级子命令适配为 JSON 命令策略。"""

from command.base import CommandError, CommandStrategy


class UpgradeCommand(CommandStrategy):
    """将升级参数转交给现有升级会话管理器。"""

    name = "upgrade"

    def execute(self, params, context):
        """验证 action 并调用升级管理器处理子命令。"""
        action = params.get("action")
        if not isinstance(action, str) or not action:
            raise CommandError("UPGRADE_ACTION_REQUIRED")
        manager = context.service("upgrade_manager")
        try:
            manager.handle_json(params)
        except (KeyError, TypeError, ValueError, OSError) as error:
            raise CommandError("UPGRADE:" + str(error))


COMMAND_STRATEGY = UpgradeCommand()
