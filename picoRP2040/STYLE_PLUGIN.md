# LCD 样式插件说明

LCD 渲染由 `dashboard.py` 统一调度，具体布局由 `style_<名称>.py` 插件负责。
当前原有界面已经迁移为 `style_default.py`，并由 `config.py` 中的
`LCD_STYLE = "default"` 选中。

新增样式时，可复制 `style_default.py` 并完成以下调整：

1. 将文件命名为 `style_<名称>.py`，名称只能包含小写字母、数字和下划线。
2. 样式类必须提供 `create_dirty_regions()`、`draw_visible()` 和 `draw_dirty()`。
3. 模块末尾调用 `register_style("<名称>", 工厂函数)` 完成注册。
4. 将 `config.py` 的 `LCD_STYLE` 修改为新名称。

`create_dirty_regions()` 返回 `(键, x, y, 宽度, 高度)` 列表；首次显示由
`draw_visible(canvas, snapshot)` 按条带完整绘制，后续刷新由
`draw_dirty(canvas, key, snapshot)` 只更新动态区域。
