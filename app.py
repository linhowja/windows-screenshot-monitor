"""Phase 1 capture pipeline plus Phase 2 direct upload.

Formal runtime keeps each JPEG in memory. HTTP 200 discards it. Upload
failure also discards it until Phase 3 adds the cache queue.
"""

from __future__ import annotations

import argparse
import io
import logging
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from PIL import Image, ImageFile

DEFAULT_JPEG_QUALITY = 40
DEFAULT_INTERVAL_SECONDS = 20
UPLOAD_TIMEOUT_SECONDS = 5
SERVER_PORT = 55550
FILENAME_RE = r"^\d{8}_\d{6}_\d{2}\.jpg$"


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


def write_test_jpeg(output_dir: Path, quality: int) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename, jpeg, _captured_at = capture_jpeg(quality)
    destination = output_dir / filename
    destination.write_bytes(jpeg)
    return destination


def run_forever(server_ip: str, interval_seconds: int, quality: int) -> None:
    hostname, username = client_identity()
    logging.info(
        "Phase 2 client started. server=%s:%s identity=%s_%s interval=%ss",
        server_ip,
        SERVER_PORT,
        hostname,
        username,
        interval_seconds,
    )
    while True:
        started = time.monotonic()
        try:
            filename, jpeg, _captured_at = capture_jpeg(quality)
            if upload_jpeg(server_ip, hostname, username, filename, jpeg):
                logging.info("Uploaded %s (%d bytes); discarded", filename, len(jpeg))
            else:
                logging.error("Upload failed for %s; discarded until Phase 3 cache", filename)
            del jpeg
        except Exception as exc:
            logging.exception("Capture cycle failed and will continue: %s", exc)
        remaining = interval_seconds - (time.monotonic() - started)
        if remaining > 0:
            time.sleep(remaining)


def run_self_test() -> None:
    import re

    source = Image.new("RGB", (1920, 1080), (20, 140, 220))
    captured_at = datetime(2026, 10, 3, 16, 20, 0, 370000)
    filename = make_filename(captured_at)
    if filename != "20261003_162000_37.jpg":
        raise AssertionError(filename)
    if make_filename(datetime(2026, 10, 3, 16, 20, 0, 999999)) != "20261003_162000_99.jpg":
        raise AssertionError("centisecond upper bound is not 99")
    if not re.fullmatch(FILENAME_RE, filename):
        raise AssertionError(filename)
    if scaled_size(1920, 1080) != (480, 270):
        raise AssertionError(scaled_size(1920, 1080))

    jpeg = process_screenshot(source, DEFAULT_JPEG_QUALITY)
    parsed = Image.open(io.BytesIO(jpeg))
    parsed.load()
    if parsed.format != "JPEG" or parsed.mode != "L" or parsed.size != (480, 270):
        raise AssertionError(f"{parsed.format} {parsed.mode} {parsed.size}")
    logging.info("client self-test passed: %s 480x270 mode=L", filename)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 2 screenshot client")
    parser.add_argument("--server-ip", default="127.0.0.1")
    parser.add_argument("--test-output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--once", action="store_true", help="Capture and upload one JPEG, then exit.")
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
    if args.test_output is not None:
        logging.info("Test JPEG written: %s", write_test_jpeg(args.test_output, args.quality))
        return 0
    if args.once:
        hostname, username = client_identity()
        filename, jpeg, _captured_at = capture_jpeg(args.quality)
        ok = upload_jpeg(args.server_ip, hostname, username, filename, jpeg)
        del jpeg
        return 0 if ok else 1
    run_forever(args.server_ip, args.interval, args.quality)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        logging.info("Stopped by user.")
        raise SystemExit(0)
