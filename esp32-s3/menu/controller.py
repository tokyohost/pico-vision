"""管理系统菜单页面、选择位置与设置确认。"""

from i18n import t
import time


class SystemMenu:
    """维护独立于硬件和渲染线程的菜单状态。"""

    PAGES = (("style", "menu.style"), ("brightness", "menu.brightness"),
             ("rotation", "menu.rotation"), ("network_unit", "menu.network_unit"),
             ("system_info", "menu.system_info"), ("about", "menu.about"))

    def __init__(self):
        """初始化关闭状态和页面栈。"""
        self.stack = []
        self.message = ""
        self._next_refresh = None

    @property
    def active(self):
        """返回菜单是否打开。"""
        return bool(self.stack)

    def open(self):
        """打开主菜单并选择第一项。"""
        self.stack = [{"key": "root", "title": t('menu.title'),
                       "items": [(value, t(key)) for value, key in self.PAGES] + [(None, t('menu.back'))],
                       "selected": 0, "current": None, "type": "settings"}]
        self.message = ""
        self._next_refresh = None

    def move(self, direction):
        """在当前页面首尾循环移动选择。"""
        page = self.stack[-1]
        page["selected"] = (page["selected"] + direction) % len(page["items"])
        self.message = ""

    def confirm(self, host, snapshot):
        """进入子页、应用设置或返回父页。"""
        page = self.stack[-1]
        value, label = page["items"][page["selected"]]
        self.message = ""
        if value is None:
            self.stack.pop()
        elif page.get("type") == "detail":
            return
        elif page.get("type") == "information":
            field = next(row for row in page["fields"] if row[0] == value)
            self.stack.append({"key": page["key"], "type": "detail", "field": value,
                               "title": field[1], "items": self._detail_items(host, field[2]),
                               "selected": 0, "current": None})
        elif page["key"] == "root":
            try:
                if value in ("system_info", "about"):
                    fields = host.system_menu_information(value)
                    self.stack.append({"key": value, "type": "information", "title": label,
                                       "fields": fields, "items": self._information_items(fields),
                                       "selected": 0, "current": None})
                    self._next_refresh = None
                    return
                items, current = host.system_menu_options(value)
            except (ImportError, MemoryError, OSError, TypeError, ValueError):
                self.message = t('menu.load_failed')
                return
            selected = next((i for i, item in enumerate(items)
                             if item[0] == current), 0)
            self.stack.append({"key": value, "title": label,
                               "type": "settings",
                               "items": list(items) + [(None, t('menu.back'))],
                               "selected": selected, "current": current})
        else:
            self.message = host.apply_system_menu_setting(page["key"], value, snapshot) or ""
            if not self.message:
                page["current"] = value

    def _information_items(self, fields):
        """构造摘要列表，完整原文另外保留供详情页使用。"""
        return [(key, label + ": " + value.replace("\n", " "))
                for key, label, value in fields] + [(None, t("menu.back"))]

    def _detail_items(self, host, text):
        """使用渲染线程的实际字体度量生成可滚动正文行。"""
        return list(enumerate(host.system_menu_detail_lines(text))) + [(None, t("menu.back"))]

    def refresh(self, host, now):
        """仅在系统信息可见时每秒采样，保留选中位置并报告变化。"""
        if not self.active or self.stack[-1]["key"] != "system_info":
            self._next_refresh = None
            return False
        ticks_diff = getattr(time, "ticks_diff", lambda a, b: a - b)
        ticks_add = getattr(time, "ticks_add", lambda a, b: a + b)
        if self._next_refresh is None:
            self._next_refresh = ticks_add(now, 1000)
            return False
        if ticks_diff(now, self._next_refresh) < 0:
            return False
        self._next_refresh = ticks_add(now, 1000)
        page = next(item for item in self.stack if item.get("type") == "information")
        updates = {row[0]: row for row in host.system_menu_information("system_info", dynamic=True)}
        fields = [updates.get(row[0], row) for row in page["fields"]]
        if fields == page["fields"]:
            return False
        previous = {row[0]: row[2] for row in page["fields"]}
        page["fields"] = fields
        page["items"] = self._information_items(fields)
        detail = self.stack[-1]
        if detail.get("type") == "detail":
            field = next(row for row in fields if row[0] == detail["field"])
            if field[2] == previous[field[0]]:
                return False
            was_back = detail["selected"] == len(detail["items"]) - 1
            detail["items"] = self._detail_items(host, field[2])
            detail["selected"] = (len(detail["items"]) - 1 if was_back else
                                  min(detail["selected"], len(detail["items"]) - 2))
        return True

    def view(self):
        """返回可安全复制到渲染线程的纯数据页面。"""
        if not self.active:
            return None
        page = dict(self.stack[-1])
        page["message"] = self.message
        return page
