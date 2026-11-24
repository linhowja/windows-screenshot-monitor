"""Desktop settings window for the Windows Screenshot Client.

This edits the local Last Known Good file only. It does not capture the screen.
Server IP stays on this computer. Interval, JPEG quality, and cache days are
replaced the next time a successful upload brings newer values from the server.
Port stays 55550.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from app import (
    CLIENT_CONFIG_PATH,
    DEFAULT_CLIENT_CONFIG,
    SERVER_PORT,
    _valid_client_fields,
    configure_client_config_path,
    save_client_config,
    setup_logging,
)

FIELD_SPECS = (
    (
        "server_ip",
        "Server IPv4",
        "這台 Client 要上傳的 Server。只存在本機，不會被 Server 覆寫。",
    ),
    (
        "screenshot_interval",
        "Screenshot Interval (seconds)",
        "正整數。下次成功上傳後，會改成 Server 帶回的值。",
    ),
    (
        "jpeg_quality",
        "JPEG Quality",
        "整數 20–100。下次成功上傳後，會改成 Server 帶回的值。",
    ),
    (
        "client_cache_days",
        "Client Cache Retention (days)",
        "正整數。下次成功上傳後，會改成 Server 帶回的值。",
    ),
)
SAVED_MESSAGE = "設定已儲存。正在執行的 Client 會在下次啟動後使用新的 Server IP。"


def read_client_config(path: Path) -> tuple[dict, str]:
    """Return display values without writing the config file."""
    if not path.exists():
        return dict(DEFAULT_CLIENT_CONFIG), "設定檔不存在，顯示預設值。尚未寫入。"
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        logging.error("Client config GUI could not read config: %s", exc)
        return dict(DEFAULT_CLIENT_CONFIG), "設定檔無法讀取，顯示預設值。按 Save 才會覆寫。"
    validated = _valid_client_fields(raw)
    if validated is None:
        logging.error("Client config GUI rejected invalid config")
        return dict(DEFAULT_CLIENT_CONFIG), "設定檔不合法，顯示預設值。按 Save 才會覆寫。"
    return validated, "已讀取目前設定。"


def parse_form(raw_fields: dict[str, str]) -> dict:
    parsed: dict = {"server_port": SERVER_PORT}
    for key, _label, _help in FIELD_SPECS:
        text = raw_fields.get(key, "")
        if key == "server_ip":
            parsed[key] = text.strip()
            continue
        stripped = text.strip()
        if stripped.lstrip("-").isdigit():
            parsed[key] = int(stripped)
        else:
            parsed[key] = text
    return parsed


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


def save_settings(path: Path, values: dict) -> tuple[bool, str]:
    if is_settings_locked(path):
        logging.error("Client config GUI refused save because settings are locked")
        return False, "設定已鎖定。成功連線 Server 後無法從客戶端修改。請解除安裝後重新安裝。"
    if not _ipv4(values.get("server_ip")):
        logging.error("Client config GUI rejected server IP")
        return False, "Server IPv4 必須是 0–255 的四段數字，例如 192.168.1.10。"
    validated = _valid_client_fields(values)
    if validated is None:
        logging.error("Client config GUI validation failed")
        return False, "Server IPv4 必須是 IPv4。間隔與 Cache 天數必須大於 0。JPEG Quality 必須是 20–100。"
    extra: dict = {}
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            current = None
        if isinstance(current, dict):
            extra = {key: value for key, value in current.items() if key not in DEFAULT_CLIENT_CONFIG}
    configure_client_config_path(path)
    save_client_config({**validated, **extra})
    logging.info("Client config GUI saved settings: %s", path)
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
    root.update_idletasks()
    screen_w = max(root.winfo_screenwidth(), 800)
    screen_h = max(root.winfo_screenheight(), 600)
    width = min(1100, max(760, int(screen_w * 0.58)))
    height = min(860, max(620, int(screen_h * 0.72)))
    root.geometry(f"{width}x{height}")
    root.minsize(680, 520)
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
    return root, tk, ttk


def is_settings_locked(path: Path) -> bool:
    """Return True if the config has been locked after a successful server connection."""
    if not path.exists():
        return False
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(raw, dict) and bool(raw.get("locked"))


def run_gui(path: Path) -> int:
    if is_settings_locked(path):
        logging.warning("Settings are locked; refusing to open editor")
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "設定已鎖定",
                "此客戶端已成功連線 Server。\n\n設定只能由 Server 推送更新。\n如需修改設定，請解除安裝後重新安裝。",
            )
            root.destroy()
        except Exception:
            print("設定已鎖定。成功連線 Server 後，設定只能由 Server 推送更新。如需修改請解除安裝後重新安裝。", file=sys.stderr)
        return 2

    try:
        root, tk, ttk = _open_settings_window("Screenshot Client Configuration")
    except Exception as exc:
        logging.error("Client config GUI unavailable: %s", exc)
        print(f"Client configuration GUI unavailable: {exc}", file=sys.stderr)
        return 1

    values, status = read_client_config(path)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    outer = ttk.Frame(root, padding=12)
    outer.grid(row=0, column=0, sticky="nsew")
    outer.columnconfigure(0, weight=1)
    outer.rowconfigure(0, weight=1)

    canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0)
    scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    scrollbar.grid(row=0, column=1, sticky="ns")
    frame = ttk.Frame(canvas, padding=16)
    frame.columnconfigure(0, weight=1)
    window_id = canvas.create_window((0, 0), window=frame, anchor="nw")

    def sync_scroll(_event=None) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.itemconfigure(window_id, width=max(canvas.winfo_width(), 1))

    frame.bind("<Configure>", sync_scroll)
    canvas.bind("<Configure>", sync_scroll)

    variables: dict[str, tk.StringVar] = {}
    for row, (key, label, help_text) in enumerate(FIELD_SPECS):
        ttk.Label(frame, text=label).grid(row=row * 3, column=0, sticky="w", pady=(8, 2))
        variable = tk.StringVar(value="" if values.get(key) is None else str(values.get(key)))
        variables[key] = variable
        ttk.Entry(frame, textvariable=variable).grid(row=row * 3 + 1, column=0, sticky="ew")
        ttk.Label(frame, text=help_text, style="Help.TLabel", wraplength=680).grid(
            row=row * 3 + 2, column=0, sticky="w", pady=(2, 6)
        )
    ttk.Label(frame, text=f"Port 固定 {SERVER_PORT}，不能在這裡修改。").grid(row=20, column=0, sticky="w", pady=(8, 0))

    footer = ttk.Frame(outer)
    footer.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    footer.columnconfigure(0, weight=1)
    status_var = tk.StringVar(value=status)
    ttk.Label(footer, textvariable=status_var, wraplength=680).grid(row=0, column=0, sticky="ew")

    def on_save() -> None:
        ok, message = save_settings(path, parse_form({key: variable.get() for key, variable in variables.items()}))
        status_var.set(message)
        if not ok:
            logging.error("Client config GUI left config unchanged after validation failure")

    def on_close() -> None:
        logging.info("Client config GUI closed without saving")
        root.destroy()

    buttons = ttk.Frame(footer)
    buttons.grid(row=1, column=0, sticky="e", pady=(8, 0))
    ttk.Button(buttons, text="Save", command=on_save, width=12).grid(row=0, column=0, padx=(0, 8))
    ttk.Button(buttons, text="Close", command=on_close, width=12).grid(row=0, column=1)
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Screenshot Client configuration GUI")
    parser.add_argument("--config", type=Path, default=CLIENT_CONFIG_PATH)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        return run_self_test()
    setup_logging()
    logging.info("Client configuration GUI started")
    return run_gui(args.config)


def run_self_test() -> int:
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="client-gui-"))
    missing = root / "missing.json"
    values, message = read_client_config(missing)
    if values != DEFAULT_CLIENT_CONFIG or missing.exists() or "尚未寫入" not in message:
        raise AssertionError(f"missing config was written or not defaulted: {message} {values}")

    path = root / "config.json"
    original = {
        "server_ip": "192.168.1.20",
        "server_port": SERVER_PORT,
        "screenshot_interval": 20,
        "jpeg_quality": 40,
        "client_cache_days": 3,
        "note": "keep-me",
    }
    path.write_text(json.dumps(original, indent=2), encoding="utf-8")
    loaded, _message = read_client_config(path)
    if loaded["server_ip"] != "192.168.1.20" or loaded["jpeg_quality"] != 40:
        raise AssertionError(f"existing config was not displayed: {loaded}")
    if path.read_text(encoding="utf-8") != json.dumps(original, indent=2):
        raise AssertionError("reading config rewrote the file")

    changed = dict(original)
    changed["server_ip"] = "10.1.2.3"
    changed["screenshot_interval"] = 25
    changed["jpeg_quality"] = 55
    changed["client_cache_days"] = 4
    ok, message = save_settings(path, changed)
    if not ok or "已儲存" not in message:
        raise AssertionError(f"valid save failed: {message}")
    saved = json.loads(path.read_text(encoding="utf-8-sig"))
    if saved["note"] != "keep-me" or saved["server_ip"] != "10.1.2.3" or saved["server_port"] != SERVER_PORT:
        raise AssertionError(f"saved config mismatch: {saved}")

    snapshot = path.read_bytes()
    for bad in (
        {"server_ip": "not-an-ip"},
        {"server_ip": ""},
        {"screenshot_interval": 0},
        {"jpeg_quality": 5},
        {"client_cache_days": -1},
    ):
        candidate = dict(changed)
        candidate.update(bad)
        ok, _message = save_settings(path, candidate)
        if ok or path.read_bytes() != snapshot:
            raise AssertionError(f"invalid value was written: {bad}")

    leftover = path.with_name(path.name + ".tmp")
    leftover.write_text("stale", encoding="utf-8")
    ok, _message = save_settings(path, changed)
    if not ok or leftover.exists():
        raise AssertionError("leftover tmp blocked the client GUI save")

    packaging = Path(__file__).resolve().parent / "packaging"
    iss = (packaging / "client.iss").read_text(encoding="utf-8")
    spec = (packaging / "client_config.spec").read_text(encoding="utf-8")
    if "RuntimeHostConfig.exe" not in iss or 'name="RuntimeHostConfig"' not in spec:
        raise AssertionError("packaging does not include the client configuration executable")
    if "ScreenshotServer" in iss:
        raise AssertionError("client installer started including the server")
    print("client config GUI self-test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
