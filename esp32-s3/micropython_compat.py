"""提供 MicroPython 原生代码装饰器的跨解释器兼容入口。"""

try:
    import micropython
except ImportError:
    class _MicroPythonCompat:
        """在桌面测试环境中将原生装饰器透明退化为原函数。"""

        @staticmethod
        def native(function):
            """返回未修改的函数以模拟 ``micropython.native``。"""
            return function

        @staticmethod
        def viper(function):
            """返回未修改的函数以模拟 ``micropython.viper``。"""
            return function

    micropython = _MicroPythonCompat()
