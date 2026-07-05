# LCD 样式插件说明

LCD 渲染由 `dashboard.py` 统一调度，具体布局由 `styles/style_<名称>.py` 插件负责。
默认样式由 `config.py` 中的 `LCD_STYLE` 选择，monitor 也可以在线切换样式。

## 新增样式

1. 在 `styles` 目录创建 `style_<名称>.py`。名称只能包含小写字母、数字和下划线。
2. 样式类必须提供 `create_dirty_regions()`、`draw_visible()` 和 `draw_dirty()`。
3. 模块末尾调用 `register_style("<名称>", 工厂函数)` 完成注册。
4. 将名称加入 monitor 的 `BUILTIN_LCD_STYLES`，随后可通过
   `--lcd-style <名称>` 或 `PICO_MONITOR_LCD_STYLE=<名称>` 在线切换。
5. 横屏样式声明 `width = 320`、`height = 240` 和 `landscape = True`。
6. `font_name` 可以选择 `native`、`screen_2inch` 或
   `screen_2inch_compact`。

`create_dirty_regions()` 返回 `(key, x, y, width, height)` 列表。首次显示由
`draw_visible(canvas, snapshot)` 按条带完整绘制；后续刷新由
`draw_dirty(canvas, key, snapshot)` 只更新动态区域。

## 性能设计原则

性能日志格式如下：

```text
ACK:LCD_FRAME:<version>:TOTAL=...MS:CANVAS=...US:LCD=...US:REGIONS=...:MEMORY_USED=...:MEMORY_TOTAL=...
```

- `CANVAS` 包含样式计算、文字、曲线和 Canvas 绘制时间。
- `LCD` 是将脏区域写入屏幕的时间。
- `REGIONS` 只是区域数量。区域更多但总像素更少，通常仍可能更快。
- 优化时同时观察 `TOTAL`、`CANVAS`、`LCD` 和 `MEMORY_USED`，不要只看单项。

### 静态层与动态层分离

首帧负责绘制外框、标题、分隔线和固定标签。后续帧不要为了更新一个数值而清空、
重画整个面板。

推荐将面板拆成独立动态区域，例如：

```python
@staticmethod
def create_dirty_regions():
    return [
        ("cpu_values", 8, 10, 92, 16),
        ("cpu_history", 8, 31, 88, 35),
        ("network_upload_value", 32, 143, 64, 7),
        ("network_upload_history", 8, 152, 88, 19),
    ]
```

`draw_dirty()` 开始时渲染器会清空当前脏矩形，因此矩形必须覆盖旧内容的最大范围，
而不只是新文字的实际宽度。这样文字变短、曲线下降或状态消失时不会留下旧像素。

如果动态矩形穿过固定标签或分隔线，`draw_dirty()` 必须重新绘制被清除的那一部分；
更好的做法是调整矩形边界，使其避开静态元素。

外框颜色随健康等级、连接状态或告警相位变化时，外框属于动态内容，不能静态化。
磁盘健康闪烁和连接状态面板通常需要保留完整区域刷新。

### 按字段选择脏区域

不要只比较整个 `cpu`、`network` 或 `disk` 字典。历史数组变化不应触发数值区域刷新，
单个速率变化也不应重画另一条曲线。

```python
if previous_cpu.get("history") != current_cpu.get("history"):
    selected.append(region_map["cpu_history"])

if previous_network.get("upload_bps") != current_network.get("upload_bps"):
    selected.append(region_map["network_upload_value"])
```

实现 `select_dirty_regions(previous, current)` 时应遵循：

- 相同数据返回空列表。
- 数值、历史、状态和容量分别比较。
- 显示单位变化时，同时刷新依赖该单位的区域。
- 告警闪烁即使数据未变化，也要刷新对应动态区域。
- `force=True` 会使用 `create_dirty_regions()`，所以列表必须包含所有动态内容。

## Canvas 高效接口

优先使用 Canvas 已封装的原生 `framebuf` 操作：

- 大块背景使用 `clear()` 或 `fill_rect()`。
- 水平、垂直线仍调用 `canvas.line()`；Canvas 会自动选择原生 `hline()`/`vline()`。
- 同色面积图使用 `fill_polygon()`。
- 按采样值着色的历史图使用 `draw_columns()`，不要在 style 中逐列调用 `line()`。
- 文字统一使用 `canvas.text()`，不要自行创建 RGB565 字符位图。

Canvas 的自定义字体使用 1-bit MONO 字形和 RGB565 palette。字形可以跨颜色复用，
固定字符串会在受限预算内缓存；包含数字的动态字符串不会进入整字符串缓存，以避免
持续分配和堆碎片。

不要在 style 中建立大尺寸 RGB565 静态背景缓存。RP2040 堆空间有限，一张
`320 × 40` RGB565 条带就需要 25,600 字节，容易引发连续内存分配失败。

## 历史图规则

历史图通常是 `CANVAS` 的主要热点：

- 优先把同色连续采样合并为一个原生多边形。
- 必须逐值着色时，将 `(x, y, color)` 交给 `canvas.draw_columns()`。
- 避免在双层 Python 循环中调用 `pixel()` 或逐像素 `fill_rect()`。
- 坐标计算优先使用整数和定点运算，避免 RP2040 上大量浮点除法。
- 限制采样数量到实际显示宽度；多个样本映射到同一列时应先聚合。
- 无数据或只有一个样本时尽早返回。

## 内存与分配约束

MicroPython 的可用总内存不等于最大连续可分配内存。即使日志仍显示数十 KB 空闲，
堆碎片也可能导致小块分配出现 `MemoryError`。

绘图热路径中应避免：

- 每帧创建大 `bytearray`、RGB565 FrameBuffer 或完整背景图。
- 对历史数组反复切片。
- 无上限的字符串、字形或颜色缓存。
- 缓存满后持续淘汰和重建动态内容。
- 为每一列创建元组、列表和临时多边形。

能复用的数组和缓冲区应在 Canvas 或样式初始化阶段创建。缓存必须有明确的项数或字节
上限，切换样式时应能够释放。

## 优化与验收流程

1. 先记录至少 20 个稳定帧的 `TOTAL/CANVAS/LCD/MEMORY_USED`。
2. 给疑似热点的 `_draw_*`、文字或历史图增加临时微秒计时。
3. 优先减少绘制工作和脏矩形面积，再考虑底层原生代码或 DMA。
4. 分别测试首帧、常规增量帧、强制刷新、样式切换和旋转后的完整重绘。
5. 连续运行数分钟，确认 `MEMORY_USED` 稳定且没有 `MemoryError`。
6. 验证文字由长变短、历史值由高变低、告警闪烁和状态颜色切换没有残影。

DMA 只能隐藏 LCD 传输时间，不能减少 `CANVAS`。当 `CANVAS` 仍明显大于 `LCD` 时，
优先优化样式算法和脏矩形；只有 LCD 已成为主要占比时，双缓冲 DMA 才通常值得引入。

## 测试要求

新增或修改样式至少应覆盖：

- `select_dirty_regions()` 只返回实际变化的 key。
- 历史变化不会刷新无关数值区域。
- 单方向网络变化不会刷新另一方向。
- 健康告警在数据不变时仍按帧刷新。
- 强制刷新包含所有动态区域。
- 字体缓存、历史图颜色和动态区域边界相关回归测试。
