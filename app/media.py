"""Turning an uploaded original into gallery-ready files and metadata.

Photos: read the date it was taken from EXIF, fix rotation, and make two WebP
copies (a small thumbnail for the grid, a large one for the full-screen view).
HEIC from iPhones is supported. Videos: read duration/size/date with ffprobe and
grab a poster frame with ffmpeg. The original file is always kept untouched."""
import io
import json
import shutil
import subprocess
from datetime import datetime, timezone

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

from .config import settings

register_heif_opener()
Image.MAX_IMAGE_PIXELS = 250_000_000

THUMB_EDGE = 720     # grid tiles (sharp on retina at ~300px)
DISPLAY_EDGE = 2400  # full-screen viewer

VIDEO_EXT = {".mov", ".mp4", ".m4v", ".3gp", ".avi", ".mkv", ".webm"}
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".tif", ".tiff", ".avif"}


def kind_for(filename: str, content_type: str | None) -> str | None:
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    ct = (content_type or "").lower()
    if ct.startswith("video/") or ext in VIDEO_EXT:
        return "video"
    if ct.startswith("image/") or ext in PHOTO_EXT:
        return "photo"
    return None


def have_ffmpeg() -> bool:
    """Posters and durations need both tools; without them videos are kept as-is."""
    return bool(shutil.which("ffprobe") and shutil.which("ffmpeg"))


def _webp(img: Image.Image, edge: int, quality: int) -> bytes:
    copy = img.copy()
    copy.thumbnail((edge, edge), Image.LANCZOS)
    buf = io.BytesIO()
    copy.save(buf, "WEBP", quality=quality, method=4)
    return buf.getvalue()


def _parse_exif_date(value: str | None, offset: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.strptime(value.strip()[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    if dt.year < 1990:  # cameras with an unset clock
        return None
    return dt  # EXIF is already local wall-clock time, which is what we group by


def _degrees(value, ref) -> float | None:
    """EXIF keeps GPS as degrees/minutes/seconds plus N/S/E/W."""
    try:
        d, m, s = (float(x) for x in value)
    except (TypeError, ValueError):
        return None
    deg = d + m / 60 + s / 3600
    return -deg if str(ref).strip().upper() in ("S", "W") else deg


def gps_of(exif) -> tuple[float | None, float | None]:
    gps = exif.get_ifd(0x8825) if exif else None
    if not gps:
        return None, None
    lat = _degrees(gps.get(2), gps.get(1))
    lon = _degrees(gps.get(4), gps.get(3))
    if lat is None or lon is None:
        return None, None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None, None
    if abs(lat) < 0.0001 and abs(lon) < 0.0001:
        return None, None  # 0,0 means the camera wrote an empty tag
    return round(lat, 6), round(lon, 6)


def from_epoch_ms(ms: int | float | None) -> datetime | None:
    if not ms:
        return None
    try:
        dt = datetime.fromtimestamp(float(ms) / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    if dt.year < 1990:
        return None
    return dt.astimezone(settings.tz).replace(tzinfo=None)


def process_photo(data: bytes) -> dict:
    img = Image.open(io.BytesIO(data))
    exif = img.getexif()
    sub = exif.get_ifd(0x8769) if exif else {}
    taken = _parse_exif_date(sub.get(36867) or sub.get(36868) or exif.get(306), sub.get(36881))
    lat, lon = gps_of(exif)

    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")

    return {
        "taken_at": taken,
        "lat": lat,
        "lon": lon,
        "width": img.width,
        "height": img.height,
        "display": _webp(img, DISPLAY_EDGE, 84),
        "thumb": _webp(img, THUMB_EDGE, 78),
    }


def process_cover(data: bytes) -> dict:
    """A saved cover: the JPEG the browser rendered is kept as sent; we only
    measure it and derive a thumbnail for the Covers grid."""
    img = Image.open(io.BytesIO(data))
    img.load()
    if img.mode != "RGB":
        img = img.convert("RGB")
    return {"width": img.width, "height": img.height, "thumb": _webp(img, THUMB_EDGE, 80)}


def _video_date(fmt_tags: dict) -> datetime | None:
    tags = {k.lower(): v for k, v in (fmt_tags or {}).items()}
    # iPhones store the local time with offset here — the best source
    apple = tags.get("com.apple.quicktime.creationdate")
    if apple:
        try:
            dt = datetime.strptime(apple[:24], "%Y-%m-%dT%H:%M:%S%z")
            return dt.replace(tzinfo=None)
        except ValueError:
            pass
    ct = tags.get("creation_time")
    if ct:
        try:
            dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt.year >= 1990:
                return dt.astimezone(settings.tz).replace(tzinfo=None)
        except ValueError:
            pass
    return None


def process_video(source: str) -> dict:
    """`source` is a local path or a signed URL — ffmpeg reads only what it needs.
    Without ffmpeg installed (e.g. a laptop), the video is kept but has no poster."""
    if not have_ffmpeg():
        return {"taken_at": None, "width": None, "height": None, "duration": None,
                "display": None, "thumb": None}
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", source],
        capture_output=True, timeout=120,
    )
    info = json.loads(probe.stdout or b"{}")
    fmt = info.get("format", {})
    stream = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    duration = float(fmt.get("duration") or stream.get("duration") or 0) or None

    width, height = stream.get("width"), stream.get("height")
    rotation = 0
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = abs(int(sd["rotation"]))
    if (stream.get("tags") or {}).get("rotate"):
        rotation = abs(int(stream["tags"]["rotate"]))
    if rotation in (90, 270) and width and height:
        width, height = height, width

    seek = "1" if (duration or 0) > 2 else "0"
    frame = subprocess.run(
        ["ffmpeg", "-v", "quiet", "-ss", seek, "-i", source, "-frames:v", "1",
         "-f", "image2", "-c:v", "mjpeg", "-q:v", "3", "pipe:1"],
        capture_output=True, timeout=180,
    ).stdout

    result = {"taken_at": _video_date(fmt.get("tags", {})), "width": width, "height": height,
              "duration": duration, "display": None, "thumb": None}
    if frame:
        poster = Image.open(io.BytesIO(frame)).convert("RGB")
        result["display"] = _webp(poster, 1600, 82)
        result["thumb"] = _webp(poster, THUMB_EDGE, 78)
    return result
