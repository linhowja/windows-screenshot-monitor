"""Windows session and power events for the Phase 4 client.

This module owns the capture state machine and a hidden message window.
The window is only an event receiver. It is not a user interface.
"""

from __future__ import annotations

import logging
import sys
import threading

WM_POWERBROADCAST = 0x0218
WM_WTSSESSION_CHANGE = 0x02B1
NOTIFY_FOR_THIS_SESSION = 0
DEVICE_NOTIFY_WINDOW_HANDLE = 0
HWND_MESSAGE = -3

WTS_SESSION_LOGON = 0x5
WTS_SESSION_LOGOFF = 0x6
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
WTS_SESSION_DESKTOP_READY = 0xF

PBT_APMSUSPEND = 0x0004
PBT_APMRESUMECRITICAL = 0x0006
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012

WTS_CURRENT_SERVER_HANDLE = 0
WTS_CURRENT_SESSION = 0xFFFFFFFF
WTS_CONNECT_STATE = 8
WTS_SESSION_INFO_EX = 25
WTS_ACTIVE = 0
WTS_SESSIONSTATE_LOCK = 0
WTS_SESSIONSTATE_UNLOCK = 1

recovery_trigger = threading.Event()
_listener_started = False
_listener_lock = threading.Lock()


class ClientState:
    """Capture is enabled only when every interactive condition is true."""

    def __init__(self, enabled: bool = False) -> None:
        self._lock = threading.Lock()
        self.logged_on = enabled
        self.session_unlocked = enabled
        self.desktop_ready = enabled
        self.system_awake = enabled
        self.changed = threading.Event()
        if enabled:
            self.changed.set()

    @property
    def capture_enabled(self) -> bool:
        with self._lock:
            return self._enabled_locked()

    def _enabled_locked(self) -> bool:
        return (
            self.logged_on
            and self.session_unlocked
            and self.desktop_ready
            and self.system_awake
        )

    def wait_until_enabled(self, timeout: float | None = None) -> bool:
        if self.capture_enabled:
            return True
        self.changed.clear()
        if self.capture_enabled:
            return True
        self.changed.wait(timeout)
        return self.capture_enabled

    def wait_until_disabled(self, timeout: float) -> bool:
        if not self.capture_enabled:
            return True
        self.changed.clear()
        if not self.capture_enabled:
            return True
        self.changed.wait(timeout)
        return not self.capture_enabled

    def _publish(self, was_enabled: bool) -> None:
        enabled = self._enabled_locked()
        if enabled != was_enabled:
            if enabled:
                logging.info("Capture enabled")
            else:
                logging.info("Capture disabled")
        self.changed.set()
        if enabled and not was_enabled:
            request_recovery("state became active")

    def apply_session(self, code: int, session_id: int, own_session_id: int | None) -> None:
        if own_session_id not in (None, 0) and session_id not in (0, own_session_id):
            return
        with self._lock:
            was_enabled = self._enabled_locked()
            if code == WTS_SESSION_LOGON:
                self.logged_on = True
                logging.info("Session LOGON")
            elif code == WTS_SESSION_LOGOFF:
                self.logged_on = False
                self.session_unlocked = False
                self.desktop_ready = False
                logging.info("Session LOGOFF")
            elif code == WTS_SESSION_LOCK:
                self.session_unlocked = False
                self.desktop_ready = False
                logging.info("Session LOCK")
                logging.info("Session locked; capture disabled")
            elif code == WTS_SESSION_UNLOCK:
                self.logged_on = True
                self.session_unlocked = True
                logging.info("Session UNLOCK")
                if self.desktop_ready and self.system_awake:
                    logging.info("Session unlocked; recovery triggered")
                else:
                    logging.info("Session unlocked; waiting for desktop readiness")
            elif code == WTS_SESSION_DESKTOP_READY:
                self.logged_on = True
                self.desktop_ready = True
                self.session_unlocked = True
                logging.info("Session desktop ready")
            else:
                return
            self._publish(was_enabled)

    def apply_power(self, code: int) -> None:
        with self._lock:
            was_enabled = self._enabled_locked()
            if code == PBT_APMSUSPEND:
                self.system_awake = False
                logging.info("Power SUSPEND")
                logging.info("System suspended; capture disabled")
            elif code in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND, PBT_APMRESUMECRITICAL):
                self.system_awake = True
                logging.info("Power RESUME")
                if self._enabled_locked():
                    logging.info("System resumed; recovery triggered")
                else:
                    logging.info("System resumed; waiting for desktop readiness")
            else:
                return
            self._publish(was_enabled)

    def set_initial(
        self,
        logged_on: bool,
        session_unlocked: bool,
        desktop_ready: bool,
        system_awake: bool,
    ) -> None:
        with self._lock:
            was_enabled = self._enabled_locked()
            self.logged_on = logged_on
            self.session_unlocked = session_unlocked
            self.desktop_ready = desktop_ready
            self.system_awake = system_awake
            self._publish(was_enabled)


client_state = ClientState(enabled=not sys.platform.startswith("win"))


def request_recovery(reason: str) -> None:
    logging.info("Recovery triggered by session event: %s", reason)
    recovery_trigger.set()


def current_session_id() -> int | None:
    if not sys.platform.startswith("win"):
        return None
    import ctypes

    session_id = ctypes.c_uint()
    if not ctypes.windll.kernel32.ProcessIdToSessionId(
        ctypes.windll.kernel32.GetCurrentProcessId(),
        ctypes.byref(session_id),
    ):
        return None
    return int(session_id.value)


def query_initial_state() -> None:
    if not sys.platform.startswith("win"):
        client_state.set_initial(True, True, True, True)
        return
    import ctypes
    from ctypes import wintypes

    wts = ctypes.windll.wtsapi32
    buffer = ctypes.c_void_p()
    returned = wintypes.DWORD()
    logged_on = False
    unlocked = False
    if wts.WTSQuerySessionInformationW(
        WTS_CURRENT_SERVER_HANDLE,
        WTS_CURRENT_SESSION,
        WTS_SESSION_INFO_EX,
        ctypes.byref(buffer),
        ctypes.byref(returned),
    ):
        try:
            raw = ctypes.string_at(buffer, returned.value)
            if len(raw) >= 20:
                session_flags = int.from_bytes(raw[16:20], "little", signed=True)
                unlocked = session_flags == WTS_SESSIONSTATE_UNLOCK
                logged_on = session_flags != WTS_SESSIONSTATE_LOCK
        finally:
            wts.WTSFreeMemory(buffer)
    client_state.set_initial(logged_on, unlocked, unlocked, True)
    if client_state.capture_enabled:
        logging.info("Startup state is active")
    else:
        logging.info("Startup state is inactive; waiting for desktop readiness")


def start_windows_listener() -> None:
    global _listener_started
    if not sys.platform.startswith("win"):
        return
    with _listener_lock:
        if _listener_started:
            return
        thread = threading.Thread(target=_message_loop, name="windows-events", daemon=True)
        thread.start()
        _listener_started = True


def _message_loop() -> None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    wts = ctypes.windll.wtsapi32
    own_session = current_session_id()

    wndproc_type = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )

    def wndproc(hwnd, msg, wparam, lparam):
        if msg == WM_WTSSESSION_CHANGE:
            client_state.apply_session(int(wparam), int(lparam), own_session)
            return 0
        if msg == WM_POWERBROADCAST:
            client_state.apply_power(int(wparam))
            return 1 if int(wparam) == PBT_APMSUSPEND else 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    callback = wndproc_type(wndproc)
    class_name = "ScreenshotClientEvents"

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", wndproc_type),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    instance = kernel32.GetModuleHandleW(None)
    window_class = WNDCLASSW()
    window_class.lpfnWndProc = callback
    window_class.hInstance = instance
    window_class.lpszClassName = class_name
    if not user32.RegisterClassW(ctypes.byref(window_class)):
        logging.error("Windows event window class registration failed")
        return
    hwnd = user32.CreateWindowExW(
        0,
        class_name,
        "ScreenshotClientEvents",
        0,
        0,
        0,
        0,
        0,
        HWND_MESSAGE,
        None,
        instance,
        None,
    )
    if not hwnd:
        logging.error("Windows event window creation failed")
        return
    if not wts.WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_THIS_SESSION):
        logging.error("Session notification registration failed")
    if not user32.RegisterSuspendResumeNotification(hwnd, DEVICE_NOTIFY_WINDOW_HANDLE):
        logging.error("Suspend/resume notification registration failed")
    message = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))
    wts.WTSUnRegisterSessionNotification(hwnd)
    user32.UnregisterSuspendResumeNotification(hwnd)
    # Keep the callback alive for the lifetime of this thread.
    del callback
