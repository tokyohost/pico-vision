"""macOS 原生通知、剪贴板和系统唤醒监听，原生框架按需加载。"""

import logging
import threading
import uuid


LOGGER = logging.getLogger("pico-monitor.macos")


class MacOsNotifications:
    """使用 UserNotifications 发送系统通知，拒绝授权时保留日志诊断。"""

    def __init__(self):
        """初始化授权状态，不在构造阶段弹出系统授权对话框。"""
        self._center = None
        self._allowed = False

    def start(self):
        """在 Cocoa 主循环启动后请求通知授权，失败不影响业务。"""
        from UserNotifications import (
            UNAuthorizationOptionAlert, UNAuthorizationOptionSound,
            UNUserNotificationCenter,
        )
        self._center = UNUserNotificationCenter.currentNotificationCenter()

        def authorized(allowed, error):
            """记录异步授权结果，不在系统回调线程操作 GUI。"""
            self._allowed = bool(allowed) and error is None
            if not self._allowed:
                LOGGER.info("系统通知未授权，通知将仅写入日志")

        self._center.requestAuthorizationWithOptions_completionHandler_(
            UNAuthorizationOptionAlert | UNAuthorizationOptionSound, authorized,
        )

    def send(self, message, title):
        """提交一次性系统通知，不使用 macOS 不支持的 pystray.notify。"""
        LOGGER.info("%s：%s", title, message)
        if self._center is None or not self._allowed:
            return False
        from UserNotifications import UNMutableNotificationContent, UNNotificationRequest
        content = UNMutableNotificationContent.alloc().init()
        content.setTitle_(title)
        content.setBody_(message)
        request = UNNotificationRequest.requestWithIdentifier_content_trigger_(
            str(uuid.uuid4()), content, None,
        )

        def completed(error):
            """记录异步通知错误，避免静默丢失诊断信息。"""
            if error is not None:
                LOGGER.warning("系统通知发送失败：%s", error)

        self._center.addNotificationRequest_withCompletionHandler_(request, completed)
        return True


class MacOsWakeObserver:
    """监听 NSWorkspace 唤醒通知，复用现有 worker 重探测协议。"""

    def __init__(self, callback):
        """保存唤醒处理函数，原生监听只在 start 时注册。"""
        self._callback = callback
        self._center = None
        self._token = None
        self._handler = None

    def start(self):
        """在主队列注册系统唤醒通知，并持有回调避免桥接对象回收。"""
        if self._token is not None:
            return
        from AppKit import NSWorkspace, NSWorkspaceDidWakeNotification
        from Foundation import NSOperationQueue
        self._center = NSWorkspace.sharedWorkspace().notificationCenter()

        def woke(notification):
            """系统恢复后通知后台丢弃失效连接并重扫设备。"""
            del notification
            self._callback()

        self._handler = woke
        self._token = self._center.addObserverForName_object_queue_usingBlock_(
            NSWorkspaceDidWakeNotification, None, NSOperationQueue.mainQueue(), woke,
        )

    def stop(self):
        """取消监听并释放原生回调引用，支持重复关闭。"""
        if self._center is not None and self._token is not None:
            self._center.removeObserver_(self._token)
        self._token = None
        self._handler = None
        self._center = None


def copy_text(text):
    """通过主线程安全的 AppKit 操作写入剪贴板，供 WKWebView 兜底。"""
    from AppKit import NSPasteboard, NSPasteboardTypeString
    from PyObjCTools.AppHelper import callAfter
    completed = threading.Event()
    accepted = []

    def write():
        """在 Cocoa 主队列清空并写入纯文本剪贴板。"""
        try:
            board = NSPasteboard.generalPasteboard()
            board.clearContents()
            accepted.append(bool(board.setString_forType_(text, NSPasteboardTypeString)))
        finally:
            completed.set()

    if threading.current_thread() is threading.main_thread():
        write()
    else:
        callAfter(write)
    if not completed.wait(5) or not accepted or not accepted[0]:
        raise RuntimeError("写入 macOS 剪贴板失败")
