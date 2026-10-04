"""Minimal Windows power-event diagnostic.

This does not change the client. Run it on the Windows test machine, enter
S3 sleep, then wake the computer. Ctrl+C stops the message loop.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

WM_POWERBROADCAST = 0x0218
DEVICE_NOTIFY_WINDOW_HANDLE = 0
HWND_MESSAGE = -3
PBT_NAMES = {
    0x0004: "PBT_APMSUSPEND",
    0x0006: "PBT_APMRESUMECRITICAL",
    0x0007: "PBT_APMRESUMESUSPEND",
    0x000A: "PBT_APMPOWERSTATUSCHANGE",
    0x0012: "PBT_APMRESUMEAUTOMATIC",
    0x0018: "PBT_POWERSETTINGCHANGE",
}


def main() -> int:
    if not sys.platform.startswith("win"):
        print("Power event diagnostic requires Windows")
        return 2

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetLastError.argtypes = []
    kernel32.GetLastError.restype = wintypes.DWORD
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.RegisterClassW.argtypes = [ctypes.c_void_p]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.RegisterSuspendResumeNotification.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    user32.RegisterSuspendResumeNotification.restype = wintypes.HANDLE
    user32.UnregisterSuspendResumeNotification.argtypes = [wintypes.HANDLE]
    user32.UnregisterSuspendResumeNotification.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = ctypes.c_ssize_t
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.PostQuitMessage.restype = None
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL

    wndproc_type = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    )

    def wndproc(hwnd, msg, wparam, lparam):
        if msg == WM_POWERBROADCAST:
            value = int(wparam)
            name = PBT_NAMES.get(value, "unknown")
            print(f"WM_POWERBROADCAST wParam={value} wParam_hex=0x{value:04X} name={name}", flush=True)
            return 1 if value == 0x0004 else 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    callback = wndproc_type(wndproc)

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
    window_class.lpszClassName = "PowerEventDiagnostic"
    if not user32.RegisterClassW(ctypes.byref(window_class)):
        print(f"RegisterClassW failed GetLastError={kernel32.GetLastError()}")
        return 1
    hwnd = user32.CreateWindowExW(
        0, "PowerEventDiagnostic", "PowerEventDiagnostic", 0,
        0, 0, 0, 0, HWND_MESSAGE, None, instance, None,
    )
    if not hwnd:
        print(f"CreateWindowExW failed GetLastError={kernel32.GetLastError()}")
        return 1
    print(f"hidden message window created hwnd={hwnd}")
    power_notify = user32.RegisterSuspendResumeNotification(hwnd, DEVICE_NOTIFY_WINDOW_HANDLE)
    if not power_notify:
        print(f"RegisterSuspendResumeNotification failed GetLastError={kernel32.GetLastError()}")
        user32.DestroyWindow(hwnd)
        return 1
    print(f"RegisterSuspendResumeNotification success handle={power_notify} GetLastError={kernel32.GetLastError()}")
    print("Waiting for WM_POWERBROADCAST. Enter S3 sleep, then wake. Ctrl+C to stop.", flush=True)

    handler_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

    def console_ctrl(_event):
        user32.PostQuitMessage(0)
        return True

    ctrl_handler = handler_type(console_ctrl)
    kernel32.SetConsoleCtrlHandler.argtypes = [handler_type, wintypes.BOOL]
    kernel32.SetConsoleCtrlHandler.restype = wintypes.BOOL
    kernel32.SetConsoleCtrlHandler(ctrl_handler, True)

    message = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))
    user32.UnregisterSuspendResumeNotification(power_notify)
    user32.DestroyWindow(hwnd)
    print("Power event diagnostic stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
