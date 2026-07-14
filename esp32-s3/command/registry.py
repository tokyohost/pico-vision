"""发现、注册并分发 command 目录中的 JSON 命令策略。"""

import os

from command.base import CommandContext, CommandError


class CommandRegistry:
    """使用策略名称维护可扩展的命令处理器集合。"""

    def __init__(self, response_writer, services=None):
        """创建空注册表并初始化命令上下文。"""
        self._strategies = {}
        self._context = CommandContext(response_writer, services)

    def register(self, strategy):
        """注册一个具有唯一非空名称的命令策略。"""
        name = getattr(strategy, "name", None)
        if not isinstance(name, str) or not name:
            raise ValueError("INVALID_COMMAND_NAME")
        self._strategies[name] = strategy

    def discover(self, directory="command"):
        """自动加载目录内公开了 COMMAND_STRATEGY 的策略模块。"""
        try:
            names = os.listdir(directory)
        except OSError:
            names = []
        for filename in names:
            if not filename.endswith(".py") or filename.startswith("_"):
                continue
            module_name = filename[:-3]
            if module_name in ("base", "registry"):
                continue
            module = __import__(
                "command." + module_name,
                None,
                None,
                ("COMMAND_STRATEGY",),
            )
            strategy = getattr(module, "COMMAND_STRATEGY", None)
            if strategy is not None:
                self.register(strategy)
        return self

    def dispatch(self, message):
        """校验命令信封并交给匹配的策略执行。"""
        command = message.get("command")
        request_id = message.get("request_id")
        params = message.get("params", {})
        if not isinstance(command, str) or not command:
            raise CommandError("COMMAND_REQUIRED")
        if not isinstance(params, dict):
            raise CommandError("PARAMS_MUST_BE_OBJECT")
        strategy = self._strategies.get(command)
        if strategy is None:
            raise CommandError("UNKNOWN_COMMAND:" + command)
        self._context.request_id = request_id
        try:
            result = strategy.execute(params, self._context)
            if result is not None:
                self._context.respond("ok", command, result, request_id)
            return result
        finally:
            self._context.request_id = None
