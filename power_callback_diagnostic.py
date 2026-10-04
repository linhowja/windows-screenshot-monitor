"""Minimal callback-based S3 power diagnostic.

This does not change the client or the window-based diagnostic. It registers
PowerRegisterSuspendResumeNotification with DEVICE_NOTIFY_CALLBACK and prints
every callback Type. Ctrl+C unregisters and exits.
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

DEVICE_NOTIFY_CALLBACK = 0x00000002
ERROR_SUCCESS = 0
PBT_NAMES = {
    4: "PBT_APMSUSPEND",
    6: "PBT_APMRESUMECRITICAL",
    7: "PBT_APMRESUMESUSPEND",
    18: "PBT_APMRESUMEAUTOMATIC",
}

CALLBACK = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.c_void_p)
_callback_keepalive = None
_parameters_keepalive = None


class DEVICE_NOTIFY_SUBSCRIBE_PARAMETERS(ctypes.Structure):
    _fields_ = [
        ("Callback", CALLBACK),
        ("Context", ctypes.c_void_p),
    ]


def main() -> int:
    if not sys.platform.startswith("win"):
        print("Power callback diagnostic requires Windows")
        return 2

    global _callback_keepalive, _parameters_keepalive
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    powrprof = ctypes.WinDLL("powrprof", use_last_error=True)
    kernel32.GetLastError.argtypes = []
    kernel32.GetLastError.restype = wintypes.DWORD
    powrprof.PowerRegisterSuspendResumeNotification.argtypes = [
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    powrprof.PowerRegisterSuspendResumeNotification.restype = wintypes.DWORD
    powrprof.PowerUnregisterSuspendResumeNotification.argtypes = [wintypes.HANDLE]
    powrprof.PowerUnregisterSuspendResumeNotification.restype = wintypes.DWORD

    def callback(_context, event_type, _setting):
        value = int(event_type)
        name = PBT_NAMES.get(value, "unknown")
        print(f"Power callback Type={value} Type_hex=0x{value:04X} name={name}", flush=True)
        return 0

    routine = CALLBACK(callback)
    parameters = DEVICE_NOTIFY_SUBSCRIBE_PARAMETERS(routine, None)
    _callback_keepalive = routine
    _parameters_keepalive = parameters
    registration = wintypes.HANDLE()
    status = powrprof.PowerRegisterSuspendResumeNotification(
        DEVICE_NOTIFY_CALLBACK,
        ctypes.byref(parameters),
        ctypes.byref(registration),
    )
    last_error = kernel32.GetLastError()
    if status != ERROR_SUCCESS or not registration:
        print(
            "PowerRegisterSuspendResumeNotification failed "
            f"status={status} GetLastError={last_error}"
        )
        return 1
    print(
        "PowerRegisterSuspendResumeNotification success "
        f"handle={registration.value} status={status} GetLastError={last_error}"
    )
    print("Waiting for callback. Enter S3 sleep, then wake. Ctrl+C to stop.", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping")
    unregister = powrprof.PowerUnregisterSuspendResumeNotification(registration)
    print(f"PowerUnregisterSuspendResumeNotification status={unregister}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
