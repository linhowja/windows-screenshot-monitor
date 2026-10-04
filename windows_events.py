"""Windows session and power events for the Phase 4 client.

Session events use a hidden message window. Power suspend/resume uses
PowerRegisterSuspendResumeNotification with DEVICE_NOTIFY_CALLBACK.
The window is only an event receiver. It is not a user interface.
"""

from __future__ import annotations

import logging
import sys
import threading
import time

WM_POWERBROADCAST = 0x0218
WM_WTSSESSION_CHANGE = 0x02B1
NOTIFY_FOR_THIS_SESSION = 0
DEVICE_NOTIFY_CALLBACK = 0x00000002
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
WTS_SESSION_INFO_EX = 25
WTS_SESSIONSTATE_LOCK = 0
WTS_SESSIONSTATE_UNLOCK = 1
WTS_ACTIVE = 0

WINDOWS_MANUAL_TESTS = """
Windows 10/11 64-bit manual tests. Run server.py first, then:
    python app.py --server-ip 127.0.0.1

A. Normal capture
   Login to the desktop.
   Expected: capture enabled, one JPEG about every 20 seconds, upload or cache.
   Not expected: screenshots before the desktop is ready.

B. Win+L
   Lock the session and wait 1-2 minutes.
   Expected: capture disabled, no new screenshot and no new cache file.
   Not expected: a screenshot of the lock screen.

C. Unlock
   Unlock back to the desktop.
   Expected: no immediate screenshot; recovery worker awakened immediately;
   next screenshot only after one full interval.
   Not expected: a second recovery worker.

D. Sleep
   Power events come from PowerRegisterSuspendResumeNotification callback,
   not from RegisterSuspendResumeNotification on the hidden window.
   Expected: Type 4 disables capture before S3; no screenshot is taken.
   Not expected: catch-up screenshots for the sleep duration.

E. Wake while locked
   Wake callback Type 7 and Type 18 set system awake.
   Expected: capture still disabled while the lock screen is showing.
   Not expected: capture before unlock and desktop ready.

F. Unlock after wake
   Unlock after E.
   Expected: recovery triggered once; screenshot resumes after a full interval.
   Not expected: an immediate screenshot at the unlock instant.

G. Logoff
   Log off the interactive user.
   Expected: capture disabled; no further capture attempts.
   Not expected: mss errors becoming a crash.

H. Login again
   Log in to the desktop again and start the client if the process exited.
   Expected: startup query sees an active session, then normal capture resumes.
   Not expected: capture while the login screen is still showing.

I. Repeated Lock/Unlock
   Lock and unlock several times.
   Expected: one recovery worker, one capture loop, no deadlock or crash.
   Not expected: duplicate workers or overlapping timers.

J. Server unavailable plus Lock/Unlock
   Stop the server, lock, then unlock.
   Expected: recovery trigger runs, upload fails, cache files remain, client continues.
   Not expected: cache deletion or a client crash.
"""

recovery_trigger = threading.Event()
_listener_started = False
_listener_lock = threading.Lock()
_callback_keepalive = None
_power_callback = None
_power_parameters = None
_power_registration = None
desktop_ready_probe = None
READINESS_ATTEMPTS = 10
READINESS_DELAY_SECONDS = 0.3


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

    def _publish(self, was_enabled: bool, trigger_recovery: bool = True) -> None:
        enabled = self._enabled_locked()
        if enabled != was_enabled:
            if enabled:
                logging.info("Capture enabled")
            else:
                logging.info("Capture disabled")
        self.changed.set()
        if trigger_recovery and enabled and not was_enabled:
            request_recovery("state became active")

    def apply_session(self, code: int, session_id: int, own_session_id: int | None) -> None:
        if own_session_id not in (None, 0) and session_id not in (0, own_session_id):
            return
        confirm_readiness = False
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
                if desktop_is_ready():
                    self.desktop_ready = True
                    logging.info("Session unlocked; recovery triggered")
                else:
                    confirm_readiness = True
                    logging.info("Session unlocked; waiting for desktop readiness")
            elif code == WTS_SESSION_DESKTOP_READY:
                self.logged_on = True
                self.desktop_ready = True
                self.session_unlocked = True
                logging.info("Session desktop ready")
            else:
                return
            self._publish(was_enabled)
        if confirm_readiness:
            schedule_desktop_readiness(self)

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
            self._publish(was_enabled, trigger_recovery=False)

    def mark_desktop_ready(self) -> None:
        with self._lock:
            was_enabled = self._enabled_locked()
            self.logged_on = True
            self.desktop_ready = True
            logging.info("Desktop readiness confirmed")
            self._publish(was_enabled)

    def disable_capture(self, reason: str) -> None:
        logging.error("Capture disabled: %s", reason)
        self.set_initial(False, False, False, False)


client_state = ClientState(enabled=not sys.platform.startswith("win"))


def request_recovery(reason: str) -> None:
    logging.info("Recovery triggered by session event: %s", reason)
    recovery_trigger.set()


def desktop_is_ready() -> bool:
    if desktop_ready_probe is not None:
        return bool(desktop_ready_probe())
    if not sys.platform.startswith("win"):
        return True
    ctypes, wintypes, _kernel32, user32, _wts = _windows_modules()
    desktop_readobjects = 0x0001
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.CloseDesktop.restype = wintypes.BOOL
    desktop = user32.OpenInputDesktop(0, False, desktop_readobjects)
    if not desktop:
        return False
    user32.CloseDesktop(desktop)
    return True


def schedule_desktop_readiness(state: ClientState) -> None:
    def confirm() -> None:
        for _ in range(READINESS_ATTEMPTS):
            if not state.session_unlocked:
                return
            if desktop_is_ready():
                state.mark_desktop_ready()
                return
            time.sleep(READINESS_DELAY_SECONDS)
        logging.info("Desktop readiness not confirmed after limited retries")

    threading.Thread(target=confirm, name="desktop-readiness", daemon=True).start()


def _windows_modules():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)

    kernel32.GetCurrentProcessId.argtypes = []
    kernel32.GetCurrentProcessId.restype = wintypes.DWORD
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel32.ProcessIdToSessionId.restype = wintypes.BOOL
    kernel32.GetLastError.argtypes = []
    kernel32.GetLastError.restype = wintypes.DWORD

    wtsapi32.WTSQuerySessionInformationW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    wtsapi32.WTSQuerySessionInformationW.restype = wintypes.BOOL
    wtsapi32.WTSFreeMemory.argtypes = [wintypes.LPVOID]
    wtsapi32.WTSFreeMemory.restype = None
    wtsapi32.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
    wtsapi32.WTSRegisterSessionNotification.restype = wintypes.BOOL
    wtsapi32.WTSUnRegisterSessionNotification.argtypes = [wintypes.HWND]
    wtsapi32.WTSUnRegisterSessionNotification.restype = wintypes.BOOL

    user32.RegisterClassW.argtypes = [ctypes.c_void_p]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = ctypes.c_ssize_t
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    return ctypes, wintypes, kernel32, user32, wtsapi32


def current_session_id() -> int | None:
    if not sys.platform.startswith("win"):
        return None
    _ctypes, wintypes, kernel32, _user32, _wts = _windows_modules()
    session_id = wintypes.DWORD()
    if not kernel32.ProcessIdToSessionId(kernel32.GetCurrentProcessId(), _ctypes.byref(session_id)):
        logging.error("ProcessIdToSessionId failed: %s", kernel32.GetLastError())
        return None
    return int(session_id.value)


def read_session_info():
    """Return logged_on, unlocked, session_state, session_flags from WTSINFOEX."""
    ctypes, wintypes, _kernel32, _user32, wts = _windows_modules()

    class WTSINFOEX_LEVEL1_W(ctypes.Structure):
        _fields_ = [
            ("SessionId", wintypes.DWORD),
            ("SessionState", wintypes.DWORD),
            ("SessionFlags", wintypes.LONG),
            ("WinStationName", wintypes.WCHAR * 33),
            ("UserName", wintypes.WCHAR * 21),
            ("DomainName", wintypes.WCHAR * 18),
            ("LogonTime", wintypes.LARGE_INTEGER),
            ("ConnectTime", wintypes.LARGE_INTEGER),
            ("DisconnectTime", wintypes.LARGE_INTEGER),
            ("LastInputTime", wintypes.LARGE_INTEGER),
            ("CurrentTime", wintypes.LARGE_INTEGER),
            ("IncomingBytes", wintypes.DWORD),
            ("OutgoingBytes", wintypes.DWORD),
            ("IncomingFrames", wintypes.DWORD),
            ("OutgoingFrames", wintypes.DWORD),
            ("IncomingCompressedBytes", wintypes.DWORD),
            ("OutgoingCompressedBytes", wintypes.DWORD),
        ]

    class WTSINFOEXW(ctypes.Structure):
        _fields_ = [
            ("Level", wintypes.DWORD),
            ("DataSize", wintypes.DWORD),
            ("Data", WTSINFOEX_LEVEL1_W),
        ]

    buffer = ctypes.c_void_p()
    returned = wintypes.DWORD()
    ok = wts.WTSQuerySessionInformationW(
        WTS_CURRENT_SERVER_HANDLE,
        WTS_CURRENT_SESSION,
        WTS_SESSION_INFO_EX,
        ctypes.byref(buffer),
        ctypes.byref(returned),
    )
    if not ok or not buffer:
        raise OSError(ctypes.get_last_error())
    try:
        info = ctypes.cast(buffer, ctypes.POINTER(WTSINFOEXW)).contents
        level1 = info.Data
        needed = WTSINFOEXW.Data.offset + WTSINFOEX_LEVEL1_W.UserName.offset
        if returned.value < needed:
            raise OSError("WTSINFOEX buffer is smaller than the session fields")
        unlocked = int(level1.SessionFlags) == WTS_SESSIONSTATE_UNLOCK
        logged_on = bool(level1.UserName) and int(level1.SessionState) == WTS_ACTIVE
        return logged_on, unlocked, int(level1.SessionState), int(level1.SessionFlags)
    finally:
        wts.WTSFreeMemory(buffer)


def query_initial_state() -> None:
    if not sys.platform.startswith("win"):
        client_state.set_initial(True, True, True, True)
        return
    try:
        logged_on, unlocked, state, flags = read_session_info()
    except OSError as exc:
        logging.error("Initial session query failed: %s", exc)
        client_state.disable_capture("initial session query failed")
        return
    desktop_ready = logged_on and unlocked
    client_state.set_initial(logged_on, unlocked, desktop_ready, True)
    logging.info("Initial session state=%s flags=%s", state, flags)
    if client_state.capture_enabled:
        logging.info("Startup state is active")
    else:
        logging.info("Startup state is inactive; waiting for desktop readiness")


def register_power_callback():
    """Register the verified S3 callback. The callback only updates state."""
    global _power_callback, _power_parameters, _power_registration
    ctypes, wintypes, kernel32, _user32, _wts = _windows_modules()
    powrprof = ctypes.WinDLL("powrprof", use_last_error=True)
    powrprof.PowerRegisterSuspendResumeNotification.argtypes = [
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    powrprof.PowerRegisterSuspendResumeNotification.restype = wintypes.DWORD
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.c_void_p,
    )

    def callback(_context, event_type, _setting):
        client_state.apply_power(int(event_type))
        return 0

    class DEVICE_NOTIFY_SUBSCRIBE_PARAMETERS(ctypes.Structure):
        _fields_ = [
            ("Callback", callback_type),
            ("Context", ctypes.c_void_p),
        ]

    routine = callback_type(callback)
    parameters = DEVICE_NOTIFY_SUBSCRIBE_PARAMETERS(routine, None)
    registration = wintypes.HANDLE()
    status = powrprof.PowerRegisterSuspendResumeNotification(
        DEVICE_NOTIFY_CALLBACK,
        ctypes.byref(parameters),
        ctypes.byref(registration),
    )
    last_error = kernel32.GetLastError()
    if status != 0 or not registration:
        return None, int(status), int(last_error)
    _power_callback = routine
    _power_parameters = parameters
    _power_registration = registration
    return registration, int(status), int(last_error)


def unregister_power_callback() -> None:
    global _power_callback, _power_parameters, _power_registration
    registration = _power_registration
    if not registration:
        return
    ctypes, wintypes, _kernel32, _user32, _wts = _windows_modules()
    powrprof = ctypes.WinDLL("powrprof", use_last_error=True)
    powrprof.PowerUnregisterSuspendResumeNotification.argtypes = [wintypes.HANDLE]
    powrprof.PowerUnregisterSuspendResumeNotification.restype = wintypes.DWORD
    powrprof.PowerUnregisterSuspendResumeNotification(registration)
    _power_registration = None
    _power_callback = None
    _power_parameters = None


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
    global _callback_keepalive
    try:
        ctypes, wintypes, kernel32, user32, wts = _windows_modules()
    except OSError as exc:
        client_state.disable_capture(f"Windows API load failed: {exc}")
        return
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
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    callback = wndproc_type(wndproc)
    _callback_keepalive = callback

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
    window_class.lpszClassName = "ScreenshotClientEvents"
    if not user32.RegisterClassW(ctypes.byref(window_class)):
        client_state.disable_capture(f"RegisterClassW failed: {kernel32.GetLastError()}")
        return
    hwnd = user32.CreateWindowExW(
        0, "ScreenshotClientEvents", "ScreenshotClientEvents", 0,
        0, 0, 0, 0, HWND_MESSAGE, None, instance, None,
    )
    if not hwnd:
        client_state.disable_capture(f"CreateWindowExW failed: {kernel32.GetLastError()}")
        return
    if not wts.WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_THIS_SESSION):
        client_state.disable_capture(
            f"WTSRegisterSessionNotification failed: {kernel32.GetLastError()}"
        )
        return
    registration, status, last_error = register_power_callback()
    if registration is None:
        client_state.disable_capture(
            "PowerRegisterSuspendResumeNotification failed: "
            f"status={status} GetLastError={last_error}"
        )
        wts.WTSUnRegisterSessionNotification(hwnd)
        return
    message = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))
    unregister_power_callback()
    wts.WTSUnRegisterSessionNotification(hwnd)


def run_windows_api_self_test() -> int:
    print(WINDOWS_MANUAL_TESTS)
    if not sys.platform.startswith("win"):
        print("Windows API self-test requires Windows")
        return 2
    ctypes, wintypes, kernel32, user32, wts = _windows_modules()
    session_id = current_session_id()
    if session_id is None:
        print("current session ID unavailable")
        return 1
    try:
        logged_on, unlocked, state, flags = read_session_info()
    except OSError as exc:
        print(f"initial session state unavailable: {exc}")
        return 1
    wndproc_type = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    )
    callback = wndproc_type(user32.DefWindowProcW)

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
    window_class.lpszClassName = "ScreenshotClientApiSelfTest"
    if not user32.RegisterClassW(ctypes.byref(window_class)):
        print(f"hidden window class failed: {kernel32.GetLastError()}")
        return 1
    hwnd = user32.CreateWindowExW(
        0, "ScreenshotClientApiSelfTest", "ScreenshotClientApiSelfTest", 0,
        0, 0, 0, 0, HWND_MESSAGE, None, instance, None,
    )
    if not hwnd:
        print(f"hidden message window failed: {kernel32.GetLastError()}")
        return 1
    if not wts.WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_THIS_SESSION):
        print(f"WTS registration failed: {kernel32.GetLastError()}")
        user32.DestroyWindow(hwnd)
        return 1
    registration, status, last_error = register_power_callback()
    if registration is None:
        print(
            "PowerRegisterSuspendResumeNotification failed "
            f"status={status} GetLastError={last_error}"
        )
        wts.WTSUnRegisterSessionNotification(hwnd)
        user32.DestroyWindow(hwnd)
        return 1
    print(f"hidden message window: {hwnd}")
    print("WTS registration: ok")
    print(f"power callback registration: ok handle={registration.value} status={status}")
    print(f"current session ID: {session_id}")
    print(f"initial session logged_on={logged_on} unlocked={unlocked} state={state} flags={flags}")
    unregister_power_callback()
    wts.WTSUnRegisterSessionNotification(hwnd)
    user32.DestroyWindow(hwnd)
    print("Windows API self-test passed")
    return 0
