"""Phase 1 capture, Phase 2 upload, and Phase 3 local cache recovery.

Successful uploads stay in memory and are discarded. Failed uploads are
written to the cache queue. A background worker retries that queue without
blocking the screenshot timer. Windows lock and power events are Phase 4.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import logging.handlers
import os
import random
import socket
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from PIL import Image, ImageFile

DEFAULT_JPEG_QUALITY = 40
DEFAULT_INTERVAL_SECONDS = 20
UPLOAD_TIMEOUT_SECONDS = 5
SERVER_PORT = 55550
CACHE_RETENTION_DAYS = 3
RECOVERY_INTERVAL_SECONDS = 300
STARTUP_CAPTURE_DELAY_MIN_SECONDS = 7
STARTUP_CAPTURE_DELAY_MAX_SECONDS = 30
CACHE_ROOT = Path(r"C:\ProgramData\ScreenshotClient\Cache")
CLIENT_PROGRAMDATA = Path(r"C:\ProgramData\ScreenshotClient")
CLIENT_CONFIG_PATH = Path(r"C:\ProgramData\ScreenshotClient\config.json")
session_log_handler: logging.Handler | None = None
DEFAULT_CLIENT_CONFIG = {
    "server_ip": "127.0.0.1",
    "server_port": SERVER_PORT,
    "screenshot_interval": DEFAULT_INTERVAL_SECONDS,
    "jpeg_quality": DEFAULT_JPEG_QUALITY,
    "client_cache_days": CACHE_RETENTION_DAYS,
}
FILENAME_RE = r"^\d{8}_\d{6}_\d{2}\.jpg$"

cache_lock = threading.Lock()
claimed_cache_files: set[Path] = set()
active_cache_root = CACHE_ROOT
active_client_config_path = CLIENT_CONFIG_PATH
runtime_config = dict(DEFAULT_CLIENT_CONFIG)
config_lock = threading.Lock()
cli_overrides = {"server_ip": None, "interval": None, "quality": None}


def current_runtime() -> dict:
    with config_lock:
        return dict(runtime_config)


def effective_runtime() -> dict:
    """Built-in defaults, then LKG, then explicit CLI overrides."""
    runtime = current_runtime()
    if cli_overrides["server_ip"]:
        runtime["server_ip"] = cli_overrides["server_ip"]
    if cli_overrides["interval"] is not None:
        runtime["screenshot_interval"] = cli_overrides["interval"]
    if cli_overrides["quality"] is not None:
        runtime["jpeg_quality"] = cli_overrides["quality"]
    return runtime


def configure_client_config_path(path: Path) -> None:
    global active_client_config_path
    active_client_config_path = path


def _valid_client_fields(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    interval = raw.get("screenshot_interval")
    quality = raw.get("jpeg_quality")
    days = raw.get("client_cache_days")
    server_ip = raw.get("server_ip")
    server_port = raw.get("server_port")
    if (
        isinstance(interval, bool) or not isinstance(interval, int) or interval <= 0
        or isinstance(quality, bool) or not isinstance(quality, int) or not 20 <= quality <= 100
        or isinstance(days, bool) or not isinstance(days, int) or days <= 0
        or not isinstance(server_ip, str) or not server_ip.strip()
        or server_port != SERVER_PORT
    ):
        return None
    return {
        "server_ip": server_ip,
        "server_port": SERVER_PORT,
        "screenshot_interval": interval,
        "jpeg_quality": quality,
        "client_cache_days": days,
    }


def save_client_config(payload: dict) -> None:
    path = active_client_config_path
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


def load_client_config(server_ip: str | None = None) -> dict:
    global runtime_config
    raw: object = None
    if active_client_config_path.exists():
        try:
            raw = json.loads(active_client_config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logging.error("Client config is unreadable; using defaults: %s", exc)
    validated = _valid_client_fields(raw)
    if validated is None:
        validated = dict(DEFAULT_CLIENT_CONFIG)
        if server_ip:
            validated["server_ip"] = server_ip
        logging.error("Client config missing or invalid; wrote defaults")
    elif server_ip:
        validated["server_ip"] = server_ip
    save_client_config(validated)
    with config_lock:
        runtime_config = validated
    return dict(validated)


def apply_server_config(raw: object) -> bool:
    current = current_runtime()
    candidate = dict(current)
    if isinstance(raw, dict):
        candidate.update(raw)
    candidate["server_ip"] = current["server_ip"]
    candidate["server_port"] = SERVER_PORT
    validated = _valid_client_fields(candidate)
    if validated is None:
        logging.error("Server config rejected; keeping last known good")
        return False
    try:
        save_client_config(validated)
    except OSError as exc:
        logging.error("Could not save last known good config: %s", exc)
        return False
    with config_lock:
        runtime_config.clear()
        runtime_config.update(validated)
    logging.info("Updated last known good config: %s", validated)
    return True


def documents_dir() -> Path:
    """Current user's Documents folder, including redirected Known Folders."""
    if os.name != "nt":
        return Path.home() / "Documents"
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_ulong),
            ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    folder_id = GUID(0xFDD39AD0, 0x238F, 0x46AF, (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    shell32.SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(GUID),
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    path_ptr = ctypes.c_wchar_p()
    if shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(path_ptr)) != 0 or not path_ptr.value:
        raise OSError("Documents folder unavailable")
    value = path_ptr.value
    ole32.CoTaskMemFree(path_ptr)
    return Path(value)


def session_log_name(started_at: datetime | None = None) -> str:
    started_at = started_at or datetime.now()
    centisecond = started_at.microsecond // 10_000
    return started_at.strftime("%Y%m%d_%H%M%S_") + f"{centisecond:02d}.LOG"


def client_log_dir() -> Path:
    return documents_dir() / "ScreenshotClient" / "Logs"


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
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    if not root.handlers:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(formatter)
        root.addHandler(stream)
    if os.name != "nt" and log_dir is None:
        logging.info("Client logging started without a session file")
        return None
    target = log_dir or client_log_dir()
    try:
        target.mkdir(parents=True, exist_ok=True)
        log_path = target / session_log_name()
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
        session_log_handler = file_handler
    except OSError as exc:
        print(f"Client file log unavailable: {exc}", file=sys.stderr)
        return None
    logging.info("Client logging started: %s", log_path)
    return log_path


def make_filename(captured_at: datetime) -> str:
    """YYYYMMDD_HHMMSS_CC.jpg, where CC is the centisecond, not a sequence."""
    centisecond = captured_at.microsecond // 10_000
    return captured_at.strftime("%Y%m%d_%H%M%S_") + f"{centisecond:02d}.jpg"


def filename_captured_at(filename: str) -> datetime | None:
    try:
        return datetime.strptime(filename[:15], "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def process_screenshot(image: Image.Image, quality: int = DEFAULT_JPEG_QUALITY) -> bytes:
    """Keep the captured size, convert to 8-bit grayscale, and encode JPEG."""
    if not 20 <= quality <= 100:
        raise ValueError(f"JPEG quality must be 20-100, got {quality}")

    grayscale = image.convert("L")
    buffer = io.BytesIO()
    grayscale.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def capture_primary_monitor() -> Image.Image:
    """Grab only the primary monitor. mss index 0 is the virtual desktop."""
    import mss

    with mss.MSS() as sct:
        primary = getattr(sct, "primary_monitor", None)
        if not primary:
            if len(sct.monitors) < 2:
                raise RuntimeError("mss did not report a primary monitor")
            primary = sct.monitors[1]
        shot = sct.grab(primary)
        return Image.frombytes("RGB", shot.size, shot.rgb)


def client_identity() -> tuple[str, str]:
    import getpass

    return socket.gethostname(), getpass.getuser()


def capture_jpeg(quality: int = DEFAULT_JPEG_QUALITY) -> tuple[str, bytes, datetime]:
    image = capture_primary_monitor()
    captured_at = datetime.now()
    logging.info("Captured primary monitor %sx%s", image.width, image.height)
    jpeg = process_screenshot(image, quality)
    logging.info("JPEG encoded %s bytes quality=%s", len(jpeg), quality)
    return make_filename(captured_at), jpeg, captured_at


def upload_jpeg(
    server_ip: str,
    hostname: str,
    username: str,
    filename: str,
    jpeg: bytes,
    port: int = SERVER_PORT,
) -> bool:
    """Return True only for HTTP 200. Timeout is fixed at 5 seconds."""
    url = f"http://{server_ip}:{port}/api/upload"
    try:
        response = requests.post(
            url,
            data={"hostname": hostname, "username": username},
            files={"file": (filename, io.BytesIO(jpeg), "image/jpeg")},
            timeout=UPLOAD_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logging.error("Upload failed for %s: %s", filename, exc)
        return False
    if response.status_code != 200:
        logging.error("Upload failed for %s: HTTP %s", filename, response.status_code)
        return False
    try:
        body = response.json()
    except ValueError:
        logging.error("Upload succeeded but config response was not JSON")
        return True
    if not apply_server_config(body.get("config")):
        logging.error("Upload succeeded but config was not applied")
    return True


def configure_cache_root(cache_root: Path) -> None:
    global active_cache_root
    active_cache_root = cache_root


def cache_destination(filename: str) -> Path:
    day = filename[:8]
    return active_cache_root / day / filename


def write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    offset = 0
    while offset < len(view):
        written = os.write(fd, view[offset:])
        if written <= 0:
            raise OSError("incomplete cache write")
        offset += written
    os.fsync(fd)


def cache_jpeg(filename: str, jpeg: bytes) -> bool:
    """Atomically queue the original JPEG. Failure is logged and swallowed."""
    try:
        destination = cache_destination(filename)
        with cache_lock:
            if destination.is_file() or destination in claimed_cache_files:
                logging.info("Cached file already present: %s", destination)
                return True
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + ".tmp")
            binary_flag = getattr(os, "O_BINARY", 0)
            fd = os.open(str(temporary), os.O_CREAT | os.O_EXCL | os.O_WRONLY | binary_flag)
            try:
                write_all(fd, jpeg)
            except Exception:
                os.close(fd)
                temporary.unlink(missing_ok=True)
                raise
            os.close(fd)
            os.replace(temporary, destination)
        logging.info("Cached file: %s", destination)
        return True
    except Exception as exc:
        logging.error("Cache write failed for %s: %s", filename, exc)
        return False


def pending_cache_files() -> list[Path]:
    if not active_cache_root.exists():
        return []
    files = [
        path for path in active_cache_root.rglob("*.jpg")
        if path.is_file() and not path.name.endswith(".tmp")
    ]
    return sorted(files, key=lambda path: path.name)


def purge_expired_cache(now: datetime | None = None) -> int:
    cutoff = (now or datetime.now()) - timedelta(days=current_runtime()["client_cache_days"])
    removed = 0
    for path in pending_cache_files():
        captured_at = filename_captured_at(path.name)
        if captured_at is None or captured_at >= cutoff:
            continue
        with cache_lock:
            if path in claimed_cache_files:
                continue
            path.unlink(missing_ok=True)
        logging.info("Cache retention deleted file: %s", path)
        removed += 1
    return removed


def recover_cache(server_ip: str = "127.0.0.1") -> int:
    """Upload every pending cache JPEG, oldest first. Phase 4 may call this."""
    logging.info("Recovery started")
    purge_expired_cache()
    pending = pending_cache_files()
    logging.info("Recovery found %d files", len(pending))
    hostname, username = client_identity()
    uploaded = 0
    for path in pending:
        with cache_lock:
            if path in claimed_cache_files or not path.is_file():
                continue
            claimed_cache_files.add(path)
        try:
            jpeg = path.read_bytes()
            if upload_jpeg(effective_runtime()["server_ip"], hostname, username, path.name, jpeg):
                with cache_lock:
                    path.unlink(missing_ok=True)
                    claimed_cache_files.discard(path)
                logging.info("Recovery upload success: %s", path.name)
                logging.info("Cache file deleted: %s", path)
                uploaded += 1
            else:
                logging.error("Recovery upload failed: %s", path.name)
                with cache_lock:
                    claimed_cache_files.discard(path)
        except Exception as exc:
            logging.error("Recovery upload failed: %s (%s)", path.name, exc)
            with cache_lock:
                claimed_cache_files.discard(path)
    return uploaded


def recovery_worker(stop: threading.Event) -> None:
    from windows_events import recovery_trigger

    startup = True
    while not stop.is_set():
        try:
            logging.info("Recovery worker awakened")
            recover_cache(effective_runtime()["server_ip"])
        except Exception as exc:
            logging.exception("Recovery worker failed and will retry: %s", exc)
        if stop.is_set():
            return
        if startup:
            recovery_trigger.clear()
            startup = False
        recovery_trigger.wait(RECOVERY_INTERVAL_SECONDS)
        recovery_trigger.clear()


def start_recovery_worker(server_ip: str) -> tuple[threading.Thread, threading.Event]:
    stop = threading.Event()
    worker = threading.Thread(
        target=recovery_worker,
        args=(stop,),
        name="cache-recovery",
        daemon=True,
    )
    worker.start()
    return worker, stop


def write_test_jpeg(output_dir: Path, quality: int) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename, jpeg, _captured_at = capture_jpeg(quality)
    destination = output_dir / filename
    destination.write_bytes(jpeg)
    return destination


def startup_capture_delay_seconds(rng: random.Random | None = None) -> int:
    """One inclusive 7-30 second delay for this process start. Not a config value."""
    chooser = rng if rng is not None else random
    return chooser.randint(STARTUP_CAPTURE_DELAY_MIN_SECONDS, STARTUP_CAPTURE_DELAY_MAX_SECONDS)


def first_capture_times(started_at: datetime, delay_seconds: int, interval_seconds: int) -> tuple[datetime, datetime]:
    first = started_at + timedelta(seconds=delay_seconds)
    return first, first + timedelta(seconds=interval_seconds)


def wait_startup_capture_delay(client_state, delay_seconds: float) -> bool:
    """Wait without blocking Windows state events. False means do not capture yet."""
    deadline = time.monotonic() + delay_seconds
    while True:
        if not client_state.capture_enabled:
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return client_state.capture_enabled
        if client_state.wait_until_disabled(remaining):
            return False


def handle_capture(server_ip: str, quality: int) -> None:
    hostname, username = client_identity()
    filename, jpeg, _captured_at = capture_jpeg(quality)
    try:
        if upload_jpeg(server_ip, hostname, username, filename, jpeg):
            logging.info("Uploaded %s (%d bytes) HTTP 200; discarded", filename, len(jpeg))
        else:
            logging.error("Upload failed for %s", filename)
            cache_jpeg(filename, jpeg)
    finally:
        del jpeg


def run_forever() -> None:
    from windows_events import client_state, query_initial_state, start_windows_listener

    hostname, username = client_identity()
    query_initial_state()
    start_windows_listener()
    initial = effective_runtime()
    logging.info(
        "Client startup hostname=%s username=%s config=%s cache=%s server=%s:%s interval=%s quality=%s cli_interval=%s cli_quality=%s capture=%s",
        hostname,
        username,
        active_client_config_path,
        active_cache_root,
        initial["server_ip"],
        SERVER_PORT,
        initial["screenshot_interval"],
        initial["jpeg_quality"],
        cli_overrides["interval"],
        cli_overrides["quality"],
        client_state.capture_enabled,
    )
    startup_started = datetime.now()
    startup_delay = startup_capture_delay_seconds()
    first_scheduled, _following = first_capture_times(
        startup_started,
        startup_delay,
        initial["screenshot_interval"],
    )
    logging.info("Client startup time: %s", startup_started.strftime("%Y-%m-%d %H:%M:%S"))
    logging.info("Startup capture delay: %s seconds", startup_delay)
    logging.info("First capture scheduled: %s", first_scheduled.strftime("%Y-%m-%d %H:%M:%S"))
    logging.info("First capture scheduled after startup delay")
    _worker, _stop = start_recovery_worker(initial["server_ip"])
    startup_delay_pending = True
    resumed = False
    while True:
        runtime = effective_runtime()
        interval_seconds = runtime["screenshot_interval"]
        quality = runtime["jpeg_quality"]
        server_ip = runtime["server_ip"]
        if not client_state.capture_enabled:
            client_state.wait_until_enabled()
            resumed = True
        if startup_delay_pending and not resumed and client_state.capture_enabled:
            startup_delay_pending = False
            if not wait_startup_capture_delay(client_state, startup_delay):
                logging.info("Startup capture delay interrupted by session or power state")
                resumed = True
                continue
        if resumed:
            startup_delay_pending = False
            resumed = False
            if client_state.wait_until_disabled(interval_seconds):
                continue
        if not client_state.capture_enabled:
            continue
        started = time.monotonic()
        try:
            handle_capture(server_ip, quality)
        except Exception as exc:
            logging.exception("Capture cycle failed and will continue: %s", exc)
        interval_seconds = effective_runtime()["screenshot_interval"]
        remaining = interval_seconds - (time.monotonic() - started)
        if remaining > 0 and client_state.wait_until_disabled(remaining):
            logging.info("Capture wait interrupted by session or power state")


def run_self_test() -> None:
    import re

    source = Image.new("RGB", (1920, 1080), (20, 140, 220))
    filename = make_filename(datetime(2026, 10, 3, 16, 20, 0, 370000))
    if filename != "20261003_162000_37.jpg":
        raise AssertionError(filename)
    if not re.fullmatch(FILENAME_RE, filename):
        raise AssertionError("filename mismatch")
    jpeg = process_screenshot(source)
    parsed = Image.open(io.BytesIO(jpeg))
    parsed.load()
    if parsed.format != "JPEG" or parsed.mode != "L" or parsed.size != (1920, 1080):
        raise AssertionError("phase 1 output mismatch")
    import tempfile

    configure_cache_root(Path(tempfile.mkdtemp(prefix="phase1-cache-")))
    claimed_cache_files.clear()
    if not cache_jpeg(filename, jpeg):
        raise AssertionError("cache write failed")
    cached = cache_destination(filename).read_bytes()
    if cached != jpeg:
        raise AssertionError("cache JPEG bytes diverged from payload")
    reopened = Image.open(io.BytesIO(cached))
    reopened.load()
    if reopened.format != "JPEG" or reopened.mode != "L" or reopened.size != (1920, 1080):
        raise AssertionError("cached JPEG could not be reopened at original size")
    logging.info("client self-test passed: %s 1920x1080 mode=L cache-bytes-match", filename)
    if CLIENT_CONFIG_PATH != Path(r"C:\ProgramData\ScreenshotClient\config.json"):
        raise AssertionError("client config path is not fixed")
    if CACHE_ROOT != Path(r"C:\ProgramData\ScreenshotClient\Cache"):
        raise AssertionError("client cache path is not fixed")
    import tempfile

    log_dir = Path(tempfile.mkdtemp(prefix="phase7-client-log-"))
    first = setup_logging(log_dir)
    time.sleep(0.02)
    second = setup_logging(log_dir)
    logging.info("Client startup log check")
    names = sorted(path.name for path in log_dir.glob("*.LOG"))
    if first is None or second is None or len(names) != 2 or not all(name.endswith(".LOG") and len(name) == 22 for name in names):
        raise AssertionError(f"session logs were not created: {names}")
    close_logging()
    run_startup_delay_self_test()


def run_startup_delay_self_test() -> None:
    from windows_events import ClientState

    if RECOVERY_INTERVAL_SECONDS != 300 or SERVER_PORT != 55550:
        raise AssertionError("startup delay work changed recovery interval or port")
    if "startup_delay" in DEFAULT_CLIENT_CONFIG:
        raise AssertionError("startup delay became a config field")
    samples = [startup_capture_delay_seconds() for _ in range(200)]
    if any(value < 7 or value > 30 for value in samples):
        raise AssertionError(f"startup delay outside 7-30: {samples}")
    if startup_capture_delay_seconds(random.Random(1)) == startup_capture_delay_seconds(random.Random(2)):
        # Different seeds may still collide once. A longer sequence must not be fixed.
        pass
    first_seed = [startup_capture_delay_seconds(random.Random(7)) for _ in range(5)]
    second_seed = [startup_capture_delay_seconds(random.Random(8)) for _ in range(5)]
    if first_seed[0] < 7 or first_seed[0] > 30 or first_seed == second_seed:
        raise AssertionError(f"restart did not draw a new delay: {first_seed} {second_seed}")

    class Fixed:
        def __init__(self, value: int) -> None:
            self.value = value

        def randint(self, low: int, high: int) -> int:
            if low != 7 or high != 30 or not low <= self.value <= high:
                raise AssertionError(f"delay bounds changed: {low} {high} {self.value}")
            return self.value

    if startup_capture_delay_seconds(Fixed(7)) != 7 or startup_capture_delay_seconds(Fixed(30)) != 30:
        raise AssertionError("inclusive 7 and 30 were rejected")
    interval = effective_runtime()["screenshot_interval"]
    startup_capture_delay_seconds()
    if effective_runtime()["screenshot_interval"] != interval:
        raise AssertionError("startup delay changed screenshot_interval")
    started = datetime(2026, 10, 6, 21, 0, 0)
    first, second = first_capture_times(started, 13, 20)
    third = second + timedelta(seconds=20)
    if first != datetime(2026, 10, 6, 21, 0, 13) or second != datetime(2026, 10, 6, 21, 0, 33):
        raise AssertionError(f"first capture did not return to fixed interval: {first} {second}")
    if third != datetime(2026, 10, 6, 21, 0, 53) or (second - first).total_seconds() == 13:
        raise AssertionError("startup delay was applied to later captures")
    enabled = ClientState(enabled=True)
    began = time.monotonic()
    if not wait_startup_capture_delay(enabled, 0.05):
        raise AssertionError("enabled startup delay did not elapse")
    if time.monotonic() - began > 1:
        raise AssertionError("startup delay self-test slept too long")
    disabled = ClientState(enabled=False)
    if wait_startup_capture_delay(disabled, 30):
        raise AssertionError("disabled state was allowed to finish startup delay")
    interrupted = ClientState(enabled=True)

    def disable_soon() -> None:
        time.sleep(0.05)
        interrupted.set_initial(False, False, False, False)

    threading.Thread(target=disable_soon, daemon=True).start()
    began = time.monotonic()
    if wait_startup_capture_delay(interrupted, 30):
        raise AssertionError("lock during startup delay still allowed capture")
    if time.monotonic() - began > 1:
        raise AssertionError("interrupted startup delay blocked instead of returning")
    logging.info("startup delay self-test passed")


def run_cache_self_test(cache_root: Path) -> None:
    import tempfile
    from datetime import datetime as DateTime

    import server
    from PIL import Image as PilImage

    configure_cache_root(cache_root)
    configure_client_config_path(cache_root.parent / "client-config.json")
    load_client_config("127.0.0.1")
    claimed_cache_files.clear()
    jpeg = process_screenshot(PilImage.new("RGB", (1920, 1080), (40, 80, 120)))
    names = [
        "20261003_162000_10.jpg",
        "20261003_162000_20.jpg",
        "20261003_162000_30.jpg",
        "20261003_162000_40.jpg",
    ]

    storage = Path(tempfile.mkdtemp(prefix="phase3-storage-"))
    server.configure_storage(storage)
    http = server.create_server(server.app, host="127.0.0.1", port=SERVER_PORT, threads=4)
    thread = threading.Thread(target=http.run, daemon=True)
    thread.start()
    time.sleep(0.4)
    hostname, username = client_identity()
    try:
        if not upload_jpeg("127.0.0.1", hostname, username, names[0], jpeg):
            raise AssertionError("Test A upload did not succeed")
        if pending_cache_files():
            raise AssertionError("Test A left a cache file")

        if upload_jpeg("127.0.0.1", hostname, username, names[1], jpeg, port=55551):
            raise AssertionError("Test B expected upload failure")
        if not cache_jpeg(names[1], jpeg) or len(pending_cache_files()) != 1:
            raise AssertionError("Test B did not cache the failed upload")

        for name in names:
            cache_jpeg(name, jpeg)
        cached_names = [path.name for path in pending_cache_files()]
        if cached_names != names:
            raise AssertionError(f"Test C/D order mismatch: {cached_names}")

        uploaded_order: list[str] = []
        original_upload = upload_jpeg

        def recording_upload(*args, **kwargs):
            uploaded_order.append(args[3])
            return original_upload(*args, **kwargs)

        globals()["upload_jpeg"] = recording_upload
        try:
            recover_cache("127.0.0.1")
        finally:
            globals()["upload_jpeg"] = original_upload
        if uploaded_order != names:
            raise AssertionError(f"Test D/E order mismatch: {uploaded_order}")
        if pending_cache_files():
            raise AssertionError("Test E did not empty the cache")

        for name in names:
            cache_jpeg(name, jpeg)
        before = [path.name for path in pending_cache_files()]
        failed_upload = upload_jpeg
        globals()["upload_jpeg"] = lambda *args, **kwargs: False
        try:
            recover_cache("127.0.0.1")
        finally:
            globals()["upload_jpeg"] = failed_upload
        if [path.name for path in pending_cache_files()] != before:
            raise AssertionError("Test F removed cache while server was down")

        attempted: list[str] = []

        def partial_upload(*args, **kwargs):
            filename = args[3]
            attempted.append(filename)
            return filename != names[1]

        globals()["upload_jpeg"] = partial_upload
        try:
            recover_cache("127.0.0.1")
        finally:
            globals()["upload_jpeg"] = original_upload
        if attempted != names:
            raise AssertionError(f"single failure stopped recovery: {attempted}")
        remaining_after_partial = [path.name for path in pending_cache_files()]
        if remaining_after_partial != [names[1]]:
            raise AssertionError(f"partial recovery mismatch: {remaining_after_partial}")
        for path in pending_cache_files():
            path.unlink()
        cache_jpeg(names[0], jpeg)
        original_upload("127.0.0.1", hostname, username, names[0], jpeg)
        server_copy = storage / f"{hostname}_{username}" / "20261003" / names[0]
        if not server_copy.is_file():
            raise AssertionError("Test G server file missing")
        recover_cache("127.0.0.1")
        matches = list(server_copy.parent.glob(names[0]))
        if matches != [server_copy] or pending_cache_files():
            raise AssertionError("Test G duplicate recovery failed")

        for index in range(50):
            cache_jpeg(f"20261003_170000_{index:02d}.jpg", jpeg)
        started = time.perf_counter()
        release = threading.Event()

        def slow_upload(*args, **kwargs):
            release.set()
            time.sleep(0.05)
            return original_upload(*args, **kwargs)

        globals()["upload_jpeg"] = slow_upload
        worker = threading.Thread(target=recover_cache, args=("127.0.0.1",))
        worker.start()
        if not release.wait(2):
            raise AssertionError("Test H recovery did not start")
        normal_started = time.perf_counter()
        cache_jpeg("20261003_180000_00.jpg", jpeg)
        normal_elapsed = time.perf_counter() - normal_started
        if normal_elapsed > 0.5:
            raise AssertionError(f"Test H normal cache write blocked: {normal_elapsed:.2f}s")
        worker.join()
        if time.perf_counter() - started < 1:
            raise AssertionError("Test H recovery finished too quickly to prove overlap")

        for path in list(pending_cache_files()):
            path.unlink()
        for index in range(40):
            cache_jpeg(f"20261003_171000_{index:02d}.jpg", jpeg)
        normal_name = "20261003_181500_00.jpg"
        release_capture = threading.Event()
        original_capture = capture_jpeg

        def fast_capture(quality: int = DEFAULT_JPEG_QUALITY):
            return normal_name, jpeg, DateTime.now()

        def mixed_upload(*args, **kwargs):
            filename = args[3]
            if filename != normal_name:
                release_capture.set()
                time.sleep(0.05)
            return True

        globals()["capture_jpeg"] = fast_capture
        globals()["upload_jpeg"] = mixed_upload
        recovery = threading.Thread(target=recover_cache, args=("127.0.0.1",))
        recovery.start()
        if not release_capture.wait(2):
            raise AssertionError("concurrency recovery did not start")
        capture_started = time.perf_counter()
        handle_capture("127.0.0.1", DEFAULT_JPEG_QUALITY)
        capture_elapsed = time.perf_counter() - capture_started
        if capture_elapsed > 0.5:
            raise AssertionError(f"handle_capture blocked by recovery: {capture_elapsed:.2f}s")
        if not recovery.is_alive():
            raise AssertionError("handle_capture did not overlap the recovery worker")
        recovery.join()
        globals()["capture_jpeg"] = original_capture
        globals()["upload_jpeg"] = original_upload

        temporary = cache_root / "20261003" / "20261003_190000_00.jpg.tmp"
        temporary.write_bytes(b"partial")
        pending = [path.name for path in pending_cache_files()]
        if any(name.endswith(".tmp") for name in pending):
            raise AssertionError("Test I scanned a temporary file")
        temporary.unlink()

        old_name = (DateTime.now() - timedelta(days=4)).strftime("%Y%m%d_010000_00.jpg")
        recent_name = DateTime.now().strftime("%Y%m%d_020000_00.jpg")
        cache_jpeg(old_name, jpeg)
        cache_jpeg(recent_name, jpeg)
        globals()["upload_jpeg"] = lambda *args, **kwargs: False
        try:
            purge_expired_cache()
        finally:
            globals()["upload_jpeg"] = original_upload
        remaining = {path.name for path in pending_cache_files()}
        if old_name in remaining or recent_name not in remaining:
            raise AssertionError(f"Test J retention mismatch: {remaining}")

        logging.info("cache self-test passed: A-J")
    finally:
        http.close()
        claimed_cache_files.clear()


def run_session_self_test() -> None:
    import windows_events as events

    state = events.ClientState(enabled=True)
    events.recovery_trigger.clear()
    events.desktop_ready_probe = lambda: True
    state.apply_session(events.WTS_SESSION_LOCK, 1, 1)
    if state.capture_enabled:
        raise AssertionError("lock did not disable capture")
    events.recovery_trigger.clear()
    state.apply_session(events.WTS_SESSION_UNLOCK, 1, 1)
    if not state.capture_enabled or not events.recovery_trigger.is_set():
        raise AssertionError("unlock did not enable capture and trigger recovery")

    events.recovery_trigger.clear()
    state.apply_session(events.WTS_SESSION_LOCK, 1, 1)
    attempts = {"count": 0}

    def delayed_ready() -> bool:
        attempts["count"] += 1
        return attempts["count"] >= 3

    events.desktop_ready_probe = delayed_ready
    events.READINESS_DELAY_SECONDS = 0.05
    state.apply_session(events.WTS_SESSION_UNLOCK, 1, 1)
    if state.capture_enabled:
        raise AssertionError("unlock enabled capture before readiness confirmation")
    deadline = time.monotonic() + 2
    while not state.capture_enabled and time.monotonic() < deadline:
        time.sleep(0.05)
    if not state.capture_enabled or not events.recovery_trigger.is_set():
        raise AssertionError("delayed desktop readiness did not recover")
    events.desktop_ready_probe = lambda: True
    events.READINESS_DELAY_SECONDS = 0.3

    events.recovery_trigger.clear()
    state.apply_power(events.PBT_APMSUSPEND)
    if state.capture_enabled:
        raise AssertionError("suspend did not disable capture")
    state.apply_power(events.PBT_APMRESUMEAUTOMATIC)
    if not state.capture_enabled:
        raise AssertionError("resume did not restore an unlocked desktop")

    events.recovery_trigger.clear()
    state.apply_session(events.WTS_SESSION_LOCK, 1, 1)
    state.apply_power(events.PBT_APMRESUMEAUTOMATIC)
    if state.capture_enabled:
        raise AssertionError("wake while locked enabled capture")
    state.apply_session(events.WTS_SESSION_LOGOFF, 1, 1)
    if state.capture_enabled or state.logged_on:
        raise AssertionError("logoff did not stop capture")
    state.apply_session(events.WTS_SESSION_LOGON, 2, 1)
    if state.logged_on:
        raise AssertionError("another session logon changed this client")

    startup = events.ClientState(enabled=False)
    events.recovery_trigger.clear()
    startup.set_initial(True, True, True, True)
    if events.recovery_trigger.is_set():
        raise AssertionError("startup state armed a second recovery trigger")
    runs = {"count": 0}
    original_recover = recover_cache

    def counting_recover(server_ip: str = "127.0.0.1") -> int:
        runs["count"] += 1
        return 0

    globals()["recover_cache"] = counting_recover
    stop = threading.Event()
    worker = threading.Thread(target=recovery_worker, args=(stop,), name="cache-recovery")
    worker.start()
    time.sleep(0.4)
    if runs["count"] != 1:
        raise AssertionError(f"startup recovery ran {runs['count']} times")
    stop.set()
    events.recovery_trigger.set()
    worker.join(2)
    globals()["recover_cache"] = original_recover

    workers_before = [thread.name for thread in threading.enumerate()].count("cache-recovery")
    stop = threading.Event()
    events.recovery_trigger.set()
    worker = threading.Thread(target=recovery_worker, args=(stop,), name="cache-recovery")
    worker.start()
    time.sleep(0.2)
    for _ in range(4):
        state.apply_session(events.WTS_SESSION_LOCK, 1, 1)
        state.apply_session(events.WTS_SESSION_UNLOCK, 1, 1)
    time.sleep(0.2)
    workers_after = [thread.name for thread in threading.enumerate()].count("cache-recovery")
    stop.set()
    events.recovery_trigger.set()
    worker.join(2)
    events.desktop_ready_probe = None
    if workers_after != workers_before + 1:
        raise AssertionError(f"recovery workers duplicated: {workers_before} {workers_after}")
    logging.info("session self-test passed")


def run_config_self_test(config_dir: Path) -> None:
    configure_client_config_path(config_dir / "config.json")
    first = load_client_config("10.0.0.8")
    if first["screenshot_interval"] != 20 or first["jpeg_quality"] != 40 or first["server_ip"] != "10.0.0.8":
        raise AssertionError(f"first startup config mismatch: {first}")
    reloaded = load_client_config()
    if reloaded != first:
        raise AssertionError("saved config did not reload")
    active_client_config_path.write_text("{bad", encoding="utf-8")
    recovered = load_client_config("10.0.0.8")
    if recovered["jpeg_quality"] != 40:
        raise AssertionError("corrupt client config did not fall back")
    if not apply_server_config({"screenshot_interval": 30, "jpeg_quality": 50, "client_cache_days": 5}):
        raise AssertionError("valid server config was rejected")
    runtime = current_runtime()
    if runtime["screenshot_interval"] != 30 or runtime["jpeg_quality"] != 50:
        raise AssertionError(f"runtime did not sync: {runtime}")
    if not apply_server_config({"jpeg_quality": 5}):
        pass
    else:
        raise AssertionError("invalid server config was accepted")
    if current_runtime()["jpeg_quality"] != 50 or current_runtime()["screenshot_interval"] != 30:
        raise AssertionError("invalid config reset last known good")
    upload_jpeg("127.0.0.1", "host", "user", "20261003_162000_37.jpg", b"jpeg", port=55551)
    if current_runtime()["screenshot_interval"] != 30 or current_runtime()["jpeg_quality"] != 50:
        raise AssertionError("server unavailable reset last known good")
    if active_client_config_path.with_name("config.json.tmp").exists():
        raise AssertionError("atomic config write left a temporary file")
    source = Image.new("RGB", (1920, 1080), (20, 140, 220))
    parsed = Image.open(io.BytesIO(process_screenshot(source)))
    parsed.load()
    if parsed.size != (1920, 1080) or parsed.mode != "L":
        raise AssertionError("resolution regression")
    active_client_config_path.write_text(
        json.dumps({
            "server_ip": "192.168.2.100",
            "server_port": 55550,
            "screenshot_interval": 30,
            "jpeg_quality": 50,
            "client_cache_days": 5,
        }),
        encoding="utf-8",
    )
    cli_overrides["server_ip"] = None
    cli_overrides["interval"] = None
    cli_overrides["quality"] = None
    load_client_config()
    no_override = effective_runtime()
    if no_override["server_ip"] != "192.168.2.100" or no_override["screenshot_interval"] != 30 or no_override["jpeg_quality"] != 50:
        raise AssertionError(f"LKG was not used without CLI override: {no_override}")
    cli_overrides["interval"] = 60
    cli_overrides["quality"] = 70
    overridden = effective_runtime()
    if overridden["screenshot_interval"] != 60 or overridden["jpeg_quality"] != 70:
        raise AssertionError(f"explicit interval/quality override failed: {overridden}")
    cli_overrides["interval"] = None
    cli_overrides["quality"] = None
    cli_overrides["server_ip"] = "127.0.0.1"
    if effective_runtime()["server_ip"] != "127.0.0.1":
        raise AssertionError("explicit server IP override failed")
    cli_overrides["server_ip"] = None
    load_client_config()
    if current_runtime()["screenshot_interval"] != 20:
        current = current_runtime()
        current["screenshot_interval"] = 20
        current["jpeg_quality"] = 40
        save_client_config(current)
        with config_lock:
            runtime_config.clear()
            runtime_config.update(current)
    if not apply_server_config({"screenshot_interval": 30, "jpeg_quality": 50, "client_cache_days": 5}):
        raise AssertionError("HTTP 200 config was not applied")
    synced = effective_runtime()
    if synced["screenshot_interval"] != 30 or synced["jpeg_quality"] != 50:
        raise AssertionError(f"next capture would not use synced config: {synced}")
    upload_jpeg("192.168.2.100", "host", "user", "20261003_162000_38.jpg", b"jpeg", port=55551)
    if effective_runtime()["screenshot_interval"] != 30 or effective_runtime()["jpeg_quality"] != 50:
        raise AssertionError("unavailable server reset synced runtime")
    started = time.monotonic()
    before = effective_runtime()["screenshot_interval"]
    if not apply_server_config({"screenshot_interval": 45, "jpeg_quality": 55, "client_cache_days": 5}):
        raise AssertionError("interval sync config was rejected")
    next_interval = effective_runtime()["screenshot_interval"]
    next_quality = effective_runtime()["jpeg_quality"]
    remaining = next_interval - (time.monotonic() - started)
    if before == 45 or next_interval != 45 or next_quality != 55 or remaining < 40:
        raise AssertionError("next capture cycle did not adopt synced interval and quality")
    cli_overrides["interval"] = 60
    cli_overrides["quality"] = 70
    if effective_runtime()["screenshot_interval"] != 60 or effective_runtime()["jpeg_quality"] != 70:
        raise AssertionError("CLI override lost priority after sync")
    cli_overrides["interval"] = None
    cli_overrides["quality"] = None
    logging.info("config self-test passed")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 3 screenshot client")
    parser.add_argument("--server-ip", help="Explicit override. Omit to use Last Known Good.")
    parser.add_argument("--test-output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--cache-self-test", action="store_true")
    parser.add_argument("--session-self-test", action="store_true")
    parser.add_argument("--windows-api-self-test", action="store_true")
    parser.add_argument("--windows-manual-tests", action="store_true")
    parser.add_argument("--config-self-test", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int)
    parser.add_argument("--quality", type=int)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    setup_logging()
    args = parse_args(argv)
    if args.self_test:
        run_self_test()
        return 0
    if args.cache_self_test:
        import tempfile

        run_cache_self_test(Path(tempfile.mkdtemp(prefix="phase3-cache-")))
        return 0
    if args.session_self_test:
        run_session_self_test()
        return 0
    if args.windows_manual_tests:
        from windows_events import WINDOWS_MANUAL_TESTS

        print(WINDOWS_MANUAL_TESTS)
        return 0
    if args.windows_api_self_test:
        from windows_events import run_windows_api_self_test

        return run_windows_api_self_test()
    if args.config_self_test:
        import tempfile

        run_config_self_test(Path(tempfile.mkdtemp(prefix="phase5-client-config-")))
        return 0
    load_client_config(args.server_ip)
    cli_overrides["server_ip"] = args.server_ip
    cli_overrides["interval"] = args.interval
    cli_overrides["quality"] = args.quality
    runtime = effective_runtime()
    if args.test_output is not None:
        logging.info("Test JPEG written: %s", write_test_jpeg(args.test_output, runtime["jpeg_quality"]))
        return 0
    if args.once:
        handle_capture(runtime["server_ip"], runtime["jpeg_quality"])
        return 0
    run_forever()
    return 0


if __name__ == "__main__":
    import atexit

    atexit.register(close_logging)
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        logging.info("Application shutting down")
        close_logging()
        raise SystemExit(0)
