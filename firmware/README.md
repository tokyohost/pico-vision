# 原生加速固件

`fn_canvas` 是可选的 MicroPython 用户 C 模块。业务代码通过
`canvas_backend.Canvas` 使用策略选择器：`canvasC.native_canvas_supported()` 会校验
模块版本和完整方法集合；匹配时选择 C 适配器，不匹配或不存在时选择未经修改的
`canvas.Canvas` Python/FrameBuffer 实现。

`fn_protocol` 是可选的 PV1 帧解析与 CRC 原生模块。`protocolC.py` 会校验
接口版本；匹配时使用 C 完成帧头、长度、填充及 CRC 校验，不匹配或不存在时自动
回退到原有 Python 解析器。JSON 仍由固件自带的 `ujson` 解析。

在 `micropython/ports/rp2` 目录构建 Raspberry Pi Pico UF2：

```sh
make BOARD=RPI_PICO \
  USER_C_MODULES=modules/micropython.cmake
```

生成文件位于 `micropython/ports/rp2/build-RPI_PICO/firmware.uf2`。

设备侧可执行以下检查：

```python
from canvasC import native_canvas_supported
from canvas_backend import canvas_backend_name

print(native_canvas_supported(), canvas_backend_name())

from protocolC import native_protocol_supported
print(native_protocol_supported())
```

返回 `True` 表示当前 UF2 已启用且接口版本兼容；返回 `False` 表示会自动回退。

业务样式通过 `Canvas.draw_line_chart(definition, values)` 提交图表定义和原始数据。
当前定义支持位置、尺寸、固定或自动最大值、折线颜色、实心填充、数值颜色区间以及
点阵背景；C 策略负责全部坐标计算，Python 策略仅用于旧固件兼容回退。

```python
canvas.draw_line_chart({
    "x": 8, "y": 20, "width": 90, "height": 35,
    "maximum": 100, "color": 0xFFFF, "filled": True,
    "regions": ((50, 0x6607), (80, 0xE507), (101, 0xF36D)),
    "grid_step_x": 12, "grid_step_y": 7, "grid_color": 0x4208,
}, history_values)
```

`maximum` 设为 `0` 时由后端根据数据自动缩放；`regions` 按上限升序定义，每项为
`(上限, RGB565颜色)`。关闭实心或点阵时分别设置 `filled=False` 或将点阵步距设为 `0`。

无法用固定阈值表达颜色规则时，可设置 `color_callback`。回调接收当前插值数值并返回
RGB565 颜色；`color_cache_step` 控制 C 端哈希缓存粒度，默认为 `1`，同一整数区间只
调用一次 Python。设为 `0` 会关闭缓存并逐列回调，通常仅用于必须精确到小数的场景。

```python
def history_color(value):
    """根据业务规则返回历史图当前数值对应的颜色。"""
    return 0xF800 if value >= 90 else 0x07E0

definition["color_callback"] = history_color
definition["color_cache_step"] = 1
canvas.draw_line_chart(definition, history_values)
```
