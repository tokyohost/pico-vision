# ESP32-S3 MicroPython LCD DMA 渲染原理

## 1. 设计目标

本方案保持 Python Style 是唯一界面扩展入口。开发者继续使用 `canvas.text()`、
`canvas.fill_rect()`、`canvas.line()` 等接口编写布局，不需要理解 ESP-IDF、DMA
描述符或 ST7789 SPI 事务。

原生代码只负责用户无需感知的像素搬运，不负责布局、数据格式化、脏区选择和
Style 生命周期。这样可以同时满足以下目标：

- 保留 MicroPython 界面开发的简单性。
- 保留现有内置和自定义 Style 的兼容性。
- 让 MicroPython 始终面对完整 RAM 画布，不再为每个条带重复执行样式绘制。
- 由 C 固件自动检测、记录和合并脏区，样式无需维护手工脏区清单。
- 使用两块内部 SRAM 条带缓冲提取非连续矩形，避免热路径动态分配。
- 避免 Python 渲染线程在每个 SPI 分块完成后重新竞争 GIL。
- 允许通过配置立即切回升级前的标准 `machine.SPI.write()` 路径。

## 2. 分层边界

```mermaid
flowchart TD
    STYLE["Python Style<br/>布局、格式化、脏区"] --> CANVAS["Canvas 公共接口"]
    CANVAS --> PY["Python Canvas 兼容实现"]
    CANVAS --> CC["fn_canvas C 图元加速"]
    PY --> BUFFER["完整 RGB565 RAM 画布<br/>240×320×2 字节"]
    CC --> BUFFER
    BUFFER --> RENDERER["Python DashboardRenderer<br/>每帧提交完整画布"]
    RENDERER --> SWITCH{"LCD_TRANSFER_BACKEND"}
    SWITCH -->|legacy| LEGACY["machine.SPI.write"]
    SWITCH -->|native_dma| DIRTY["C 瓦片哈希比较<br/>脏矩形合并"]
    DIRTY --> STRIP["内部 SRAM 条带 A/B<br/>交替提取矩形行"]
    STRIP --> DMAA["DMA 缓冲 A"]
    STRIP --> DMAB["DMA 缓冲 B"]
    DMAA --> SPI["SPI2 / ST7789"]
    DMAB --> SPI
    LEGACY --> SPI
```

以下部分继续使用 Python：

- Style 插件发现、加载和切换；
- 数据格式化和显示文本生成；
- Canvas 公共 API；
- 完整画布绘制、帧发布和性能统计；
- LCD 初始化、旋转、背光和截图流程。

以下部分由 `fn_lcd` 原生模块完成：

- 初始化时接收分辨率、显存偏移、SPI 和 GPIO 脚位方案；
- 分配两块内部 DMA RAM 和两块内部 SRAM 条带缓冲；
- 按瓦片比较完整画布，并记录、横向合并和纵向合并脏矩形；
- 从完整 Canvas 按行提取脏矩形，交替使用两块条带缓冲；
- 使用现有 `machine.SPI` 的设备句柄排队 DMA 事务；
- 等待事务完成并维护累计字节数与事务数。

## 3. 为什么不把 Style 改成 C

Style 的核心价值是表达界面意图，而不是搬运像素。把 Style 改成 C 会增加编译、
烧录和内存生命周期管理成本，也会破坏运行期插件能力。

当前性能数据中 Canvas 绘制约为几十至一百毫秒，而 LCD 路径曾达到一秒以上。
因此优化边界应停在 Canvas 图元和 LCD 传输后端，不应侵入 Style 层。

## 4. 旧传输路径

`legacy` 后端保留原有代码语义：

```python
self.spi.write(pixels)
```

ESP32 MicroPython 的硬件 SPI 驱动会把较大的缓冲区拆成最多 4092 字节的事务。
等待每笔事务完成时，驱动会释放 GIL；存在两个 Python 线程时，通信线程可能先
获得 GIL，使渲染线程在一次 `show_region()` 内反复等待。当前性能统计包围整个
`show_region()`，所以这些 GIL 等待也会累计到 `LCD_US`。

该路径的价值是兼容标准固件和提供可靠回退，不作为 ESP32-S3 的目标性能路径。

## 5. 原生 DMA 传输路径

`native_dma` 后端初始化两块 4092 字节内部 DMA 缓冲区和两块
`逻辑宽度 × LCD_STRIP_HEIGHT × 2` 的内部 SRAM 条带缓冲。4092 与当前
`machine.SPI` 总线默认单笔事务上限一致，不修改屏幕接线和 SPI 时钟。C 固件
另外在 PSRAM 保存已显示与待提交瓦片哈希，以及固定容量脏矩形表。

一次区域写入按以下顺序执行：

1. MicroPython 在完整 RGB565 画布上执行一次 `draw_visible()`。
2. `fn_lcd.dirty_regions()` 比较瓦片哈希并返回合并后的脏矩形。
3. Python 只为这些矩形设置 ST7789 列窗口、行窗口和显存写入命令。
4. C 固件从完整画布按行复制到条带 A/B，两块条带循环交替使用。
5. 每块条带再由 DMA 缓冲 A/B 分块排队；DMA 发送当前块时 CPU 准备下一块。
6. 所有矩形发送成功后提交待定哈希；任一事务失败则丢弃待定哈希，下一帧重试。

原生函数执行期间不调用 `MP_THREAD_GIL_EXIT`。这样能够保证一个区域内的 DMA
事务连续完成，不会在每个 4092 字节边界让另一个 Python 线程长期抢占。底层
FreeRTOS、Wi-Fi、USB 和中断任务不依赖 MicroPython GIL，仍可由系统调度。

## 6. 后端开关

`config.py` 提供：

```python
LCD_TRANSFER_BACKEND = "auto"
LCD_DMA_CHUNK_SIZE = 4092
LCD_STRIP_HEIGHT = 40
LCD_DIRTY_TILE_WIDTH = 16
LCD_DIRTY_TILE_HEIGHT = 8
RENDER_FRAME_POLICY = "latest"  # 也可设为 "block"
```

支持三种模式：

| 配置 | 行为 | 适用场景 |
| --- | --- | --- |
| `legacy` | 始终使用标准 `machine.SPI.write()` | 对照测试和紧急回退 |
| `native_dma` | 强制使用 `fn_lcd`，模块或内存异常直接报错 | 固件能力验收 |
| `auto` | 优先使用 `fn_lcd`，不可用时回退 `legacy` | 默认部署 |

也可以在设备根目录的 `runtime_config.json` 中覆盖：

```json
{
  "LCD_TRANSFER_BACKEND": "legacy"
}
```

切换后需要软重启，因为 DMA 缓冲和 LCD 设备在启动阶段创建。

`RENDER_FRAME_POLICY=latest` 会覆盖尚未消费的旧快照，只保留最新帧；`block` 在
待处理槽占用时阻塞发布者，保证不丢帧。同步回退模式天然阻塞。两种策略都不会
允许通信线程与渲染线程同时修改同一完整画布。

## 7. 启动与性能日志

启动时输出实际后端：

```text
BOOT:LCD_TRANSFER_BACKEND:NATIVE_DMA
```

开发模式帧日志增加：

```text
LCD_BACKEND=NATIVE_DMA
```

`auto` 回退后会显示 `LEGACY`，因此测试时应以日志中的实际值为准，而不是只看
配置文件。

## 8. 推荐对照测试

固定同一块屏幕、同一 Style、同一 Monitor 数据和 40 MHz SPI，分别采集至少
二十个稳定帧：

1. `legacy + SYNC`；
2. `native_dma + SYNC`；
3. `legacy + THREAD`；
4. `native_dma + THREAD`。

记录以下指标的平均值、P95 和最大值：

- `TOTAL`；
- `CANVAS`；
- `LCD`；
- `SCHEDULE`；
- `SLOWEST_REGION`；
- `DROPPED_FRAMES` 的增量。

如果 `native_dma` 生效，预期 `CANVAS` 基本不变，`LCD` 和
`SLOWEST_REGION` 显著下降。若 `LCD` 仍接近一秒，应继续核对实际 SPI 时钟、
供电、接线、区域字节数以及是否发生 `auto` 回退。

## 9. 约束与后续方向

- 当前 DMA 双缓冲容量受既有 SPI 总线 4092 字节单笔上限约束。
- 脏区精度由瓦片尺寸决定；默认十六乘八像素，在区域数量和额外传输间折中。
- 原生后端当前同步等待一个区域完成，不是完整的 CPU0 原生渲染任务。
- Style 中大量逐像素 Python 循环仍会反映在 `CANVAS_US`，应优先使用批量 Canvas API。
- 如果后续需要更大的 DMA 事务，应统一调整 SPI 总线 `max_transfer_sz`、内部 RAM
  预算和压力测试，不能只放大 Python 配置值。
- 不计划把 Style 改写为 C；后续优化仍应保持 Python Style API 稳定。
