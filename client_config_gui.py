"""Desktop settings window for the Windows Screenshot Client.

Edits install_config.json (server_ip only). Dynamic settings are displayed
read-only from runtime_state.json and are managed by the server.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from app import (
    DEFAULT_INSTALL_CONFIG,
    DEFAULT_RUNTIME_STATE,
    INSTALL_CONFIG_PATH,
    RUNTIME_STATE_PATH,
    SERVER_PORT,
    _valid_install_fields,
    _valid_runtime_fields,
    setup_logging,
)

SAVED_MESSAGE = "Server IP 已儲存。正在執行的 Client 會在下次啟動後使用新的 Server IP。"


def read_install_config(path: Path) -> tuple[dict, str]:
    if not path.exists():
        return dict(DEFAULT_INSTALL_CONFIG), "install_config 不存在，顯示預設值。"
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        logging.error("GUI could not read install_config: %s", exc)
        return dict(DEFAULT_INSTALL_CONFIG), "install_config 無法讀取，顯示預設值。"
    validated = _valid_install_fields(raw)
    if validated is None:
        return dict(DEFAULT_INSTALL_CONFIG), "install_config 不合法，顯示預設值。"
    return validated, "已讀取目前 Server IP。"


def read_runtime_state(path: Path) -> dict:
    if not path.exists():
        return dict(DEFAULT_RUNTIME_STATE)
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_RUNTIME_STATE)
    validated = _valid_runtime_fields(raw)
    return validated if validated is not None else dict(DEFAULT_RUNTIME_STATE)


def _ipv4(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parts = value.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdigit() or int(part) > 255:
            return False
    return True


def save_install_config(path: Path, server_ip: str) -> tuple[bool, str]:
    if not _ipv4(server_ip):
        return False, "Server IPv4 必須是 0–255 的四段數字，例如 192.168.1.10。"
    payload = {"server_ip": server_ip.strip(), "server_port": SERVER_PORT}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.unlink(missing_ok=True)
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)
    logging.info("GUI saved install_config: %s", path)
    return True, SAVED_MESSAGE


def _open_settings_window(title: str):
    import tkinter as tk
    from tkinter import font as tkfont
    from tkinter import ttk

    if os.name == "nt":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    root = tk.Tk()
    root.title(title)
    root.geometry("760x520")
    root.minsize(640, 420)
    root.resizable(True, True)
    for name in ("TkDefaultFont", "TkTextFont"):
        try:
            current = tkfont.nametofont(name)
            size = abs(int(current.cget("size") or 10))
            if size > 12:
                current.configure(size=11)
        except Exception:
            pass
    style = ttk.Style(root)
    style.configure("Help.TLabel", foreground="#444444")
    style.configure("Readonly.TLabel", foreground="#666666")
    return root, tk, ttk


def run_gui(install_path: Path, state_path: Path) -> int:
    try:
        root, tk, ttk = _open_settings_window("Runtime Host Configuration")
    except Exception as exc:
        logging.error("Client config GUI unavailable: %s", exc)
        print(f"Client configuration GUI unavailable: {exc}", file=sys.stderr)
        return 1

    install, status = read_install_config(install_path)
    state = read_runtime_state(state_path)

    root.columnconfigure(0, weight=1)
    frame = ttk.Frame(root, padding=16)
    frame.grid(row=0, column=0, sticky="nsew")
    frame.columnconfigure(0, weight=1)

    ttk.Label(frame, text="Server IPv4").grid(row=0, column=0, sticky="w", pady=(8, 2))
    ip_var = tk.StringVar(value=str(install.get("server_ip", "")))
    ttk.Entry(frame, textvariable=ip_var).grid(row=1, column=0, sticky="ew")
    ttk.Label(
        frame,
        text="這台 Client 要上傳的 Server。只存在本機，不會被 Server 覆寫。需要管理員權限才能修改。",
        style="Help.TLabel",
        wraplength=680,
    ).grid(row=2, column=0, sticky="w", pady=(2, 12))

    ttk.Label(frame, text=f"Port 固定 {SERVER_PORT}，不能修改。").grid(row=3, column=0, sticky="w", pady=(4, 8))

    ttk.Separator(frame, orient="horizontal").grid(row=4, column=0, sticky="ew", pady=8)
    ttk.Label(
        frame,
        text="以下由 Server 管理，下次成功上傳後更新。在這裡不能修改。",
        style="Readonly.TLabel",
    ).grid(row=5, column=0, sticky="w", pady=(4, 6))

    row = 6
    for key, label in (
        ("screenshot_interval", "Screenshot Interval (seconds)"),
        ("jpeg_quality", "JPEG Quality"),
        ("client_cache_days", "Client Cache Retention (days)"),
    ):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=(6, 0))
        ttk.Label(frame, text=str(state.get(key, "")), style="Readonly.TLabel").grid(
            row=row + 1, column=0, sticky="w", pady=(0, 4)
        )
        row += 2

    status_var = tk.StringVar(value=status)
    ttk.Label(frame, textvariable=status_var, wraplength=680).grid(row=row, column=0, sticky="ew", pady=(12, 4))

    def on_save() -> None:
        ok, message = save_install_config(install_path, ip_var.get())
        status_var.set(message)
        if not ok:
            logging.error("GUI left install_config unchanged")

    def on_close() -> None:
        root.destroy()

    buttons = ttk.Frame(frame)
    buttons.grid(row=row + 1, column=0, sticky="e", pady=(8, 0))
    ttk.Button(buttons, text="Save", command=on_save, width=12).grid(row=0, column=0, padx=(0, 8))
    ttk.Button(buttons, text="Close", command=on_close, width=12).grid(row=0, column=1)
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Screenshot Client configuration GUI")
    parser.add_argument("--install-config", type=Path, default=INSTALL_CONFIG_PATH)
    parser.add_argument("--runtime-state", type=Path, default=RUNTIME_STATE_PATH)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        return run_self_test()
    setup_logging()
    logging.info("Client configuration GUI started")
    return run_gui(args.install_config, args.runtime_state)


def run_self_test() -> int:
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="client-gui-"))
    missing = root / "missing.json"
    values, message = read_install_config(missing)
    if values != DEFAULT_INSTALL_CONFIG or missing.exists() or "不存在" not in message:
        raise AssertionError(f"missing install config: {message} {values}")

    path = root / "install_config.json"
    path.write_text(json.dumps({"server_ip": "192.168.1.20", "server_port": SERVER_PORT}), encoding="utf-8")
    loaded, _ = read_install_config(path)
    if loaded["server_ip"] != "192.168.1.20":
        raise AssertionError(f"existing config not displayed: {loaded}")

    ok, message = save_install_config(path, "10.1.2.3")
    if not ok or "已儲存" not in message:
        raise AssertionError(f"valid save failed: {message}")
    saved = json.loads(path.read_text(encoding="utf-8-sig"))
    if saved["server_ip"] != "10.1.2.3" or saved["server_port"] != SERVER_PORT:
        raise AssertionError(f"saved mismatch: {saved}")

    ok, _ = save_install_config(path, "not-an-ip")
    if ok:
        raise AssertionError("invalid IP was written")

    packaging = Path(__file__).resolve().parent / "packaging"
    iss = (packaging / "client.iss").read_text(encoding="utf-8")
    spec = (packaging / "client_config.spec").read_text(encoding="utf-8")
    if "RuntimeHostConfig.exe" not in iss or 'name="RuntimeHostConfig"' not in spec:
        raise AssertionError("packaging does not include the client configuration executable")
    print("client config GUI self-test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
