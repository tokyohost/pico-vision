"""提供可自动发现的 JSON 命令策略包。"""

from command.registry import CommandRegistry


def create_command_registry(response_writer, services=None):
    """创建并自动发现内置及用户自定义命令策略。"""
    return CommandRegistry(response_writer, services).discover()
