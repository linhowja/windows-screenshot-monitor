"""Phase 2 upload server.

Listens on TCP 55550 and accepts one endpoint: POST /api/upload.
A 200 is returned only after the JPEG is verified on disk, or when the
same final path already exists. There is no web UI.
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import re
import sys
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request
from PIL import Image
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
    return jsonify(status="ok", config=PHASE2_CONFIG), 200


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
        default=Path("dev_storage"),
        help="Development storage root. Phase 5 replaces this with configured storage.",
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


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    args = parse_args(argv)
    configure_storage(args.storage_root)
    if args.self_test:
        run_self_test(args.storage_root)
        return 0

    logging.info("Listening on %s:%s storage=%s", HOST, PORT, STORAGE_ROOT)
    serve(app, host=HOST, port=PORT, threads=4)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
