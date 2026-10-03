"""Phase 2 upload server.

Listens on TCP 55550 and accepts one endpoint: POST /api/upload.
A 200 is returned only after the JPEG is verified on disk, or when the
same final path already exists. There is no web UI.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import threading
from pathlib import Path

from flask import Flask, jsonify, request
from waitress import create_server, serve

HOST = "0.0.0.0"
PORT = 55550
FILENAME_RE = re.compile(r"^(\d{8})_(\d{6})_(\d{2})\.jpg$")
PHASE2_CONFIG = {
    "screenshot_interval": 20,
    "jpeg_quality": 40,
    "client_cache_days": 3,
}

app = Flask(__name__)
STORAGE_ROOT = Path("dev_storage")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def configure_storage(storage_root: Path) -> None:
    global STORAGE_ROOT
    STORAGE_ROOT = storage_root
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)


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
    if not 1 <= int(day[4:6]) <= 12 or not 1 <= int(day[6:8]) <= 31:
        raise ValueError("invalid filename date")
    if int(clock[0:2]) > 23 or int(clock[2:4]) > 59 or int(clock[4:6]) > 59:
        raise ValueError("invalid filename time")
    if int(centisecond) > 99:
        raise ValueError("invalid filename centisecond")
    return filename, day


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
    return jsonify(status="ok", config=PHASE2_CONFIG), 200


def write_exclusive(destination: Path, payload: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(destination), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, payload)
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
    if len(payload) < 3 or payload[:2] != b"\xff\xd8":
        return jsonify(status="error", message="invalid jpeg"), 400

    try:
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
        default=Path("dev_storage"),
        help="Development storage root. Phase 5 replaces this with configured storage.",
    )
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def run_self_test(storage_root: Path) -> None:
    import io
    import time
    from datetime import datetime

    import requests
    from PIL import Image

    from app import make_filename, process_screenshot, upload_jpeg

    configure_storage(storage_root)
    server = create_server(app, host="127.0.0.1", port=PORT, threads=4)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(0.4)

    try:
        source = Image.new("RGB", (1920, 1080), (30, 90, 140))
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
        if response.json().get("config") != PHASE2_CONFIG:
            raise AssertionError(f"config shape mismatch: {response.json()}")

        stored = storage_root / "LIN-PC01_child" / "20261003" / filename
        if not stored.is_file() or stored.read_bytes() != jpeg:
            raise AssertionError(f"stored file mismatch: {stored}")
        first_stat = stored.stat()

        duplicate = requests.post(
            url,
            data={"hostname": "LIN-PC01", "username": "child"},
            files={"file": (filename, io.BytesIO(b"\xff\xd8\xffchanged"), "image/jpeg")},
            timeout=5,
        )
        if duplicate.status_code != 200:
            raise AssertionError("duplicate upload was not acknowledged")
        if stored.read_bytes() != jpeg or stored.stat().st_mtime_ns == 0:
            raise AssertionError("duplicate upload changed the original file")
        if stored.stat().st_size != first_stat.st_size:
            raise AssertionError("duplicate upload overwrote the original file")
        siblings = list(stored.parent.glob("*.jpg"))
        if siblings != [stored]:
            raise AssertionError(f"duplicate created extra files: {siblings}")

        rejected = requests.post(
            url,
            data={"hostname": "../evil", "username": "child"},
            files={"file": (filename, io.BytesIO(jpeg), "image/jpeg")},
            timeout=5,
        )
        if rejected.status_code == 200:
            raise AssertionError("path traversal was accepted")

        started = time.perf_counter()
        failed = upload_jpeg("127.0.0.1", "LIN-PC01", "child", filename, jpeg, port=55551)
        elapsed = time.perf_counter() - started
        if failed or elapsed > 6:
            raise AssertionError(f"unavailable server was not a fast failure: {failed} {elapsed:.2f}s")

        logging.info(
            "server self-test passed: %s bytes=%s duplicate=ok timeout=%.2fs",
            stored,
            stored.stat().st_size,
            elapsed,
        )
    finally:
        server.close()


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    args = parse_args(argv)
    configure_storage(args.storage_root)
    if args.self_test:
        run_self_test(args.storage_root)
        return 0

    logging.info("Listening on %s:%s storage=%s", args.host, args.port, STORAGE_ROOT)
    serve(app, host=args.host, port=args.port, threads=4)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
