"""Windows 图形界面的 IntelliJ IDEA 深色主题。"""

import os


IDEA_COLORS = {
    "window": "#1E1F22",
    "panel": "#2B2D30",
    "panel_hover": "#393B40",
    "field": "#1E1F22",
    "border": "#43454A",
    "border_focus": "#3574F0",
    "text": "#DFE1E5",
    "muted": "#9DA0A8",
    "disabled": "#6F737A",
    "accent": "#3574F0",
    "accent_hover": "#467FF2",
    "selection": "#2F65CA",
    "success": "#6AAB73",
    "warning": "#CF8E6D",
    "danger": "#F75464",
}

IDEA_FONT = ("Microsoft YaHei UI", 10)
IDEA_MONO_FONT = ("Consolas", 10)


def _configure_windows_title_bar(window):
    """在受支持的 Windows 版本上启用原生深色标题栏。"""
    if os.name != "nt":
        return
    try:
        import ctypes

        window.update_idletasks()
        window_handle = window.winfo_id()
        enabled = ctypes.c_int(1)
        # Windows 11 使用属性 20，较新的 Windows 10 使用属性 19。
        for attribute in (20, 19):
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                window_handle,
                attribute,
                ctypes.byref(enabled),
                ctypes.sizeof(enabled),
            )
            if result == 0:
                break
    except (AttributeError, OSError, RuntimeError):
        # 标题栏装饰不影响窗口功能，不支持时保留系统默认样式。
        return


def apply_idea_theme(window):
    """向指定 Tk 窗口应用统一的 IntelliJ IDEA Darcula 风格。"""
    import tkinter as tk
    from tkinter import ttk

    colors = IDEA_COLORS
    window.configure(background=colors["window"])
    window.option_add("*Font", IDEA_FONT)
    window.option_add("*Background", colors["window"])
    window.option_add("*Foreground", colors["text"])
    window.option_add("*activeBackground", colors["panel_hover"])
    window.option_add("*activeForeground", colors["text"])
    window.option_add("*selectBackground", colors["selection"])
    window.option_add("*selectForeground", colors["text"])
    window.option_add("*highlightBackground", colors["border"])
    window.option_add("*highlightColor", colors["border_focus"])
    window.option_add("*insertBackground", colors["text"])
    window.option_add("*troughColor", colors["field"])
    window.option_add("*Text.Background", colors["field"])
    window.option_add("*Text.Foreground", colors["text"])
    window.option_add("*Text.relief", tk.FLAT)
    window.option_add("*Text.borderWidth", 1)
    window.option_add("*Entry.Background", colors["field"])
    window.option_add("*Entry.Foreground", colors["text"])
    window.option_add("*Button.Background", colors["panel"])
    window.option_add("*Button.Foreground", colors["text"])
    window.option_add("*Button.relief", tk.FLAT)
    window.option_add("*Button.borderWidth", 0)

    style = ttk.Style(window)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=colors["window"], foreground=colors["text"], font=IDEA_FONT)
    style.configure("TFrame", background=colors["window"])
    style.configure("Panel.TFrame", background=colors["panel"])
    style.configure("TLabel", background=colors["window"], foreground=colors["text"])
    style.configure("Muted.TLabel", background=colors["window"], foreground=colors["muted"])
    style.configure(
        "Title.TLabel",
        background=colors["window"],
        foreground=colors["text"],
        font=("Microsoft YaHei UI", 18, "bold"),
    )
    style.configure(
        "Hint.TLabel",
        background=colors["window"],
        foreground=colors["muted"],
    )
    style.configure(
        "TButton",
        background=colors["panel"],
        foreground=colors["text"],
        bordercolor=colors["border"],
        lightcolor=colors["border"],
        darkcolor=colors["border"],
        padding=(12, 7),
        relief=tk.FLAT,
    )
    style.map(
        "TButton",
        background=[
            ("disabled", colors["window"]),
            ("pressed", colors["selection"]),
            ("active", colors["panel_hover"]),
        ],
        foreground=[("disabled", colors["disabled"])],
        bordercolor=[("focus", colors["border_focus"])],
    )
    style.configure(
        "Primary.TButton",
        background=colors["accent"],
        foreground="#FFFFFF",
        bordercolor=colors["accent"],
        padding=(16, 8),
    )
    style.map(
        "Primary.TButton",
        background=[
            ("disabled", colors["panel_hover"]),
            ("pressed", colors["selection"]),
            ("active", colors["accent_hover"]),
        ],
        foreground=[("disabled", colors["disabled"])],
    )
    style.configure("Footer.TButton", padding=(16, 8))
    style.configure(
        "TLabelframe",
        background=colors["window"],
        bordercolor=colors["border"],
        lightcolor=colors["border"],
        darkcolor=colors["border"],
        relief=tk.SOLID,
        borderwidth=1,
    )
    style.configure(
        "TLabelframe.Label",
        background=colors["window"],
        foreground=colors["text"],
        font=("Microsoft YaHei UI", 10, "bold"),
    )
    style.configure("Card.TLabelframe", background=colors["panel"], bordercolor=colors["border"])
    style.configure(
        "Card.TLabelframe.Label",
        background=colors["panel"],
        foreground=colors["text"],
        font=("Microsoft YaHei UI", 11, "bold"),
    )
    style.configure("Card.TLabel", background=colors["panel"], foreground=colors["text"])
    style.configure("Card.TFrame", background=colors["panel"])

    field_options = {
        "fieldbackground": colors["field"],
        "background": colors["field"],
        "foreground": colors["text"],
        "bordercolor": colors["border"],
        "lightcolor": colors["border"],
        "darkcolor": colors["border"],
        "insertcolor": colors["text"],
        "padding": (7, 6),
    }
    for style_name in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(style_name, **field_options)
        style.map(
            style_name,
            fieldbackground=[
                ("readonly", colors["field"]),
                ("disabled", colors["window"]),
            ],
            foreground=[("disabled", colors["disabled"])],
            bordercolor=[("focus", colors["border_focus"])],
            arrowcolor=[
                ("disabled", colors["disabled"]),
                ("!disabled", colors["muted"]),
            ],
        )

    style.configure("TCheckbutton", background=colors["window"], foreground=colors["text"])
    style.map(
        "TCheckbutton",
        background=[("active", colors["window"])],
        foreground=[("disabled", colors["disabled"])],
        indicatorcolor=[
            ("selected", colors["accent"]),
            ("!selected", colors["field"]),
        ],
    )
    style.configure(
        "Treeview",
        background=colors["field"],
        fieldbackground=colors["field"],
        foreground=colors["text"],
        bordercolor=colors["border"],
        rowheight=28,
    )
    style.map(
        "Treeview",
        background=[("selected", colors["selection"])],
        foreground=[("selected", "#FFFFFF")],
    )
    style.configure(
        "Treeview.Heading",
        background=colors["panel"],
        foreground=colors["muted"],
        bordercolor=colors["border"],
        padding=(8, 7),
        relief=tk.FLAT,
    )
    style.map("Treeview.Heading", background=[("active", colors["panel_hover"])])
    style.configure(
        "TScrollbar",
        background=colors["panel_hover"],
        troughcolor=colors["window"],
        bordercolor=colors["window"],
        arrowcolor=colors["muted"],
        relief=tk.FLAT,
    )
    style.map("TScrollbar", background=[("active", colors["disabled"])])
    style.configure(
        "TProgressbar",
        background=colors["accent"],
        troughcolor=colors["field"],
        bordercolor=colors["field"],
        lightcolor=colors["accent"],
        darkcolor=colors["accent"],
    )
    style.configure(
        "Horizontal.TScale",
        background=colors["panel"],
        troughcolor=colors["field"],
    )
    _configure_windows_title_bar(window)
    return style
