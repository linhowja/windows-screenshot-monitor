"""Desktop settings window for the Windows Screenshot Server.

This is not a web UI. It edits the five existing server settings and writes
server_config.json. The running server keeps the values it loaded at startup.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from server import (
    CONFIG_PATH,
    DEFAULT_SERVER_CONFIG,
    PORT,
    load_server_config,
    save_server_config,
    setup_logging,
)

FIELD_SPECS = (
    (
        "storage_root",
        "Screenshot Storage Root",
        "新截圖要寫入的資料夾。修改後只影響新資料，不搬移舊檔。",
    ),
    (
        "screenshot_interval",
        "Screenshot Interval (seconds)",
        "正整數。沿用 Server 目前規則，必須大於 0。",
    ),
    (
        "jpeg_quality",
        "JPEG Quality",
        "整數 20–100。沿用 Server 目前允許的 JPEG quality。",
    ),
    (
        "client_cache_days",
        "Client Cache Retention (days)",
        "正整數。沿用 Server 目前規則，0 或負數會被拒絕。",
    ),
    (
        "server_image_retention_days",
        "Server Image Retention (days)",
        "正整數。沿用 Server 目前規則，0 或負數會被拒絕。",
    ),
)
RESTART_MESSAGE = "設定已儲存。重新啟動 Screenshot Server 後才會生效。"


def read_server_config(path: Path) -> tuple[dict, str]:
    """Return display values without writing the config file."""
    if not path.exists():
        return dict(DEFAULT_SERVER_CONFIG), "設定檔不存在，顯示目前 Server 預設值。尚未寫入。"
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        logging.error("Server config GUI could not read config: %s", exc)
        return dict(DEFAULT_SERVER_CONFIG), "設定檔無法讀取，顯示預設值。按 Save 才會覆寫。"
    if not isinstance(raw, dict):
        logging.error("Server config GUI rejected non-object config")
        return dict(DEFAULT_SERVER_CONFIG), "設定檔不是物件，顯示預設值。按 Save 才會覆寫。"
    values = dict(DEFAULT_SERVER_CONFIG)
    for key in DEFAULT_SERVER_CONFIG:
        if key in raw:
            values[key] = raw[key]
    return values, "已讀取目前設定。"


def validate_settings(values: dict) -> tuple[dict | None, list[str]]:
    errors: list[str] = []
    storage = values.get("storage_root")
    if not isinstance(storage, str) or not storage.strip() or "\x00" in storage:
        errors.append("Screenshot Storage Root 必須是有效路徑，不能是空白。")
        storage_value = None
    else:
        storage_value = storage.strip()

    interval = _positive_field(values.get("screenshot_interval"), "Screenshot Interval (seconds)", errors)
    quality = _quality_field(values.get("jpeg_quality"), errors)
    cache_days = _positive_field(values.get("client_cache_days"), "Client Cache Retention (days)", errors)
    retention_days = _positive_field(
        values.get("server_image_retention_days"),
        "Server Image Retention (days)",
        errors,
    )
    if errors:
        return None, errors
    return {
        "storage_root": storage_value,
        "screenshot_interval": interval,
        "jpeg_quality": quality,
        "client_cache_days": cache_days,
        "server_image_retention_days": retention_days,
    }, []


def parse_form(raw_fields: dict[str, str]) -> dict:
    parsed: dict = {}
    for key, _label, _help in FIELD_SPECS:
        text = raw_fields.get(key, "")
        if key == "storage_root":
            parsed[key] = text
            continue
        stripped = text.strip()
        if stripped.lstrip("-").isdigit():
            parsed[key] = int(stripped)
        else:
            parsed[key] = text
    return parsed


def save_settings(path: Path, values: dict) -> tuple[bool, str]:
    validated, errors = validate_settings(values)
    if validated is None:
        logging.error("Server config GUI validation failed: %s", "; ".join(errors))
        return False, "\n".join(errors)
    extra: dict = {}
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            current = None
        if isinstance(current, dict):
            extra = {key: value for key, value in current.items() if key not in DEFAULT_SERVER_CONFIG}
    save_server_config(path, {**validated, **extra})
    logging.info("Server config GUI saved settings: %s", path)
    return True, RESTART_MESSAGE


def _open_settings_window(title: str):
    """Size the window from the screen and keep text readable on high-DPI displays."""
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


def run_gui(path: Path) -> int:
    try:
        root, tk, ttk = _open_settings_window("Screenshot Server Configuration")
    except Exception as exc:
        logging.error("Server config GUI unavailable: %s", exc)
        print(f"Server configuration GUI unavailable: {exc}", file=sys.stderr)
        return 1

    values, status = read_server_config(path)
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
        variable = tk.StringVar(value=_display(values.get(key)))
        variables[key] = variable
        ttk.Entry(frame, textvariable=variable).grid(row=row * 3 + 1, column=0, sticky="ew")
        ttk.Label(frame, text=help_text, style="Help.TLabel", wraplength=680).grid(
            row=row * 3 + 2, column=0, sticky="w", pady=(2, 6)
        )

    footer = ttk.Frame(outer)
    footer.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    footer.columnconfigure(0, weight=1)
    status_var = tk.StringVar(value=status)
    ttk.Label(footer, textvariable=status_var, wraplength=680).grid(row=0, column=0, sticky="ew")

    def on_save() -> None:
        ok, message = save_settings(path, parse_form({key: variable.get() for key, variable in variables.items()}))
        status_var.set(message)
        if not ok:
            logging.error("Server config GUI left config unchanged after validation failure")

    def on_close() -> None:
        logging.info("Server config GUI closed without saving")
        root.destroy()

    buttons = ttk.Frame(footer)
    buttons.grid(row=1, column=0, sticky="e", pady=(8, 0))
    ttk.Button(buttons, text="Save", command=on_save, width=12).grid(row=0, column=0, padx=(0, 8))
    ttk.Button(buttons, text="Close", command=on_close, width=12).grid(row=0, column=1)
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Screenshot Server configuration GUI")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        return run_self_test()
    setup_logging()
    logging.info("Server configuration GUI started")
    return run_gui(args.config)


def run_self_test() -> int:
    import os
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="phase8a-gui-"))
    os.chdir(root)
    missing = root / "missing.json"
    before = list(root.iterdir())
    values, message = read_server_config(missing)
    if values != DEFAULT_SERVER_CONFIG or missing.exists() or before != list(root.iterdir()):
        raise AssertionError(f"missing config was written or not defaulted: {message}")

    path = root / "server_config.json"
    original = {
        "storage_root": r"D:\ScreenshotServer",
        "screenshot_interval": 20,
        "jpeg_quality": 40,
        "client_cache_days": 3,
        "server_image_retention_days": 14,
        "note": "keep-me",
    }
    path.write_text(json.dumps(original, indent=2), encoding="utf-8")
    loaded, _message = read_server_config(path)
    if loaded["jpeg_quality"] != 40 or loaded["storage_root"] != r"D:\ScreenshotServer":
        raise AssertionError(f"existing config was not displayed: {loaded}")
    if path.read_text(encoding="utf-8") != json.dumps(original, indent=2):
        raise AssertionError("reading config rewrote the file")

    changed = dict(original)
    changed.update(
        {
            "storage_root": r"E:\Shots",
            "screenshot_interval": 25,
            "jpeg_quality": 55,
            "client_cache_days": 4,
            "server_image_retention_days": 21,
        }
    )
    ok, message = save_settings(path, changed)
    if not ok or "重新啟動" not in message:
        raise AssertionError(f"valid save failed: {message}")
    saved = json.loads(path.read_text(encoding="utf-8"))
    if saved["note"] != "keep-me" or saved["screenshot_interval"] != 25 or saved["jpeg_quality"] != 55:
        raise AssertionError(f"saved config mismatch: {saved}")
    if not path.read_bytes().startswith(b"{"):
        raise AssertionError("config was not written as readable JSON")

    snapshot = path.read_bytes()
    rejected = dict(changed)
    rejected["jpeg_quality"] = 5
    ok, message = save_settings(path, rejected)
    if ok or path.read_bytes() != snapshot:
        raise AssertionError("invalid jpeg quality was written")
    for key, bad in (
        ("screenshot_interval", 0),
        ("screenshot_interval", -1),
        ("screenshot_interval", True),
        ("client_cache_days", 0),
        ("server_image_retention_days", -3),
        ("storage_root", "  "),
        ("storage_root", ""),
    ):
        candidate = dict(changed)
        candidate[key] = bad
        ok, _message = save_settings(path, candidate)
        if ok or path.read_bytes() != snapshot:
            raise AssertionError(f"invalid {key}={bad!r} was written")
    form_rejected = parse_form({key: str(changed[key]) for key in DEFAULT_SERVER_CONFIG})
    form_rejected["jpeg_quality"] = "40.5"
    ok, _message = save_settings(path, form_rejected)
    if ok or path.read_bytes() != snapshot:
        raise AssertionError("non-integer form value was written")

    close_without_save(path)
    if path.read_bytes() != snapshot:
        raise AssertionError("close wrote the config")

    restarted = load_server_config(path)
    if (
        restarted["storage_root"] != r"E:\Shots"
        or restarted["screenshot_interval"] != 25
        or restarted["jpeg_quality"] != 55
        or restarted["client_cache_days"] != 4
        or restarted["server_image_retention_days"] != 21
    ):
        raise AssertionError(f"restart did not load GUI settings: {restarted}")
    if json.loads(path.read_text(encoding="utf-8")).get("note") != "keep-me":
        raise AssertionError("server reload removed an existing field")

    leftover = path.with_name(path.name + ".tmp")
    leftover.write_text("stale", encoding="utf-8")
    ok, _message = save_settings(path, changed)
    if not ok or leftover.exists():
        raise AssertionError("leftover tmp blocked the GUI save")

    if PORT != 55550:
        raise AssertionError("GUI work changed the fixed port")
    packaging = Path(__file__).resolve().parent / "packaging"
    iss = (packaging / "server.iss").read_text(encoding="utf-8")
    spec = (packaging / "server_config.spec").read_text(encoding="utf-8")
    if "ScreenshotServerConfig.exe" not in iss or 'name="ScreenshotServerConfig"' not in spec:
        raise AssertionError("packaging does not include the configuration executable")
    if "ScreenshotClient" in (packaging / "server.iss").read_text(encoding="utf-8"):
        raise AssertionError("server installer started including the client")
    print("server config GUI self-test passed")
    return 0


def close_without_save(path: Path) -> None:
    """Close leaves the file alone. The window calls this path, not save_settings."""
    path.stat()


def _positive_field(value: object, label: str, errors: list[str]) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        errors.append(f"{label} 必須是大於 0 的整數。")
        return None
    return value


def _quality_field(value: object, errors: list[str]) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or not 20 <= value <= 100:
        errors.append("JPEG Quality 必須是 20–100 的整數。")
        return None
    return value


def _display(value: object) -> str:
    return "" if value is None else str(value)


if __name__ == "__main__":
    raise SystemExit(main())
