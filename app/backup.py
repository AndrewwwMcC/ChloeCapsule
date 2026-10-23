"""Download everything: one zip of the originals exactly as they were uploaded.

Nothing is built on disk or held in memory — zipstream-ng is handed a generator per
file and the bytes go straight out to the browser as they come off the bucket. STORE
only (media is already compressed), so the zip is the sum of its parts, and ZIP64
switches itself on, which it has to above 4 GB.

The whole album is one request, and Railway cuts any HTTP request at 15 minutes, so
the download page also offers a zip per year — same layout, same metadata.csv."""
import csv
import io
import logging
import re

from zipstream import ZIP_STORED, ZipStream

from . import db, storage

log = logging.getLogger("uvicorn.error")

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

CSV_HEADER = ["path", "original_filename", "capture_time", "upload_time", "place",
              "width", "height", "duration_seconds", "bytes"]

_BAD_CHARS = re.compile(r'[\x00-\x1f<>:"/\\|?*]')


def safe_name(name: str | None, fallback: str) -> str:
    """A filename that is safe to write on any machine, keeping the original as given."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    base = _BAD_CHARS.sub("_", base).strip(" .")
    return base or fallback


def _folder(kind: str, when) -> str:
    """Photos/2025/2025-08 August — one folder per month, inside its year."""
    top = "Photos" if kind == "photo" else "Videos"
    return f"{top}/{when.year}/{when.year}-{when.month:02d} {MONTHS[when.month - 1]}"


def _unique(path: str, used: set[str]) -> str:
    """Two files called IMG_0001.JPG both get in: the second becomes IMG_0001 (2).JPG."""
    if path.lower() not in used:
        used.add(path.lower())
        return path
    stem, dot, ext = path.rpartition(".")
    stem, ext = (stem, dot + ext) if dot else (path, "")
    n = 2
    while f"{stem} ({n}){ext}".lower() in used:
        n += 1
    path = f"{stem} ({n}){ext}"
    used.add(path.lower())
    return path


_cover_sizes: dict[tuple[str, str], int] = {}


def _cover_size(cover: dict) -> int:
    """Covers don't carry their byte count in the database, so ask the bucket — once.
    Keyed by updated_at as well, so re-saving a cover can't leave a stale number."""
    cid, stamp = str(cover["id"]), str(cover["updated_at"])
    if (cid, stamp) not in _cover_sizes:
        for stale in [k for k in _cover_sizes if k[0] == cid]:
            del _cover_sizes[stale]
        _cover_sizes[(cid, stamp)] = storage.size(cover["image_key"]) or 0
    return _cover_sizes[(cid, stamp)]


def entries(year: int | None = None) -> list[dict]:
    """Every original that belongs in the zip, in the order it will be written."""
    out: list[dict] = []
    used: set[str] = set()

    for kind in ("photo", "video"):
        for m in db.all_media(kind):
            when = m["taken_at"]
            if year and when.year != year:
                continue
            name = safe_name(m["original_name"], f"{m['id']}")
            out.append({
                "path": _unique(f"{_folder(kind, when)}/{name}", used),
                "name": m["original_name"] or name,
                "key": m["original_key"],
                "capture_time": when,
                "upload_time": m["created_at"],
                "place": m["place"] or "",
                "width": m["width"], "height": m["height"],
                "duration": m["duration"] if kind == "video" else None,
                "bytes": m["bytes"] or 0,
            })

    for c in db.all_covers():
        made = c["created_at"]
        if year and made.year != year:
            continue
        name = f"cover-{made:%Y-%m-%d}-{str(c['id'])[:8]}.jpg"
        out.append({
            "path": _unique(f"Covers/{name}", used),
            "name": name,
            "key": c["image_key"],
            "capture_time": None,
            "upload_time": made,
            "place": "",
            "width": c["width"], "height": c["height"],
            "duration": None,
            "bytes": _cover_size(c),
        })

    out.sort(key=lambda e: e["path"])
    return out


def _when(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value is not None else ""


def metadata_csv(rows: list[dict]) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.writer(buf)
    w.writerow(CSV_HEADER)
    for e in rows:
        w.writerow([e["path"], e["name"], _when(e["capture_time"]), _when(e["upload_time"]),
                    e["place"], e["width"] or "", e["height"] or "",
                    f"{e['duration']:.2f}" if e["duration"] else "", e["bytes"] or ""])
    return buf.getvalue().encode("utf-8-sig")  # BOM so Excel opens the accents correctly


def _bytes_of(key: str, path: str):
    """One file's bytes. A file missing from the bucket is logged and left empty rather
    than allowed to break the archive — a backup that opens beats one that doesn't."""
    try:
        yield from storage.stream(key)
    except Exception as exc:
        log.warning("Download: couldn't read %s (%s) — left empty in the zip", key, exc)


def zip_of(rows: list[dict]) -> ZipStream:
    zs = ZipStream(compress_type=ZIP_STORED)
    zs.add(metadata_csv(rows), "metadata.csv")
    for e in rows:
        zs.add(_bytes_of(e["key"], e["path"]), e["path"])
    return zs


def summary() -> dict:
    """What the download page shows before anyone clicks: totals, and the same per year."""
    rows = entries()
    years: dict[int, dict] = {}
    for e in rows:
        y = (e["capture_time"] or e["upload_time"]).year
        slot = years.setdefault(y, {"year": y, "files": 0, "bytes": 0})
        slot["files"] += 1
        slot["bytes"] += e["bytes"] or 0
    return {
        "files": len(rows),
        "bytes": sum(e["bytes"] or 0 for e in rows),
        "years": sorted(years.values(), key=lambda y: y["year"], reverse=True),
    }


def human(n: int) -> str:
    size = float(n)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:,.0f} {unit}" if unit in ("bytes", "KB") else f"{size:,.1f} {unit}"
        size /= 1024
    return f"{size:,.1f} TB"
