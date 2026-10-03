"""Phase 1 client capture pipeline.

Formal runtime keeps each encoded JPEG in memory and then discards it.
It does not upload, cache, or write a successful screenshot to disk.

Acceptance output is opt-in only:

    python app.py --test-output DIR
    python app.py --self-test
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageFile

# Phase 1 local defaults. Server-driven configuration is a later phase.
DEFAULT_JPEG_QUALITY = 40
DEFAULT_INTERVAL_SECONDS = 20
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

    with mss.mss() as sct:
        primary = getattr(sct, "primary_monitor", None)
        if not primary:
            if len(sct.monitors) < 2:
                raise RuntimeError("mss did not report a primary monitor")
            primary = sct.monitors[1]
        shot = sct.grab(primary)
        return Image.frombytes("RGB", shot.size, shot.rgb)


def capture_jpeg(quality: int = DEFAULT_JPEG_QUALITY) -> tuple[str, bytes, datetime]:
    captured_at = datetime.now()
    filename = make_filename(captured_at)
    jpeg = process_screenshot(capture_primary_monitor(), quality)
    return filename, jpeg, captured_at


def write_test_jpeg(output_dir: Path, quality: int) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename, jpeg, _captured_at = capture_jpeg(quality)
    destination = output_dir / filename
    destination.write_bytes(jpeg)
    return destination


def run_forever(interval_seconds: int, quality: int) -> None:
    logging.info(
        "Phase 1 capture started. JPEGs stay in memory only. "
        "interval=%ss quality=%s",
        interval_seconds,
        quality,
    )
    while True:
        filename, jpeg, _captured_at = capture_jpeg(quality)
        logging.info(
            "Captured %s in memory (%d bytes, quality %d); discarded without saving",
            filename,
            len(jpeg),
            quality,
        )
        del jpeg
        time.sleep(interval_seconds)


def _jpeg_sof(data: bytes) -> tuple[int, int, int, int]:
    """Return precision, height, width, component count from the first SOF marker."""
    index = 2
    while index + 8 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (0xD8, 0xD9):
            index += 2
            continue
        if index + 4 > len(data):
            break
        length = int.from_bytes(data[index + 2:index + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2):
            precision = data[index + 4]
            height = int.from_bytes(data[index + 5:index + 7], "big")
            width = int.from_bytes(data[index + 7:index + 9], "big")
            components = data[index + 9]
            return precision, height, width, components
        index += 2 + length
    raise AssertionError("JPEG SOF marker not found")


def _quantization_tables(data: bytes) -> bytes:
    tables = bytearray()
    index = 2
    while index + 4 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        length = int.from_bytes(data[index + 2:index + 4], "big")
        if marker == 0xDB:
            tables.extend(data[index + 2:index + 2 + length])
        if marker == 0xDA:
            break
        index += 2 + length
    return bytes(tables)


def run_self_test() -> None:
    import re

    source = Image.new("RGB", (1920, 1080), (20, 140, 220))
    for x in range(0, 1920, 40):
        for y in range(0, 1080, 40):
            source.putpixel((x, y), (x % 256, y % 256, 80))

    captured_at = datetime(2026, 10, 3, 16, 20, 0, 370000)
    filename = make_filename(captured_at)
    if filename != "20261003_162000_37.jpg":
        raise AssertionError(f"centisecond filename mismatch: {filename}")
    if make_filename(datetime(2026, 10, 3, 16, 20, 0, 999999)) != "20261003_162000_99.jpg":
        raise AssertionError("centisecond upper bound is not 99")
    if not re.fullmatch(FILENAME_RE, filename):
        raise AssertionError(f"filename does not match YYYYMMDD_HHMMSS_CC.jpg: {filename}")

    if scaled_size(1920, 1080) != (480, 270):
        raise AssertionError(f"unexpected scaled size: {scaled_size(1920, 1080)}")

    jpeg = process_screenshot(source, DEFAULT_JPEG_QUALITY)
    if jpeg[:2] != b"\xff\xd8":
        raise AssertionError("output is not a JPEG")

    parsed = Image.open(io.BytesIO(jpeg))
    parsed.load()
    if parsed.format != "JPEG":
        raise AssertionError(f"format is {parsed.format}, expected JPEG")
    if parsed.mode != "L":
        raise AssertionError(f"mode is {parsed.mode}, expected 8-bit grayscale L")
    if parsed.size != (480, 270):
        raise AssertionError(f"size is {parsed.size}, expected 480x270")

    precision, height, width, components = _jpeg_sof(jpeg)
    if (precision, height, width, components) != (8, 270, 480, 1):
        raise AssertionError(
            f"SOF mismatch: precision={precision} size={width}x{height} components={components}"
        )

    reference = io.BytesIO()
    Image.new("L", (8, 8), 128).save(reference, format="JPEG", quality=DEFAULT_JPEG_QUALITY)
    other = io.BytesIO()
    Image.new("L", (8, 8), 128).save(other, format="JPEG", quality=95)
    if _quantization_tables(jpeg) != _quantization_tables(reference.getvalue()):
        raise AssertionError("JPEG quantization tables do not match Pillow quality 40")
    if _quantization_tables(jpeg) == _quantization_tables(other.getvalue()):
        raise AssertionError("quality 40 tables unexpectedly match quality 95")

    logging.info(
        "self-test passed: %s %sx%s mode=%s quality=%s bytes=%s",
        filename,
        parsed.size[0],
        parsed.size[1],
        parsed.mode,
        DEFAULT_JPEG_QUALITY,
        len(jpeg),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 1 primary-monitor JPEG pipeline")
    parser.add_argument(
        "--test-output",
        type=Path,
        help="Write one encoded JPEG to this directory and exit. Not used in normal runtime.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run the synthetic 1920x1080 pipeline check without a display.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help="Seconds between captures in normal mode. Default 20. Not server-synced.",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=DEFAULT_JPEG_QUALITY,
        help="JPEG quality for this process. Default 40. Not server-synced.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    setup_logging()
    args = parse_args(argv)

    if args.self_test:
        run_self_test()
        return 0

    if args.test_output is not None:
        destination = write_test_jpeg(args.test_output, args.quality)
        logging.info("Test JPEG written: %s", destination)
        return 0

    run_forever(args.interval, args.quality)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        logging.info("Stopped by user.")
        raise SystemExit(0)
