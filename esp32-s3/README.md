# ESP32-S3 设备端代码

本目录是从 `picoRP2040` 独立出来的 ESP32-S3 专用实现，不包含 RP2040 硬件档案、Pico USB Device 驱动或跨开发板选择逻辑。

## 固定硬件配置

- 开发板：ESP32-S3
- 状态灯：GPIO48 板载 WS2812，单灯珠
- LCD 总线：SPI2，SCK GPIO12，MOSI GPIO11，保留 MISO GPIO15
- LCD 控制：CS GPIO10，DC/RS GPIO9，RST/RESET GPIO14，背光 PWM GPIO13
- 默认 LCD：ST7789 2.4 英寸十针 SPI A 款，排针顺序为 GND、RS、CS、SCL、SDA、RESET、VDD、GND、LED+、LED-
- 十针信号：RS 接 GPIO9，CS 接 GPIO10，SCL 接 GPIO12，SDA 接 GPIO11，RESET 接 GPIO14
- 十针背光：LED+ 接受限电源，LED- 通过外部低端 MOSFET 调光，GPIO13 只驱动 MOSFET 栅极
- 按键：GPIO1、GPIO2、GPIO3，低电平有效并启用内部上拉
- 通信：ESP32-S3 内置 USB 控制台和可选 Wi-Fi WebSocket
- WebSocket：客户端握手携带设备名称和稳定标识；设备持久化连接记录，并支持禁用、优先级抢占和单活动连接 JSON 同步

## 10pin LCD 接线图

ST7789 2.4 英寸十针 SPI A 款屏幕按以下排针顺序连接 ESP32-S3：

```text
ST7789 10pin LCD                  ESP32-S3
------------------------------------------------
1  GND        ------------------  GND
2  RS / DC    ------------------  GPIO9
3  CS         ------------------  GPIO10
4  SCL / SCK  ------------------  GPIO12
5  SDA / MOSI ------------------  GPIO11
6  RESET      ------------------  GPIO14
7  VDD        ------------------  3V3
8  GND        ------------------  GND
9  LED+       ------------------  受限流的背光电源正极
10 LED-       ------------------  MOSFET 背光模块 LED- 端子
```

背光使用 GPIO13 驱动外部低端 MOSFET，GPIO 不直接承载 LED 背光电流：

```text
MOSFET 背光模块端子              连接位置
------------------------------------------------
PWM / SIG / IN  --------------  ESP32-S3 GPIO13
GND             --------------  ESP32-S3 GND
LED-            --------------  LCD 第 10 脚 LED-
GND             --------------  背光电源 GND，与 ESP32-S3 GND 共地
```

如果使用裸 MOSFET 而不是成品背光模块，则按以下方式连接：

```text
GPIO13 ----[100R~220R]---- MOSFET G
GPIO13 ----[10K下拉]------ GND

MOSFET S ----------------- GND
MOSFET D ----------------- LCD LED-
LCD LED+ ----------------- 受限流的背光电源正极
ESP32-S3 GND ------------- 背光电源 GND 共地
```

LED+ 必须接带限流的背光电源正极，不要让 GPIO 或无保护电源直接承担背光电流。

## 固件要求

推荐使用仓库 `esp32/driver` 中带原生 PV1、Canvas 和 LCD DMA 加速模块的 ESP32-S3 MicroPython 固件。标准固件缺少原生模块时，协议、画布和 LCD 像素传输会自动使用兼容后端，但必须提供 `network`、`neopixel`、`machine.SPI`、`machine.PWM` 和内置 USB 控制台能力。

部署时将本目录中的 Python 文件及子目录复制到 ESP32-S3 文件系统根目录，并以 `main.py` 作为启动入口。

## 独立 USB CDC

固件按 TinyUSB 官方双 CDC 方案在启动时直接枚举两个原生接口：CDC 0 保留给 REPL，CDC 1 专供 PV1 数据。数据接口由 C 回调立即读空 TinyUSB FIFO，并写入独立 32 KB 环形缓冲，不再使用 `machine.USBDevice` 的 Python 端点回调。环形缓冲在后端初始化时优先从 PSRAM 动态分配，避免把 32 KB 常驻数组塞进紧张的内部 DRAM。该功能必须连接 ESP32-S3 原生 USB OTG 接口，CH343 等 USB-UART 接口仍属于兼容控制台通道。

- 原生数据 CDC 通过 `_usb_cdc_data → NativeCdcStream → UsbCdcTransport → TransportManager` 接入现有协议。
- USB 枚举、端点重挂、FIFO 和环形缓冲全部由固件 C 层处理，Python 渲染停顿不会中断逐包端点服务。
- 固件没有编译 `_usb_cdc_data` 时才回退到原有内置控制台或 CH343 通道，不再创建存在长期稳定性问题的运行时 Python CDC。
- 如需固定使用 CH343/控制台传输，应把 `USB_DEDICATED_CDC_ENABLED` 设为 `False`。
- 可通过 `config.py` 的 `USB_DEDICATED_CDC_ENABLED` 控制数据通道；C 缓冲容量由板级固件宏 `MICROPY_HW_USB_CDC_DATA_RX_BUFSIZE` 决定。
- PONG 会报告当前 MicroPython SDK 版本及 `sdk_update` 能力。仅原生 USB 传输可以执行 `sdk.bootloader`；设备先返回结构化成功应答，再调用 `machine.bootloader()` 进入 ESP32-S3 ROM USB 下载模式，供 Windows Monitor 无按键刷写完整合并 bin。

## 第二阶段渲染服务

ESP32-S3 专用入口已经使用 `render_service.py` 隔离通信主循环与渲染状态：

- 通信主线程只解析 USB/WIFI 数据并发布最新快照。
- Python 渲染工作线程独占 `DashboardRenderer`、Canvas、LCD 和 SPI。
- 两个固定快照槽支持 `latest` 最新帧覆盖和 `block` 阻塞等待两种背压策略。
- 样式切换、旋转、背光和截图通过八项固定控制队列在渲染线程执行。
- 线程模块不可用或线程创建失败时，自动回退到相同接口的同步渲染服务。
- 启动日志通过 `BOOT:RENDER_SERVICE:THREAD` 或 `SYNC_FALLBACK` 标明实际模式。

该阶段可以在 SPI DMA 等待释放 GIL 时让通信主线程继续运行，但所有 MicroPython 线程仍受 GIL 和 CPU1 亲和性限制。真正把绘制计算固定到 CPU0 需要继续实施原生 C 渲染任务。

## LCD 像素传输后端

`LCD_TRANSFER_BACKEND` 可在 `legacy`、`native_dma` 和 `auto` 之间切换。默认
`auto` 在固件包含 `fn_lcd` API 2 时，让 MicroPython 始终在完整 RAM 画布绘制；
C 固件自动检测并记录脏区，以两块内部 SRAM 条带缓冲交替提取像素，再通过两块
内部 DMA RAM 发送。旧固件会安全回退标准 `machine.SPI.write()`。该优化不改变
Python Style 和 Canvas API；完整原理、
配置方法与对照测试见
[ESP32-S3 MicroPython LCD DMA 渲染原理](../doc/esp32-fix/ESP32-S3_MicroPython_LCD_DMA渲染原理.md)。
