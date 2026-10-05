"""Phase 2 upload server.

Listens on TCP 55550 and accepts one endpoint: POST /api/upload.
A 200 is returned only after the JPEG is verified on disk, or when the
same final path already exists. There is no web UI.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import logging.handlers
import os
import re
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify, request
from PIL import Image
from waitress import create_server, serve

HOST = "0.0.0.0"
PORT = 55550
FILENAME_RE = re.compile(r"^(\d{8})_(\d{6})_(\d{2})\.jpg$")
DEFAULT_SERVER_CONFIG = {
    "storage_root": r"C:\ProgramData\ScreenshotServer\Storage",
    "screenshot_interval": 20,
    "jpeg_quality": 40,
    "client_cache_days": 3,
    "server_image_retention_days": 14,
}
SERVER_PROGRAMDATA = Path(r"C:\ProgramData\ScreenshotServer")
CONFIG_PATH = Path(r"C:\ProgramData\ScreenshotServer\server_config.json")
session_log_handler: logging.Handler | None = None

app = Flask(__name__)
STORAGE_ROOT = Path("dev_storage")
server_config = dict(DEFAULT_SERVER_CONFIG)
config_lock = threading.Lock()


def server_log_dir() -> Path:
    from app import documents_dir

    return documents_dir() / "ScreenshotServer" / "Logs"


def close_logging() -> None:
    global session_log_handler
    if session_log_handler is None:
        return
    logging.info("Application shutting down")
    session_log_handler.flush()
    logging.getLogger().removeHandler(session_log_handler)
    session_log_handler.close()
    session_log_handler = None


def setup_logging(log_dir: Path | None = None) -> Path | None:
    global session_log_handler
    from app import session_log_name

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    if not any(isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler) for handler in root.handlers):
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(formatter)
        root.addHandler(stream)
    if os.name != "nt" and log_dir is None:
        logging.info("Server logging started without a session file")
        return None
    target = log_dir or server_log_dir()
    try:
        target.mkdir(parents=True, exist_ok=True)
        log_path = target / session_log_name()
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
        session_log_handler = file_handler
    except OSError as exc:
        print(f"Server file log unavailable: {exc}", file=sys.stderr)
        return None
    logging.info("Server logging started: %s", log_path)
    return log_path


def configure_storage(storage_root: Path) -> None:
    global STORAGE_ROOT
    STORAGE_ROOT = storage_root
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)


def _positive_int(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return default
    return value


def sanitize_server_config(raw: object) -> dict:
    source = raw if isinstance(raw, dict) else {}
    storage_root = source.get("storage_root", DEFAULT_SERVER_CONFIG["storage_root"])
    if not isinstance(storage_root, str) or not storage_root.strip():
        logging.error("Invalid storage_root; using default")
        storage_root = DEFAULT_SERVER_CONFIG["storage_root"]
    quality = source.get("jpeg_quality", DEFAULT_SERVER_CONFIG["jpeg_quality"])
    if isinstance(quality, bool) or not isinstance(quality, int) or not 20 <= quality <= 100:
        logging.error("Invalid jpeg_quality; using default")
        quality = DEFAULT_SERVER_CONFIG["jpeg_quality"]
    return {
        "storage_root": storage_root,
        "screenshot_interval": _positive_int(
            source.get("screenshot_interval"), DEFAULT_SERVER_CONFIG["screenshot_interval"]
        ),
        "jpeg_quality": quality,
        "client_cache_days": _positive_int(
            source.get("client_cache_days"), DEFAULT_SERVER_CONFIG["client_cache_days"]
        ),
        "server_image_retention_days": _positive_int(
            source.get("server_image_retention_days"),
            DEFAULT_SERVER_CONFIG["server_image_retention_days"],
        ),
    }


def save_server_config(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    data = json.dumps(payload, indent=2).encode("utf-8")
    binary_flag = getattr(os, "O_BINARY", 0)
    fd = os.open(str(temporary), os.O_CREAT | os.O_EXCL | os.O_WRONLY | binary_flag)
    try:
        view = memoryview(data)
        offset = 0
        while offset < len(view):
            written = os.write(fd, view[offset:])
            if written <= 0:
                raise OSError("incomplete config write")
            offset += written
        os.fsync(fd)
    except Exception:
        os.close(fd)
        temporary.unlink(missing_ok=True)
        raise
    os.close(fd)
    os.replace(temporary, path)


def load_server_config(path: Path | None = None, storage_override: Path | None = None) -> dict:
    global server_config
    path = path or CONFIG_PATH
    raw: object = None
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            logging.error("Server config is unreadable; using defaults: %s", exc)
    validated = sanitize_server_config(raw)
    if storage_override is not None:
        validated["storage_root"] = str(storage_override)
    save_server_config(path, validated)
    with config_lock:
        server_config = validated
    configure_storage(Path(validated["storage_root"]))
    return dict(validated)


def client_config_payload() -> dict:
    with config_lock:
        return {
            "screenshot_interval": server_config["screenshot_interval"],
            "jpeg_quality": server_config["jpeg_quality"],
            "client_cache_days": server_config["client_cache_days"],
        }


def retention_state_path(config_path: Path | None = None) -> Path:
    return (config_path or CONFIG_PATH).with_name("server_retention_state.json")


def capture_timestamp(filename: str) -> datetime | None:
    match = FILENAME_RE.fullmatch(filename)
    if not match:
        return None
    day, clock, centisecond = match.groups()
    try:
        captured = datetime.strptime(day + clock, "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return captured.replace(microsecond=int(centisecond) * 10_000)


def find_retention_candidates(storage_root: Path, retention_days: int, now: datetime) -> list[Path]:
    cutoff = now - timedelta(days=retention_days)
    root = storage_root.resolve()
    candidates: list[Path] = []
    if not root.is_dir():
        return candidates
    for identity in root.iterdir():
        if not identity.is_dir():
            continue
        for day_dir in identity.iterdir():
            if not day_dir.is_dir() or not re.fullmatch(r"\d{8}", day_dir.name):
                continue
            for path in day_dir.iterdir():
                if not path.is_file() or path.suffix.lower() != ".jpg":
                    continue
                captured = capture_timestamp(path.name)
                if captured is None or path.name[:8] != day_dir.name or captured >= cutoff:
                    continue
                resolved = path.resolve()
                if os.path.commonpath([str(root), str(resolved)]) != str(root):
                    continue
                candidates.append(path)
    return candidates


def save_retention_state(path: Path, last_check_date: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.unlink(missing_ok=True)
    data = json.dumps({"last_check_date": last_check_date}, indent=2).encode("utf-8")
    binary_flag = getattr(os, "O_BINARY", 0)
    fd = os.open(str(temporary), os.O_CREAT | os.O_EXCL | os.O_WRONLY | binary_flag)
    try:
        view = memoryview(data)
        offset = 0
        while offset < len(view):
            written = os.write(fd, view[offset:])
            if written <= 0:
                raise OSError("incomplete retention state write")
            offset += written
        os.fsync(fd)
    except Exception:
        os.close(fd)
        temporary.unlink(missing_ok=True)
        raise
    os.close(fd)
    os.replace(temporary, path)


def read_retention_state(path: Path) -> str | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    value = raw.get("last_check_date")
    if not isinstance(value, str):
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    return value


def windows_confirm_delete(count: int, retention_days: int, storage_root: Path) -> bool:
    if not sys.platform.startswith("win"):
        logging.error("Retention confirmation requires Windows; keeping files")
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
    user32.MessageBoxW.restype = ctypes.c_int
    question = (
        f"發現 {count} 張超過 {retention_days} 天的圖片。\n"
        f"Storage Root:\n{storage_root}\n"
        "是否刪除這些圖片？"
    )
    answer = user32.MessageBoxW(None, question, "Screenshot Server Retention", 0x00000004 | 0x00000020 | 0x00000100)
    if answer != 6:
        user32.MessageBoxW(
            None,
            "圖片未刪除。\n如果需要保留，請自行將這些圖片移動到其他資料夾。\n今天不會再次詢問。",
            "Screenshot Server Retention",
            0x00000040,
        )
        return False
    return True


def delete_candidates(candidates: list[Path]) -> tuple[int, int]:
    deleted = 0
    failed = 0
    for path in candidates:
        try:
            path.unlink()
            deleted += 1
        except OSError as exc:
            failed += 1
            logging.error("Retention delete failed: %s (%s)", path, exc)
    return deleted, failed


def run_retention_check(
    storage_root: Path,
    retention_days: int,
    state_path: Path,
    now: datetime | None = None,
    decider=None,
) -> dict:
    now = now or datetime.now()
    today = now.date().isoformat()
    if read_retention_state(state_path) == today:
        logging.info("Retention check skipped; already completed today")
        return {"skipped": True, "candidates": 0, "deleted": 0, "failed": 0}
    logging.info("Retention check started")
    try:
        candidates = find_retention_candidates(storage_root, retention_days, now)
    except Exception as exc:
        logging.error("Retention check error: %s", exc)
        return {"skipped": False, "error": True, "candidates": 0, "deleted": 0, "failed": 0}
    logging.info("Retention candidates found: %d", len(candidates))
    deleted = 0
    failed = 0
    if candidates:
        delete = False
        try:
            delete = (decider or windows_confirm_delete)(len(candidates), retention_days, storage_root)
        except Exception as exc:
            logging.error("Retention confirmation failed; keeping files: %s", exc)
        logging.info("User selected %s", "DELETE" if delete else "KEEP")
        if delete:
            deleted, failed = delete_candidates(candidates)
    save_retention_state(state_path, today)
    logging.info("Deleted: %d", deleted)
    logging.info("Delete failed: %d", failed)
    logging.info("Retention check completed")
    return {"skipped": False, "candidates": len(candidates), "deleted": deleted, "failed": failed}


def safe_identity_part(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid {field}")
    if value != value.strip() or any(char in value for char in "/\\:\0") or ".." in value:
        raise ValueError(f"invalid {field}")
    if value in {".", ".."}:
        raise ValueError(f"invalid {field}")
    return value


def validated_filename(filename: str) -> tuple[str, str]:
    match = FILENAME_RE.fullmatch(filename or "")
    if not match:
        raise ValueError("invalid filename")
    day, clock, centisecond = match.groups()
    try:
        datetime.strptime(day, "%Y%m%d")
        datetime.strptime(clock, "%H%M%S")
    except ValueError as exc:
        raise ValueError("invalid filename date") from exc
    if int(centisecond) > 99:
        raise ValueError("invalid filename centisecond")
    return filename, day


def validate_jpeg(payload: bytes) -> None:
    try:
        with Image.open(io.BytesIO(payload)) as image:
            if image.format != "JPEG":
                raise ValueError("invalid jpeg")
            image.load()
    except Exception as exc:
        raise ValueError("invalid jpeg") from exc


def destination_for(hostname: str, username: str, filename: str) -> Path:
    hostname = safe_identity_part(hostname, "hostname")
    username = safe_identity_part(username, "username")
    filename, day = validated_filename(filename)
    root = STORAGE_ROOT.resolve()
    destination = (root / f"{hostname}_{username}" / day / filename).resolve()
    if os.path.commonpath([str(root), str(destination)]) != str(root):
        raise ValueError("invalid destination")
    return destination


def success_response():
    return jsonify(status="ok", config=client_config_payload()), 200


def write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    offset = 0
    while offset < len(view):
        written = os.write(fd, view[offset:])
        if written <= 0:
            raise OSError("incomplete file write")
        offset += written
    os.fsync(fd)


def write_exclusive(destination: Path, payload: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    binary_flag = getattr(os, "O_BINARY", 0)
    fd = os.open(str(destination), os.O_CREAT | os.O_EXCL | os.O_WRONLY | binary_flag)
    try:
        write_all(fd, payload)
    except Exception:
        os.close(fd)
        destination.unlink(missing_ok=True)
        raise
    else:
        os.close(fd)


@app.post("/api/upload")
def api_upload():
    uploaded = request.files.get("file")
    if uploaded is None:
        return jsonify(status="error", message="file is required"), 400

    payload = uploaded.read()
    try:
        validate_jpeg(payload)
        destination = destination_for(
            request.form.get("hostname", ""),
            request.form.get("username", ""),
            uploaded.filename or "",
        )
    except ValueError as exc:
        return jsonify(status="error", message=str(exc)), 400

    if destination.is_file():
        logging.info("Duplicate upload acknowledged without overwrite: %s", destination)
        return success_response()

    try:
        write_exclusive(destination, payload)
    except FileExistsError:
        logging.info("Duplicate upload lost the create race: %s", destination)
        return success_response()
    except Exception as exc:
        logging.exception("Failed to store upload: %s", exc)
        return jsonify(status="error", message="store failed"), 500

    if not destination.is_file() or destination.stat().st_size != len(payload):
        destination.unlink(missing_ok=True)
        return jsonify(status="error", message="store verification failed"), 500

    logging.info("Stored %s (%d bytes)", destination, len(payload))
    return success_response()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 2 screenshot upload server")
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=None,
        help="Development override. Explicit CLI wins over server_config.json.",
    )
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def run_self_test(storage_root: Path) -> None:
    import time

    import requests
    from PIL import Image as PilImage

    from app import make_filename, process_screenshot, upload_jpeg

    if PORT != 55550 or HOST != "0.0.0.0":
        raise AssertionError("server listen address is not fixed")
    try:
        parse_args(["--port", "80"])
    except SystemExit:
        pass
    else:
        raise AssertionError("port option is still accepted")

    validated_filename("20261003_162000_37.jpg")
    validated_filename("20260228_120000_00.jpg")
    for bad_name in ("20260231_120000_00.jpg", "20261301_120000_00.jpg"):
        try:
            validated_filename(bad_name)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid date accepted: {bad_name}")

    configure_storage(storage_root)
    partial = storage_root / "partial-test" / "20261003" / "20261003_162000_37.jpg"
    original_write = os.write

    def failing_write(fd: int, data: bytes) -> int:
        if isinstance(data, memoryview):
            data = data.tobytes()
        original_write(fd, data[:1])
        raise OSError("simulated incomplete write")

    os.write = failing_write
    try:
        try:
            write_exclusive(partial, b"\xff\xd8" + b"x" * 32)
        except OSError:
            pass
        else:
            raise AssertionError("simulated write failure did not raise")
    finally:
        os.write = original_write
    if partial.exists() or any(partial.parent.glob("*")):
        raise AssertionError("failed write left a partial file")

    server = create_server(app, host="127.0.0.1", port=PORT, threads=4)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(0.4)

    try:
        source = PilImage.new("RGB", (1920, 1080), (30, 90, 140))
        jpeg = process_screenshot(source)
        filename = make_filename(datetime(2026, 10, 3, 16, 20, 0, 370000))
        url = f"http://127.0.0.1:{PORT}/api/upload"

        response = requests.post(
            url,
            data={"hostname": "LIN-PC01", "username": "child"},
            files={"file": (filename, io.BytesIO(jpeg), "image/jpeg")},
            timeout=5,
        )
        if response.status_code != 200 or response.json().get("status") != "ok":
            raise AssertionError(f"upload failed: {response.status_code} {response.text}")
        if response.json().get("config") != client_config_payload():
            raise AssertionError(f"upload config mismatch: {response.json()}")

        stored = storage_root / "LIN-PC01_child" / "20261003" / filename
        if not stored.is_file() or stored.read_bytes() != jpeg:
            raise AssertionError(f"stored file mismatch: {stored}")
        if stored.stat().st_size != len(jpeg) or jpeg.count(b"\n") != stored.read_bytes().count(b"\n"):
            raise AssertionError("stored JPEG bytes were translated")
        if stored.stat().st_size != len(jpeg):
            raise AssertionError("stored size does not match payload")

        duplicate = requests.post(
            url,
            data={"hostname": "LIN-PC01", "username": "child"},
            files={"file": (filename, io.BytesIO(jpeg + b"\xff"), "image/jpeg")},
            timeout=5,
        )
        if duplicate.status_code != 200 or stored.read_bytes() != jpeg:
            raise AssertionError("duplicate upload overwrote or was rejected")
        if duplicate.json().get("config") != client_config_payload():
            raise AssertionError("duplicate response omitted current config")
        if list(stored.parent.glob("*.jpg")) != [stored]:
            raise AssertionError("duplicate upload created another file")

        invalid = requests.post(
            url,
            data={"hostname": "LIN-PC01", "username": "child"},
            files={"file": ("20261003_162001_00.jpg", io.BytesIO(b"\xff\xd8not-a-jpeg"), "image/jpeg")},
            timeout=5,
        )
        if invalid.status_code != 400:
            raise AssertionError(f"invalid jpeg was not rejected: {invalid.status_code}")
        if (stored.parent / "20261003_162001_00.jpg").exists():
            raise AssertionError("invalid jpeg created a file")

        bad_date = requests.post(
            url,
            data={"hostname": "LIN-PC01", "username": "child"},
            files={"file": ("20260231_120000_00.jpg", io.BytesIO(jpeg), "image/jpeg")},
            timeout=5,
        )
        if bad_date.status_code != 400:
            raise AssertionError("impossible date was accepted")

        started = time.perf_counter()
        failed = upload_jpeg("127.0.0.1", "LIN-PC01", "child", filename, jpeg, port=55551)
        elapsed = time.perf_counter() - started
        if failed or elapsed > 6:
            raise AssertionError(f"unavailable server was not a fast failure: {failed} {elapsed:.2f}s")

        logging.info(
            "server self-test passed: %s bytes=%s port=%s duplicate=ok invalid=400",
            stored,
            stored.stat().st_size,
            PORT,
        )
    finally:
        server.close()


def run_retention_self_test() -> None:
    import tempfile

    now = datetime(2026, 10, 4, 12, 0, 0)
    root = Path(tempfile.mkdtemp(prefix="phase6-retention-"))
    identity = root / "LIN-PC01_child"

    def write_named(folder: str, name: str, payload: bytes = b"jpg") -> Path:
        destination = identity / folder
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / name
        path.write_bytes(payload)
        return path

    old = write_named("20260919", "20260919_115959_00.jpg")
    exact = write_named("20260920", "20260920_120000_00.jpg")
    young = write_named("20260921", "20260921_120000_00.jpg")
    invalid_name = write_named("20260920", "bad.jpg")
    invalid_date = write_named("20260231", "20260231_120000_00.jpg")
    mismatch = write_named("20260920", "20260919_120000_00.jpg")
    temporary = write_named("20260920", "20260920_120000_00.jpg.tmp")
    png = write_named("20260920", "20260920_120000_00.png")
    stray = root / "notes.txt"
    stray.write_text("keep", encoding="utf-8")
    candidates = {path.name for path in find_retention_candidates(root, 14, now)}
    if candidates != {old.name}:
        raise AssertionError(f"retention candidates mismatch: {candidates}")
    for kept in (exact, young, invalid_name, invalid_date, mismatch, temporary, png, stray):
        if not kept.exists():
            raise AssertionError(f"non-candidate missing before delete: {kept}")
    state = root / "server_retention_state.json"
    result = run_retention_check(root, 14, state, now, decider=lambda *_args: True)
    if result["deleted"] != 1 or old.exists() or not exact.exists() or not stray.exists():
        raise AssertionError(f"candidate deletion mismatch: {result}")
    second = run_retention_check(root, 14, state, now, decider=lambda *_args: True)
    if not second["skipped"]:
        raise AssertionError("same-day retention check ran again")
    save_retention_state(state, "2026-10-03")
    third = run_retention_check(root, 14, state, now, decider=lambda *_args: False)
    if third["skipped"]:
        raise AssertionError("yesterday state blocked today's check")
    state.write_text("{bad", encoding="utf-8")
    fourth = run_retention_check(root, 14, state, now, decider=lambda *_args: False)
    if fourth["skipped"]:
        raise AssertionError("corrupt state was treated as already checked")
    failing = write_named("20260901", "20260901_010000_00.jpg")
    other = write_named("20260901", "20260901_020000_00.jpg")
    state.unlink()
    original_unlink = Path.unlink

    def failing_unlink(path: Path, *args, **kwargs):
        if path == failing:
            raise OSError("simulated delete failure")
        return original_unlink(path, *args, **kwargs)

    Path.unlink = failing_unlink
    try:
        failed = run_retention_check(root, 14, state, now, decider=lambda *_args: True)
    finally:
        Path.unlink = original_unlink
    if failed["failed"] != 1 or not failing.exists() or other.exists():
        raise AssertionError(f"partial delete failure mismatch: {failed}")
    short_root = Path(tempfile.mkdtemp(prefix="phase6-short-"))
    four_days = now - timedelta(days=4)
    two_days = now - timedelta(days=2)
    old_short = short_root / "LIN-PC01_child" / four_days.strftime("%Y%m%d")
    old_short.mkdir(parents=True)
    (old_short / four_days.strftime("%Y%m%d_%H%M%S_00.jpg")).write_bytes(b"old")
    new_short = short_root / "LIN-PC01_child" / two_days.strftime("%Y%m%d")
    new_short.mkdir(parents=True)
    (new_short / two_days.strftime("%Y%m%d_%H%M%S_00.jpg")).write_bytes(b"new")
    short_candidates = {path.name for path in find_retention_candidates(short_root, 3, now)}
    if short_candidates != {four_days.strftime("%Y%m%d_%H%M%S_00.jpg")}:
        raise AssertionError(f"three-day retention mismatch: {short_candidates}")
    stale = Path(tempfile.mkdtemp(prefix="phase6-stale-tmp-")) / "server_retention_state.json"
    stale.with_name(stale.name + ".tmp").write_text("partial", encoding="utf-8")
    save_retention_state(stale, "2026-10-04")
    if not stale.is_file() or stale.with_name(stale.name + ".tmp").exists():
        raise AssertionError("stale retention temporary file blocked the next write")
    protected = write_named("20260901", "20260901_030000_00.jpg")
    state.unlink(missing_ok=True)

    def broken_scan(*_args, **_kwargs):
        raise PermissionError("simulated storage scan failure")

    original_scan = find_retention_candidates
    globals()["find_retention_candidates"] = broken_scan
    try:
        failed_scan = run_retention_check(root, 14, state, now, decider=lambda *_args: True)
    finally:
        globals()["find_retention_candidates"] = original_scan
    if failed_scan.get("deleted") != 0 or not protected.exists() or "error" not in failed_scan:
        raise AssertionError(f"retention scan failure deleted files or crashed: {failed_scan}")
    logging.info("retention self-test passed")


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    args = parse_args(argv)
    config_path = CONFIG_PATH
    if args.self_test:
        import tempfile

        config_path = Path(tempfile.mkdtemp(prefix="phase5-server-config-")) / "server_config.json"
        missing = load_server_config(config_path, storage_override=args.storage_root)
        if missing["jpeg_quality"] != 40 or missing["server_image_retention_days"] != 14:
            raise AssertionError(f"default server config mismatch: {missing}")
        config_path.write_text("{not json", encoding="utf-8")
        recovered = load_server_config(config_path, storage_override=args.storage_root)
        if recovered["screenshot_interval"] != 20:
            raise AssertionError("corrupt server config did not fall back")
        config_path.write_text(
            json.dumps({"jpeg_quality": 5, "screenshot_interval": 0, "storage_root": ""}),
            encoding="utf-8",
        )
        invalid = load_server_config(config_path, storage_override=args.storage_root)
        if invalid["jpeg_quality"] != 40 or invalid["screenshot_interval"] != 20:
            raise AssertionError(f"invalid server config was accepted: {invalid}")
        windows_root = sanitize_server_config({"storage_root": r"D:\ScreenshotServer"})
        if windows_root["storage_root"] != r"D:\ScreenshotServer":
            raise AssertionError("Windows storage path was rejected")
        relative_root = sanitize_server_config({"storage_root": "dev_storage"})
        if relative_root["storage_root"] != "dev_storage":
            raise AssertionError("relative storage path was rejected")
        storage_root = args.storage_root or Path(tempfile.mkdtemp(prefix="phase5-storage-"))
        if args.storage_root is not None and Path(invalid["storage_root"]) != args.storage_root:
            raise AssertionError("CLI storage override did not win")
        isolated = load_server_config(config_path, storage_override=storage_root)
        if Path(isolated["storage_root"]) != storage_root:
            raise AssertionError("self-test storage root was not isolated")
        untouched = Path(tempfile.mkdtemp(prefix="phase5-default-config-")) / "server_config.json"
        defaulted = load_server_config(untouched)
        if defaulted["storage_root"] != DEFAULT_SERVER_CONFIG["storage_root"]:
            raise AssertionError("omitted storage override did not use config default")
        if CONFIG_PATH != Path(r"C:\ProgramData\ScreenshotServer\server_config.json"):
            raise AssertionError("server config path is not fixed")
        custom = {
            "storage_root": "dev_storage",
            "screenshot_interval": 30,
            "jpeg_quality": 50,
            "client_cache_days": 5,
            "server_image_retention_days": 14,
        }
        plain_path = Path(tempfile.mkdtemp(prefix="phase5-nobom-")) / "server_config.json"
        plain_path.write_bytes(json.dumps(custom).encode("utf-8"))
        plain = load_server_config(plain_path)
        bom_path = Path(tempfile.mkdtemp(prefix="phase5-bom-")) / "server_config.json"
        bom_path.write_bytes(b"\xef\xbb\xbf" + json.dumps(custom).encode("utf-8"))
        bom = load_server_config(bom_path)
        for loaded in (plain, bom):
            if (
                loaded["screenshot_interval"] != 30
                or loaded["jpeg_quality"] != 50
                or loaded["client_cache_days"] != 5
            ):
                raise AssertionError(f"UTF-8 config was reset to defaults: {loaded}")
        if not bom_path.read_bytes().startswith(b"{") or bom_path.read_bytes().startswith(b"\xef\xbb\xbf"):
            raise AssertionError("server config save started writing a BOM")
        run_retention_self_test()
        run_self_test(storage_root)
        return 0
    loaded = load_server_config(config_path, storage_override=args.storage_root)
    try:
        run_retention_check(
            STORAGE_ROOT,
            int(loaded["server_image_retention_days"]),
            retention_state_path(config_path),
        )
    except Exception as exc:
        logging.error("Retention check error: %s", exc)
    logging.info(
        "Server startup config=%s storage=%s interval=%s quality=%s cache_days=%s retention_days=%s",
        config_path,
        loaded["storage_root"],
        loaded["screenshot_interval"],
        loaded["jpeg_quality"],
        loaded["client_cache_days"],
        loaded["server_image_retention_days"],
    )
    logging.info("Listening on %s:%s storage=%s", HOST, PORT, STORAGE_ROOT)
    serve(app, host=HOST, port=PORT, threads=4)
    return 0


if __name__ == "__main__":
    import atexit

    atexit.register(close_logging)
    raise SystemExit(main())
