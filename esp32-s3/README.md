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

### 主题按键监听

系统菜单新增“系统信息”和“关于”，位于原四项设置之后、“返回”之前。

- 系统信息展示 SDK 版本、固件版本、完整设备 UUID、设备名称、开发板型号、屏幕型号和物理分辨率，以及内存使用、当前连接方式、Wi-Fi 状态、SSID 和 IP 地址。版本及 UUID 与设备协议上报使用相同的数据来源，不依赖电脑端在线。
- 进入系统信息时读取全部信息，可见期间每秒采样内存及连接状态，只有值变化才刷新画面。静态版本信息不重复采集，离开后停止采样；读取失败仅对应项显示“未知”或“不可用”。内存统计为 MicroPython 堆的已用、空闲、总字节数和使用百分比，不代表芯片全部 RAM。
- 信息列表显示摘要，功能键确认进入只读详情。详情按当前屏幕实际字体宽度换行，超屏后使用上下键浏览；完整 ID、版本号和网址不会截断。每页末项为“返回”，返回父页保留原选中位置；正文按确认不会修改配置。
- 关于页展示 OmniWatch、设备端用途简介、作者 tokyohost，以及项目地址 `https://github.com/tokyohost/omniwatch-doc`。页面沿用设备当前中英文设置，不包含联系方式或联网操作。

功能键长按达到 `BUTTON_LONG_PRESS_MS`（默认 500ms）进入系统菜单；短按在松手后继续轮换样式、亮度、旋转、网络单位快捷模式。菜单外另外两键保持原有快捷操作。

菜单使用中文分级列表：功能键短按确认，另外两键上下选择，长按方向键连续移动，首尾循环。每页最后一项为“返回”，子页返回保留父页选中位置，主菜单返回退出；菜单不自动超时。功能键长按不会同时触发短按，菜单内长按功能键不执行操作。

系统菜单包含样式切换、亮度调节、屏幕旋转和网络速率单位。亮度提供 10%～100% 十档，并补入当前非整十值；旋转提供 0°/180°；单位提供 MB/Mbps。移动选择不修改设置，确认后生效并标记当前值，保留在子页。原亮度快捷操作仍保持 1% 步进。设置复用 `configChange` 通知与原有配置覆盖规则，不新增本地持久化。

菜单打开期间继续接收监控数据、更新 LED 和处理通信，暂缓自动页面切换及远端显示配置应用；退出时按最新快照和连接状态恢复。未连接时也可进入菜单调整亮度、旋转和单位，切换样式会提示“请先连接监控端”。菜单复用完整画布，临时关闭整秒同步以保证按键响应，退出后恢复主题同步策略。

菜单内事件不会透传给主题；菜单外功能键短按在松手时依次透传 `press`、`release`，其中 `press` 的消费结果决定是否轮换快捷模式。功能键长按由系统保留，不向主题透传。其他两键在菜单外仍透传原始事件。

当前主题可以实现可选的 `on_button_event(button, event_type, snapshot)` 方法监听三枚物理按键。`button` 分别为 `style_previous`、`style_next`、`function`，`event_type` 分别为 `press`、`long_press`、`repeat`、`release`。返回 `True` 表示主题消费该事件，驱动会使用当前快照立即刷新主题；返回 `False` 或不实现该方法时，继续执行设备原有的样式切换、亮度、旋转等默认命令。监听器异常只会上报 `BUTTON:STYLE_EVENT_ERROR`，不会中断设备主循环。
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

可见帧整秒同步由每个 Style 的 `sync_visible_frame_to_second` 布尔属性独立决定。
切换 Style 时，渲染器只把该属性下发给 MicroPython SDK；未声明的旧自定义 Style
默认关闭。开启后，每次渲染只把完整画布复制到 C 层的最新帧邮箱并立即返回；
新画布会覆盖尚未显示的旧画布。原生 FreeRTOS 任务在墙钟整秒前取出最新帧，
重新按已显示帧哈希计算脏区，设置 LCD 窗口并在整秒边界启动第一笔像素 DMA。
Python 不计算目标时间，也不等待边界。FPS、
游戏和测试 Style 默认关闭，普通监控及待机时钟 Style 默认开启。缺少 `fn_lcd`
API 4 的兼容 SPI 固件不支持底层异步整秒同步。
设备端会同步推进所有 `history` 和 `*_history` 固定时间格：某秒没有收到新快照
时复制最近一个值，同一秒内真实数据到达后直接覆盖该保持值，使折线持续滚动且
不改写此前的真实历史数据。

## 独立 USB CDC

固件按 TinyUSB 官方双 CDC 方案在启动时直接枚举两个原生接口：CDC 0 保留给 REPL，CDC 1 专供 PV1 数据。数据接口由独立 `fn_cdc_rx` FreeRTOS 任务持续推进 TinyUSB，C 回调立即读空 FIFO 并写入 32 KB 环形缓冲，再按 PV1 头部与 64 字节物理边界组装到四帧有界队列。全程不再使用 `machine.USBDevice` 的 Python 端点回调。长期缓冲优先从 PSRAM 动态分配；队列和环形缓冲都满时依靠 USB NAK 背压，不覆盖未处理数据。该功能必须连接 ESP32-S3 原生 USB OTG 接口，CH343 等 USB-UART 接口仍属于兼容控制台通道。

- 原生数据 CDC 通过 `_usb_cdc_data → NativeCdcStream → UsbCdcTransport → TransportManager` 接入现有协议。
- USB 枚举、端点重挂、FIFO、半帧超时和完整帧队列全部由固件 C 层处理，Python 只取完整帧并调用 `fn_protocol` C 解析器，LCD 渲染停顿不会中断逐包端点服务。
- 固件没有编译 `_usb_cdc_data` 时才回退到原有内置控制台或 CH343 通道，不再创建存在长期稳定性问题的运行时 Python CDC。
- 如需固定使用 CH343/控制台传输，应把 `USB_DEDICATED_CDC_ENABLED` 设为 `False`。
- 可通过 `config.py` 的 `USB_DEDICATED_CDC_ENABLED` 控制数据通道；C 缓冲容量由板级固件宏 `MICROPY_HW_USB_CDC_DATA_RX_BUFSIZE` 决定。
- PONG 会报告当前 MicroPython SDK 版本及 `sdk_update` 能力。仅原生 USB 传输可以执行 `sdk.bootloader`；设备先返回并刷新结构化成功应答，再通过 MicroPython 调度器延迟调用 `machine.bootloader()`，确保命令处理栈退出后进入 ESP32-S3 ROM USB 下载模式，供 Windows Monitor 无按键刷写完整合并 bin。

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
`auto` 在固件包含 `fn_lcd` API 4 时，让 MicroPython 始终在完整 RAM 画布绘制；
C 固件自动检测并记录脏区，以两块内部 SRAM 条带缓冲交替提取像素，再通过两块
内部 DMA RAM 发送。旧固件会安全回退标准 `machine.SPI.write()`。该优化不改变
Python Style 和 Canvas API；完整原理、
配置方法与对照测试见
[ESP32-S3 MicroPython LCD DMA 渲染原理](../doc/esp32-fix/ESP32-S3_MicroPython_LCD_DMA渲染原理.md)。


## 小屏语言

小屏跟随活动驱动下发的 `display.locale`，支持 `zh-CN` 和 `en-US`。首次绘制前加载独立的 `locale.json`；缺失或损坏默认中文。语言变化时以同目录临时文件替换配置，保存失败仍更新当前会话，重复快照不会反复写 Flash。运行期间断连、增量快照不包含语言字段或字段非法均保留当前语言。系统菜单打开时继续接收快照，退出后应用最新语言并完整重绘，不增加独立语言菜单。

`i18n.py` 和 `locales/` 提供轻量查表翻译。系统菜单、启动和连接提示按稳定键翻译；主题 style（含待机主题）的名称、详情、画面文案和排版保持原样，不参与国际化。`screen_text.py` 对中文显式选择已有字库，SDK API 10 及以上使用十二像素字体，较早版本回退文泉驿；固定区域需要使用实际文本宽度进行裁剪。发布包自动包含语言模块，不包含运行时生成的 `locale.json`。RP2040 源码不受此次接入影响。
