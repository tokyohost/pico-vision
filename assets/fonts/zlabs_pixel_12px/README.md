# Z工坊像素黑体 12px

来源：https://github.com/Astro-2539/ZLabs-Pixel-12px

采用作者发布的 `Build_20260519` 大陆字形版 `ZLabsPixel_12px_M_CN.ttf`。原字体及生成点阵依照同目录 `LICENSE-OFL.txt` 的 OFL-1.1 授权发布，不适用项目代码的商业使用限制。

固件包沿用现有 ASCII + GB2312 字符索引，共 7,540 个字形，不代表原字体的全部 Unicode 覆盖范围。字形高度 12px，ASCII 步进 6px，其他字符步进 12px；索引之外的字符沿用固件问号回退。

在工作区执行 `python pico-project/tools/build_zlabs_pixel_font.py` 重新生成点阵，需要 Pillow。生成文件为 `micropython/ports/rp2/modules/fn_canvas/font_zlabs_pixel_data.c`，点阵占 180,960 字节只读 Flash，不整体加载到 Python 堆。

重新编译启用 `FN_CANVAS_BUILTIN_FONTS` 的 MicroPython 固件（fn_canvas API 10），再部署对应 Pico 或 ESP32-S3 SDK。旧固件需要更新后才能使用新字体。

```python
canvas.text(8, 8, "你好，世界！CPU 88%", WHITE, font_name="zlabs_pixel_12px")
canvas.set_font("zlabs_pixel_12px")
```

字体测试样式名为 `zlabs_pixel_test`，中文名称为“Z工坊12px字体测试”，可通过现有样式选择功能加载。测试页为 240×320 竖屏，包含 1 倍和 2 倍显示、中文、英文数字、标点及紧凑字体对照；刷新区域使用 40px 条带。
