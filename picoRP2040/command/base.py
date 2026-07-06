"""定义 JSON 命令策略的公共接口、上下文和异常。"""


class CommandError(Exception):
    """表示可安全返回给 Monitor 的命令执行错误。"""


class CommandContext:
    """封装命令策略可使用的协议响应与应用服务。"""

    def __init__(self, response_writer, services=None):
        """保存响应函数及可选服务字典。"""
        self._response_writer = response_writer
        self.services = services or {}
        self.request_id = None

    def respond(self, status, command, data=None, request_id=None):
        """发送一条结构化命令响应。"""
        response = {"status": status, "command": command}
        if data is not None:
            response["data"] = data
        if request_id is not None:
            response["request_id"] = request_id
        self._response_writer(response)

    def service(self, name, required=True):
        """按名称取得服务，必要服务缺失时抛出命令错误。"""
        service = self.services.get(name)
        if service is None and required:
            raise CommandError("SERVICE_UNAVAILABLE:" + name)
        return service


class CommandStrategy:
    """定义所有自定义命令策略必须实现的最小接口。"""

    name = None

    def execute(self, params, context):
        """执行命令；子类必须覆盖此方法。"""
        raise NotImplementedError
