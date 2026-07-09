#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.
#
#  Any project, software, or derivative work that uses, modifies, links to,
#  or incorporates this software must make its complete source code publicly
#  available under the same license.
#
#  This software is provided "as is", without warranty of any kind.

"""封装 Windows PDH 计数器采样使用的 ctypes 数据结构。"""

import ctypes


class _PdhFormattedValueUnion(ctypes.Union):
    """保存 Windows PDH 格式化计数器的联合值。"""

    _fields_ = [("double_value", ctypes.c_double), ("large_value", ctypes.c_longlong)]

class _PdhFormattedValue(ctypes.Structure):
    """描述 Windows PDH 格式化计数器值及状态。"""

    _anonymous_ = ("value",)
    _fields_ = [("status", ctypes.c_ulong), ("value", _PdhFormattedValueUnion)]

class _PdhFormattedItem(ctypes.Structure):
    """描述 Windows PDH 通配符实例名称及其格式化值。"""

    _fields_ = [("name", ctypes.c_wchar_p), ("value", _PdhFormattedValue)]

