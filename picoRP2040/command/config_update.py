"""实现运行配置修改命令策略。"""

try:
    import ujson as json
except ImportError:
    import json

from command.base import CommandError, CommandStrategy


CONFIGURATION_FILE = "runtime_config.json"
ALLOWED_CONFIGURATION = {
    "LCD_STYLE": str,
    "RENDER_INTERVAL_MS": int,
    "MONITOR_TIMEOUT_INTERVALS": int,
    "LED_BRIGHTNESS": int,
}


class ConfigUpdateCommand(CommandStrategy):
    """校验、持久化并应用允许动态修改的配置。"""

    name = "config.update"

    def execute(self, params, context):
        """更新白名单配置并返回是否建议重启。"""
        values = params.get("values")
        if not isinstance(values, dict) or not values:
            raise CommandError("CONFIG_VALUES_REQUIRED")
        normalized = {}
        for key, value in values.items():
            expected_type = ALLOWED_CONFIGURATION.get(key)
            if expected_type is None:
                raise CommandError("CONFIG_NOT_ALLOWED:" + str(key))
            try:
                normalized[key] = expected_type(value)
            except (TypeError, ValueError):
                raise CommandError("CONFIG_BAD_VALUE:" + key)
        persisted = {}
        try:
            with open(CONFIGURATION_FILE, "r") as source:
                persisted = json.loads(source.read())
        except (OSError, ValueError):
            pass
        persisted.update(normalized)
        with open(CONFIGURATION_FILE, "w") as output:
            output.write(json.dumps(persisted))
        import config
        for key, value in normalized.items():
            setattr(config, key, value)
        callback = context.service("config_updated", required=False)
        if callback is not None:
            callback(normalized)
        return {"updated": normalized, "restart_required": True}


COMMAND_STRATEGY = ConfigUpdateCommand()
