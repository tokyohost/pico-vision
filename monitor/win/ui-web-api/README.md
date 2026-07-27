# Web 界面 Python API

本目录承载 `ui_web.py` 拆分后的 Python 实现。`win.ui_web` 继续作为稳定兼容
入口，托盘程序和已有测试无需修改导入路径。

- `bridge.py`：统一动作路由和桥接状态初始化。
- `settings_api.py`：首屏数据、设置保存和 qBittorrent 验证。
- `update_api.py`：应用、固件和 SDK 在线更新。
- `device_api.py`：设备控制、探测和 SDK 刷写。
- `network_api.py`：Wi-Fi 和 WebSocket 客户端管理。
- `style_api.py`：屏幕样式管理。
- `custom_data_api.py`：自定义数据插件管理。
- `log_api.py`：日志和数据目录操作。
- `common.py`：队列、对话框和响应公共能力。
- `webview.py`：pywebview 窗口生命周期和页面导航。
- `config.py`：桥接层稳定配置常量。
