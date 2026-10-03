"""Phase 1 capture, Phase 2 upload, and Phase 3 local cache recovery.

Successful uploads stay in memory and are discarded. Failed uploads are
written to the cache queue. A background worker retries that queue without
blocking the screenshot timer. Windows lock and power events are Phase 4.
"""

from __future__ import annotations

import argparse
import io
import logging
import os
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
CACHE_ROOT = Path(r"C:\ProgramData\ScreenshotClient\Cache")
FILENAME_RE = r"^\d{8}_\d{6}_\d{2}\.jpg$"

cache_lock = threading.Lock()
claimed_cache_files: set[Path] = set()
active_cache_root = CACHE_ROOT


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def scaled_size(width: int, height: int) -> tuple[int, int]:
    """Scale each axis to 25 percent. 1920x1080 becomes 480x270."""
    return (max(1, round(width * 0.25)), max(1, round(height * 0.25)))


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
    """Resize each axis to 25 percent, convert to 8-bit grayscale, encode JPEG."""
    if not 20 <= quality <= 100:
        raise ValueError(f"JPEG quality must be 20-100, got {quality}")

    resized = image.resize(scaled_size(image.width, image.height), Image.Resampling.LANCZOS)
    grayscale = resized.convert("L")
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
    return make_filename(captured_at), process_screenshot(image, quality), captured_at


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
            fd = os.open(str(temporary), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
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
    cutoff = (now or datetime.now()) - timedelta(days=CACHE_RETENTION_DAYS)
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
            if upload_jpeg(server_ip, hostname, username, path.name, jpeg):
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


def recovery_worker(server_ip: str, stop: threading.Event) -> None:
    from windows_events import recovery_trigger

    while not stop.is_set():
        try:
            logging.info("Recovery worker awakened")
            recover_cache(server_ip)
        except Exception as exc:
            logging.exception("Recovery worker failed and will retry: %s", exc)
        if stop.is_set():
            return
        recovery_trigger.wait(RECOVERY_INTERVAL_SECONDS)
        recovery_trigger.clear()


def start_recovery_worker(server_ip: str) -> tuple[threading.Thread, threading.Event]:
    stop = threading.Event()
    worker = threading.Thread(
        target=recovery_worker,
        args=(server_ip, stop),
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


def handle_capture(server_ip: str, quality: int) -> None:
    hostname, username = client_identity()
    filename, jpeg, _captured_at = capture_jpeg(quality)
    try:
        if upload_jpeg(server_ip, hostname, username, filename, jpeg):
            logging.info("Uploaded %s (%d bytes); discarded", filename, len(jpeg))
        else:
            logging.error("Upload failed for %s", filename)
            cache_jpeg(filename, jpeg)
    finally:
        del jpeg


def run_forever(server_ip: str, interval_seconds: int, quality: int) -> None:
    from windows_events import client_state, query_initial_state, start_windows_listener

    hostname, username = client_identity()
    query_initial_state()
    start_windows_listener()
    logging.info(
        "Phase 4 client started. server=%s:%s identity=%s_%s capture=%s",
        server_ip,
        SERVER_PORT,
        hostname,
        username,
        client_state.capture_enabled,
    )
    _worker, _stop = start_recovery_worker(server_ip)
    resumed = False
    while True:
        if not client_state.capture_enabled:
            client_state.wait_until_enabled()
            resumed = True
        if resumed:
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
        remaining = interval_seconds - (time.monotonic() - started)
        if remaining > 0 and client_state.wait_until_disabled(remaining):
            logging.info("Capture wait interrupted by session or power state")


def run_self_test() -> None:
    import re

    source = Image.new("RGB", (1920, 1080), (20, 140, 220))
    filename = make_filename(datetime(2026, 10, 3, 16, 20, 0, 370000))
    if filename != "20261003_162000_37.jpg":
        raise AssertionError(filename)
    if not re.fullmatch(FILENAME_RE, filename) or scaled_size(1920, 1080) != (480, 270):
        raise AssertionError("phase 1 pipeline mismatch")
    parsed = Image.open(io.BytesIO(process_screenshot(source)))
    parsed.load()
    if parsed.format != "JPEG" or parsed.mode != "L" or parsed.size != (480, 270):
        raise AssertionError("phase 1 output mismatch")
    logging.info("client self-test passed: %s 480x270 mode=L", filename)


def run_cache_self_test(cache_root: Path) -> None:
    import tempfile
    from datetime import datetime as DateTime

    import server
    from PIL import Image as PilImage

    configure_cache_root(cache_root)
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
    state.apply_session(events.WTS_SESSION_LOCK, 1, 1)
    if state.capture_enabled:
        raise AssertionError("lock did not disable capture")
    state.apply_session(events.WTS_SESSION_UNLOCK, 1, 1)
    if state.capture_enabled:
        raise AssertionError("unlock enabled capture before desktop ready")
    if events.recovery_trigger.is_set():
        raise AssertionError("unlock triggered recovery before desktop ready")
    state.apply_session(events.WTS_SESSION_DESKTOP_READY, 1, 1)
    if not state.capture_enabled or not events.recovery_trigger.is_set():
        raise AssertionError("desktop ready did not resume and trigger recovery")

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

    workers_before = [thread.name for thread in threading.enumerate()].count("cache-recovery")
    stop = threading.Event()
    events.recovery_trigger.set()
    worker = threading.Thread(target=recovery_worker, args=("127.0.0.1", stop), name="cache-recovery")
    worker.start()
    time.sleep(0.2)
    for _ in range(4):
        state.apply_session(events.WTS_SESSION_LOCK, 1, 1)
        state.apply_session(events.WTS_SESSION_DESKTOP_READY, 1, 1)
    time.sleep(0.2)
    workers_after = [thread.name for thread in threading.enumerate()].count("cache-recovery")
    stop.set()
    events.recovery_trigger.set()
    worker.join(2)
    if workers_after != workers_before + 1:
        raise AssertionError(f"recovery workers duplicated: {workers_before} {workers_after}")
    logging.info("session self-test passed")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 3 screenshot client")
    parser.add_argument("--server-ip", default="127.0.0.1")
    parser.add_argument("--test-output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--cache-self-test", action="store_true")
    parser.add_argument("--session-self-test", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--quality", type=int, default=DEFAULT_JPEG_QUALITY)
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
    if args.test_output is not None:
        logging.info("Test JPEG written: %s", write_test_jpeg(args.test_output, args.quality))
        return 0
    if args.once:
        handle_capture(args.server_ip, args.quality)
        return 0
    run_forever(args.server_ip, args.interval, args.quality)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        logging.info("Stopped by user.")
        raise SystemExit(0)
