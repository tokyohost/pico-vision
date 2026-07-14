# Pico RP2040 系统监控屏

项目包含电脑端数据采集程序和 Pico RP2040 显示程序，实现两个独立功能：

1. 按开发板型号非阻塞控制 WS2812 多色灯或 GPIO 单色状态灯。
2. 通过 USB CDC 或 Wi-Fi WebSocket 增量接收 JSON，并将 ST7789 LCD 按条带异步刷新。

## 设计约束

- 不使用 RP2040 第二核心，规避 MicroPython 线程、USB 和 SPI 之间的互锁风险。
- 内置 USB CDC 仅用于 REPL；PV1 通信使用独立 USB CDC 及非阻塞批量 FIFO。
- LCD 不申请 240×320 的整帧缓冲，仅使用 240×48×2，即 23,040 字节条带缓冲。
- LED、串口接收和 LCD 刷新均由单核协作式主循环调度。
- JSON 最大长度为 16 KiB，超限数据包会被拒绝。

## Pico 端文件

将 `picoRP2040/` 的完整目录结构复制到 Pico 根目录：

- `main.py`：应用入口和协作式主循环。
- `led/`：不同板载状态灯的非阻塞控制策略与控制器工厂。
- `protocol.py`：PV1 握手及 JSON 增量接收状态机。
- `net/`：USB CDC、Wi-Fi、WebSocket 传输策略及首连接锁定选择器。
- `usb_transport.py`：创建与 REPL 隔离的 USB CDC 数据通道。
- `usb/device/`：上游 MicroPython `usb-device` 和 `usb-device-cdc` MIT 实现。
- `upgrade_manager.py`：串口升级会话、临时写入、SHA-256 校验、安装和自动重启。
- `data_receiver.py`：最新 JSON 快照缓存。
- `lcd.py`：ST7789 初始化和区域写屏。
- `canvas.py`：带条带裁剪的 RGB565 绘图。
- `dashboard.py`：仪表盘布局和分段刷新。
- `config.py`：开发板、屏幕方案、周期和协议配置。
- `color_manager.py`：按屏幕型号管理反色模式和 RGB/BGR 颜色顺序。
- `board_manager.py`：注册开发板硬件档案并隔离不同板载 LED 类型。
- `fonts/`：SDK 内置文泉驿点阵正黑和 Fusion Pixel 双语字模的授权说明。

Pico 握手会向 Monitor 返回当前开发板型号、屏幕色彩方案、运行固件版本和 `net` 状态；USB 模式返回 `mode=usb`，Wi-Fi 模式还返回 SSID、IP、网关、RSSI、WebSocket 端口与路径。源码
直接部署时版本为 `development`，发布升级包会自动写入对应的发布版本。

开发板型号和 Wi-Fi 开关由 `picoRP2040/config.py` 配置。例如 ESP32-S3 开启 Wi-Fi：

```python
BOARD_MODEL = "ESP32-S3"
WIFI_ENABLED = True
```

ESP32-S3 与 RP2040 都遵循样式声明的默认字体，例如现有紧凑样式使用
`font_name = "screen_2inch_compact"`。需要显示中文时，可通过 `canvas.text()` 的
`font_name` 参数为单次文字绘制选择字体；调用结束后会恢复样式默认字体。

项目配套的 RP2040 与 ESP32-S3 固件还可选择 `wqy_8x16` 或
`fusion_pixel_8x16`。两者均为英文半角 8×16、中文全角 16×16，直接由 `fn_canvas`
从固件只读区绘制。`canvas.text()` 和 `canvas.text_width()` 都接受 `font_name`；不传入
时保持当前样式字体，样式未指定时仍默认 `native`。

仅使用 USB CDC 时把 `WIFI_ENABLED` 设为 `False`，固件不会初始化无线网卡或 WebSocket 服务。支持的板型包括：

- `rp2040_usb`：GP22 上的 WS2812 多色状态灯。
- `rp2040_typec`：GP25 控制的单色状态灯。
- `ESP32-S3`：默认使用 GPIO48 上的板载 WS2812；具体开发板引脚不同时可修改 `board_manager.py` 中的档案。

新增型号时，可创建 `BoardProfile` 并通过 `register_board_profile()` 注册；业务层
无需感知 LED 的具体实现。

USB 能力同样按照 `BOARD_MODEL` 自动选择，不需要额外 USB 开关：

- `rp2040_usb`、`rp2040_typec` 使用 `machine.USBDevice` 注册保留 REPL 的独立数据 CDC。
- `ESP32-S3` 使用固件内置 USB CDC 或 USB 串行控制台，通过 `sys.stdin` 与
  `sys.stdout` 承载 PV1，不导入也不调用 ESP32 不支持的 `machine.USBDevice`。

ESP32-S3 内置控制台在收到 Monitor 首个字节后锁定 USB 会话；长期无通信后释放，
使启用 Wi-Fi 时 WebSocket 仍可参与传输竞选。

RP2040 端需要 MicroPython 1.23 或更新版本。启动后 USB 会重新枚举为
两个串口：一个保留给 REPL，另一个由 Monitor 通过 PV1 PING 自动识别。
首次部署后原串口短暂断开属于正常现象。Debian 下建议将
`PICO_MONITOR_PORT` 留空，不要固定 `/dev/ttyACM0`。

屏幕硬件由 `picoRP2040/config.py` 中的 `LCD_DEVICE_TYPE` 选择。编码由
芯片、尺寸、排针数量和批次组成，最终由 `lcd` 目录中对应的 `LcdDevice` 子类完整
定义脚位、分辨率、色彩、偏移和写屏细节。工厂会自动扫描该目录中公开
`LCD_DEVICE_CLASS` 的模块，无需维护集中式型号表：

- `st7789-2inch-8pin-a`：ST7789VW 二英寸八针 SPI A 款屏幕。
- `st7789-2.4inch-10pin-a`：ST7789 二点四英寸十针 SPI A 款屏幕。
- `st7789-2.4inch-8pin-b`：ST7789 二点四英寸八针 SPI B 款屏幕。

两种八针屏会按照 `BOARD_MODEL` 自动选择 GPIO。RP2040 保持原有
`SCK=GP6、MOSI=GP7、CS=GP8、DC=GP14、RST=GP15、BL=GP26`；ESP32-S3 使用
`SPI(2)、SCK=GPIO12、MOSI=GPIO11、CS=GPIO10、DC=GPIO9、RST=GPIO14、BL=GPIO13`。
ESP32-S3 默认以 10 MHz 驱动屏幕，并将不接屏幕的 MISO 显式分配到 GPIO15，避免
旧版 MicroPython 自动使用 GPIO13 而与背光 PWM 冲突。
完整接线见 `doc/ST7789_WIRING_README.md`。十针屏目前仅支持 RP2040，ESP32-S3
选择该方案时会返回明确错误，防止误用 RP2040 脚位。

屏幕色彩方案由所选屏幕档案确定，并在握手时提供给 Monitor：

- `st7789vw_2inch`：旧款 ST7789VW 二英寸屏，开启反色并使用 RGB 顺序。
- `st7789_2_4inch`：新款二点四英寸屏，关闭反色并使用 RGB 顺序。
- `st7789_2_4inch_bgr`：新款屏的 BGR 变体；仅在红色与蓝色互换时使用。

旧配置名 `st7789_2inch` 仍可使用，并会自动映射到 `st7789vw_2inch`。

GitHub Actions 会按照全部开发板型号与规范 LCD 设备类型的笛卡尔积生成升级包，
文件名格式为 `OmniWatch-pico-upgrade-v<版本>-<开发板型号>-<LCD设备类型>.zip`。无型号后缀的
兼容包固定对应 `rp2040_usb` 与 `st7789-2inch-8pin-a`，其他硬件不可混用该兼容包。

## 通信协议

PV1 帧可承载在 USB CDC 字节流或 WebSocket 二进制消息中。USB 和 WebSocket 同时可用时，设备锁定首个建立的连接；活动连接断开后才释放并重新选择。WebSocket 默认监听 `ws://设备IP:8765/pv1`，双方发送 Ping/Pong 心跳，Monitor 通信异常后按重连间隔重新握手。

设备提供两个配网命令：`wifi.list` 返回按信号强度排序的附近网络；`wifi.set` 的 `params` 接受 `ssid`、`password` 和可选 `timeout_ms`，并通过 `COMMAND` 帧返回连接成功详情或失败原因。Wi-Fi 凭据仅保存在设备端 `wifi_config.json`，PONG 和日志不会返回密码。

数据包采用纯 ASCII 行协议，避免 MicroPython 将二进制 `0x03` 解释为 Ctrl+C：

```text
JSON: + 单行 UTF-8 JSON + 换行符
```

设备发现命令为 `PING:PICO_LCD?\n`，有效 JSON 接收完成后返回 `ACK:JSON\n`。

## 启动方式

```powershell
python -m pip install -r requirements.txt
python send_frame.py
```

固定串口时可增加 `--port COM3` 参数。
