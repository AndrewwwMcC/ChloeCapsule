import hashlib
import json
import logging
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse, PlainTextResponse,
                               RedirectResponse, Response)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth, db, media, places, stats, storage
from .config import settings

log = logging.getLogger("uvicorn.error")  # the logger uvicorn already prints

HERE = Path(__file__).parent
CHUNK_SIZE = 16 * 1024 * 1024  # 16 MB per request keeps every upload well under proxy limits
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init()
    threading.Thread(target=storage.abort_stale_uploads, daemon=True).start()
    threading.Thread(target=backfill_posters, daemon=True).start()
    yield
    db.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


# --- helpers ---------------------------------------------------------------------

def age_label(d: date | datetime) -> str | None:
    """'born', '4 mo', '2 yrs 3 mo' — needs BIRTH_DATE."""
    b = settings.birth_date
    if not b:
        return None
    d = d.date() if isinstance(d, datetime) else d
    months = (d.year - b.year) * 12 + (d.month - b.month) - (1 if d.day < b.day else 0)
    if months < 0:
        return None
    if months == 0:
        return "newborn"
    if months < 12:
        return f"{months} mo"
    years, rest = divmod(months, 12)
    label = f"{years} yr" if years == 1 else f"{years} yrs"
    return f"{label} {rest} mo" if rest else label


def year_age_range(year: int) -> str | None:
    b = settings.birth_date
    if not b:
        return None
    start = max(date(year, 1, 1), b)
    end = min(date(year, 12, 31), date.today())
    if end < b:
        return None
    a, z = (start - b).days // 365, (end - b).days // 365
    if year == b.year:
        return "The year she arrived" if z == 0 else f"Born, to age {z}"
    return f"Age {a}" if a == z else f"Age {a} to {z}"


def rail_age(year: int) -> str | None:
    b = settings.birth_date
    if not b or year < b.year:
        return None
    return "born" if year == b.year else f"age {year - b.year}"


def ctx(request: Request, **extra) -> dict:
    return {"request": request, "site_name": settings.site_name,
            "role": auth.role_of(request), **extra}


def needs_login(request: Request) -> RedirectResponse | None:
    if not auth.role_of(request):
        return RedirectResponse(f"/login?next={request.url.path}", status_code=303)
    return None


def no_store(resp):
    resp.headers["Cache-Control"] = "no-store"
    return resp


def fmt_duration(sec: float | None) -> str:
    if not sec:
        return ""
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


# --- pages -----------------------------------------------------------------------

@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return "User-agent: *\nDisallow: /\n"


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    return no_store(templates.TemplateResponse(request, "login.html", ctx(request, next=next, error=None)))


@app.post("/login")
def login(request: Request, password: str = Form(...), remember: str | None = Form(None),
          next: str = Form("/")):
    ip = auth.client_ip(request)
    if auth.too_many_attempts(ip):
        return no_store(templates.TemplateResponse(
            request, "login.html", ctx(request, next=next, error="Too many tries. Wait 15 minutes."),
            status_code=429))
    role = auth.check_password(password)
    if not role:
        auth.record_failure(ip)
        time.sleep(0.6)
        return no_store(templates.TemplateResponse(
            request, "login.html", ctx(request, next=next, error="That password didn't work."),
            status_code=401))
    target = next if next.startswith("/") and not next.startswith("//") else "/"
    resp = RedirectResponse(target, status_code=303)
    resp.set_cookie(auth.COOKIE, auth.make_cookie(role), httponly=True, samesite="lax",
                    secure=settings.secure_cookies,
                    max_age=auth.REMEMBER_SECONDS if remember else None)
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(auth.COOKIE)
    return resp


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    """The almanac: where both admins and family land after logging in."""
    if (r := needs_login(request)):
        return r
    return no_store(templates.TemplateResponse(request, "home.html", ctx(
        request, nav="home", s=stats.with_urls(stats.payload()))))


@app.get("/timelapse", response_class=HTMLResponse)
def timelapse(request: Request):
    if (r := needs_login(request)):
        return r
    return no_store(templates.TemplateResponse(request, "timelapse.html", ctx(
        request, nav="timelapse")))


@app.get("/photos", response_class=HTMLResponse)
def photos_latest(request: Request):
    if (r := needs_login(request)):
        return r
    years = db.year_counts("photo")
    if years:
        return RedirectResponse(f"/photos/{years[0]['year']}", status_code=303)
    return no_store(templates.TemplateResponse(request, "photos.html", ctx(
        request, nav="photos", years=[], year=None, months=[], total=0, video_total=0, age_range=None)))


@app.get("/photos/{year}", response_class=HTMLResponse)
def photos_year(request: Request, year: int):
    if (r := needs_login(request)):
        return r
    years = [{"year": y["year"], "n": y["n"], "age": rail_age(y["year"])} for y in db.year_counts("photo")]
    items = db.media_in_year("photo", year)
    video_total = sum(y["n"] for y in db.year_counts("video") if y["year"] == year)

    months: dict[int, list] = {}
    for m in items:
        months.setdefault(m["taken_at"].month, []).append(m)

    month_blocks, index = [], 0
    for month_num in sorted(months, reverse=True):
        tiles = []
        for i, m in enumerate(months[month_num]):
            w, h = m["width"] or 1, m["height"] or 1
            ratio = w / h
            shape = "wide" if ratio >= 1.45 else "tall" if ratio <= 0.8 else ("big" if i % 9 == 0 else "")
            when = m["taken_at"]
            tiles.append({
                "id": str(m["id"]), "index": index, "shape": shape,
                "thumb": storage.url(m["thumb_key"]), "full": storage.url(m["display_key"]),
                "date": f"{when.strftime('%b')} {when.day}, {when.year}",
                "age": age_label(when) or "",
            })
            index += 1
        n = len(tiles)
        month_blocks.append({"name": MONTHS[month_num - 1], "anchor": MONTHS[month_num - 1].lower(),
                             "count": f"{n} photo" if n == 1 else f"{n} photos", "n": n, "tiles": tiles})

    return no_store(templates.TemplateResponse(request, "photos.html", ctx(
        request, nav="photos", years=years, year=year, months=month_blocks, total=len(items),
        video_total=video_total, age_range=year_age_range(year))))


@app.get("/videos", response_class=HTMLResponse)
def videos(request: Request, year: int | None = None):
    if (r := needs_login(request)):
        return r
    years = [y["year"] for y in db.year_counts("video")]
    items = db.media_in_year("video", year) if year else db.all_media("video")
    groups: list[dict] = []
    for m in items:
        when = m["taken_at"]
        label = f"{MONTHS[when.month - 1]} {when.year}"
        if not groups or groups[-1]["name"] != label:
            groups.append({"name": label, "clips": []})
        groups[-1]["clips"].append({
            "id": str(m["id"]), "poster": storage.url(m["thumb_key"]),
            "poster_large": storage.url(m["display_key"]), "src": storage.url(m["original_key"]),
            "mime": m["mime"] or "video/mp4", "len": fmt_duration(m["duration"]),
            "date": f"{when.strftime('%b')} {when.day}", "age": age_label(when) or "",
        })
    for g in groups:
        n = len(g["clips"])
        g["count"] = f"{n} clip" if n == 1 else f"{n} clips"
    return no_store(templates.TemplateResponse(request, "videos.html", ctx(
        request, nav="videos", years=years, year=year, groups=groups, total=len(items))))


# --- covers ----------------------------------------------------------------------

COVER_W, COVER_H = 1600, 2080  # 4:5.2, the shape of a newsstand cover


def _as_uuid(value: str | None) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None


def cover_card(c: dict) -> dict:
    try:
        saved = json.loads(c["settings"])
    except (TypeError, ValueError):
        saved = {}
    made = c["created_at"]
    return {
        "id": str(c["id"]),
        "thumb": storage.url(c["thumb_key"]) or storage.url(c["image_key"]),
        "full": storage.url(c["image_key"]),
        "masthead": saved.get("masthead") or settings.site_name,
        "issue": saved.get("issue") or "",
        "date": f"{made.strftime('%b')} {made.day}, {made.year}" if hasattr(made, "day") else "",
    }


@app.get("/covers", response_class=HTMLResponse)
def covers_page(request: Request):
    if (r := needs_login(request)):
        return r
    return no_store(templates.TemplateResponse(request, "covers.html", ctx(
        request, nav="covers", covers=[cover_card(c) for c in db.all_covers()])))


@app.get("/covers/new", response_class=HTMLResponse)
def cover_editor(request: Request, photo: str | None = None, cover: str | None = None):
    if (r := needs_login(request)):
        return r
    if auth.role_of(request) != "admin":
        return RedirectResponse("/covers", status_code=303)

    picker = [{
        "id": str(m["id"]), "thumb": storage.url(m["thumb_key"]), "year": m["taken_at"].year,
        "when": f"{MONTHS[m['taken_at'].month - 1]} {m['taken_at'].year}",
        "date": f"{m['taken_at'].strftime('%b')} {m['taken_at'].day}, {m['taken_at'].year}",
    } for m in db.all_media("photo") if m["thumb_key"]]
    years = sorted({p["year"] for p in picker}, reverse=True)

    saved, cover_id = None, None
    if cover:
        row = db.get_cover(_as_uuid(cover) or "") if _as_uuid(cover) else None
        if not row:
            raise HTTPException(404)
        cover_id = str(row["id"])
        saved = row["settings"]
        photo = str(row["media_id"]) if row["media_id"] else None

    start = _as_uuid(photo)
    if start and not db.get_media(start):
        start = None  # the source photo is gone; the editor asks for another

    return no_store(templates.TemplateResponse(request, "cover_new.html", ctx(
        request, nav="covers", picker=picker, years=years, start_photo=start,
        saved_settings=saved, cover_id=cover_id, next_no=db.cover_count() + 1,
        cover_w=COVER_W, cover_h=COVER_H)))


@app.get("/covers/{cover_id}/download")
def cover_download(request: Request, cover_id: uuid.UUID):
    if not auth.role_of(request):
        raise HTTPException(401)
    c = db.get_cover(str(cover_id))
    if not c:
        raise HTTPException(404)
    return RedirectResponse(storage.url(c["image_key"], download_name=f"cover-{str(cover_id)[:8]}.jpg"),
                            status_code=302)


@app.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request):
    if (r := needs_login(request)):
        return r
    if auth.role_of(request) != "admin":
        return RedirectResponse("/photos", status_code=303)
    return no_store(templates.TemplateResponse(request, "upload.html", ctx(
        request, nav="upload", chunk_size=CHUNK_SIZE)))


@app.get("/files/{key:path}")
def local_file(request: Request, key: str, download: str | None = None):
    """Local mode only: serves stored files to logged-in visitors."""
    if not storage.LOCAL:
        raise HTTPException(404)
    if not auth.role_of(request):
        raise HTTPException(401)
    try:
        path = storage.local_path(key)
    except ValueError:
        raise HTTPException(404)
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, filename=download) if download else FileResponse(path)


@app.get("/media/{media_id}/image")
def media_image(request: Request, media_id: uuid.UUID):
    """The photo's display copy served by the app itself. The cover editor draws it on a
    canvas, which it may only read back from if the bytes came from our own origin —
    a redirect to a signed bucket link would taint the canvas."""
    if not auth.role_of(request):
        raise HTTPException(401)
    m = db.get_media(str(media_id))
    if not m:
        raise HTTPException(404)
    key = m["display_key"] or m["original_key"]
    try:
        data = storage.get(key)
    except Exception:
        raise HTTPException(404)
    mime = "image/webp" if m["display_key"] else (m["mime"] or "application/octet-stream")
    return Response(data, media_type=mime, headers={"Cache-Control": "private, max-age=3600"})


@app.get("/media/{media_id}/download")
def download(request: Request, media_id: uuid.UUID):
    if not auth.role_of(request):
        raise HTTPException(401)
    m = db.get_media(str(media_id))
    if not m:
        raise HTTPException(404)
    name = m["original_name"] or f"{media_id}"
    return RedirectResponse(storage.url(m["original_key"], download_name=name), status_code=302)


# --- turning an original into a gallery item -------------------------------------

def ingest(*, media_id: str, key: str, kind: str, name: str, size: int, mime: str, sha: str,
           last_modified_ms: float | None = None, taken_override: datetime | None = None,
           local_path: str | None = None) -> dict:
    try:
        if kind == "photo":
            data = Path(local_path).read_bytes() if local_path else storage.get(key)
            result = media.process_photo(data)
        else:
            result = media.process_video(local_path or storage.ffmpeg_source(key))
    except Exception as exc:  # unreadable file: don't keep a broken item
        storage.delete(key)
        raise HTTPException(415, f"Couldn't read {name}: {type(exc).__name__}")

    if result["taken_at"]:
        taken, source = result["taken_at"], ("exif" if kind == "photo" else "video")
    elif taken_override:
        taken, source = taken_override, "shortcut"
    elif media.from_epoch_ms(last_modified_ms):
        taken, source = media.from_epoch_ms(last_modified_ms), "file"
    else:
        taken, source = datetime.now(settings.tz).replace(tzinfo=None), "upload"

    display_key = thumb_key = None
    if result["display"]:
        display_key = f"display/{media_id}.webp"
        storage.put(display_key, result["display"], "image/webp")
    if result["thumb"]:
        thumb_key = f"thumb/{media_id}.webp"
        storage.put(thumb_key, result["thumb"], "image/webp")

    lat, lon = result.get("lat"), result.get("lon")
    db.insert_media({
        "id": media_id, "kind": kind, "taken_at": taken, "date_source": source,
        "original_key": key, "display_key": display_key, "thumb_key": thumb_key,
        "width": result["width"], "height": result["height"], "duration": result.get("duration"),
        "bytes": size, "mime": mime, "original_name": name, "sha256": sha,
        "lat": lat, "lon": lon, "place": places.place_for(lat, lon),
    })
    stats.invalidate()  # the Home page counts this one now
    return {"id": media_id, "kind": kind, "taken_at": taken.isoformat(), "date_source": source}


def _ext(name: str) -> str:
    return ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""


def duplicate_of(m: dict) -> dict:
    """Answer for a file we already have — same fields as a fresh ingest, so the
    uploader can link a skipped file to where its twin already sits."""
    return {"duplicate": True, "id": str(m["id"]), "kind": m["kind"],
            "taken_at": m["taken_at"].isoformat()}


# --- video posters that were missed (no ffmpeg at upload time) -------------------

def make_poster(m: dict) -> bool:
    """Grab a poster frame for one video and fill in what ffprobe knows.
    Returns False when ffmpeg can't get a frame out of it. Never touches taken_at."""
    media_id = str(m["id"])
    result = media.process_video(storage.ffmpeg_source(m["original_key"]))
    if not result["thumb"]:
        return False

    fields = {"thumb_key": f"thumb/{media_id}.webp"}
    storage.put(fields["thumb_key"], result["thumb"], "image/webp")
    if result["display"]:
        fields["display_key"] = f"display/{media_id}.webp"
        storage.put(fields["display_key"], result["display"], "image/webp")
    for col in ("width", "height", "duration"):
        if result.get(col) and not m.get(col):
            fields[col] = result[col]

    db.update_media(media_id, fields)
    stats.invalidate()
    return True


def backfill_posters() -> None:
    """On startup: give a poster to any video that never got one."""
    try:
        rows = db.videos_without_poster()
        if not rows:
            return
        if not media.have_ffmpeg():
            log.warning("%d video(s) have no poster; install ffmpeg to make them.", len(rows))
            return
        fixed = 0
        for m in rows:
            try:
                if make_poster(m):
                    fixed += 1
                else:
                    log.warning("No frame came out of %s", m["original_name"] or m["id"])
            except Exception as exc:
                log.warning("Poster failed for %s: %s", m["original_name"] or m["id"], exc)
        log.info("Made posters for %d of %d video(s) that were missing one.", fixed, len(rows))
    except Exception as exc:  # never let startup housekeeping take the site down
        log.warning("Poster backfill stopped: %s", exc)


# --- chunked upload API (admin, from the browser) --------------------------------

UPLOADS: dict[str, dict] = {}


@app.post("/api/upload/init")
async def upload_init(request: Request):
    auth.require_admin(request)
    body = await request.json()
    name, size = str(body.get("name") or "file"), int(body.get("size") or 0)
    mime = str(body.get("type") or "application/octet-stream")
    kind = media.kind_for(name, mime)
    if not kind:
        return JSONResponse({"error": "Not a photo or video"}, status_code=415)
    if (twin := await run_in_threadpool(db.find_by_name_size, name, size)):
        return duplicate_of(twin)
    media_id = str(uuid.uuid4())
    key = f"originals/{media_id}{_ext(name)}"
    s3_id = await run_in_threadpool(storage.mp_start, key, mime)
    UPLOADS[media_id] = {"key": key, "s3_id": s3_id, "parts": [], "next": 1, "sha": hashlib.sha256(),
                         "name": name, "size": size, "mime": mime, "kind": kind,
                         "last_modified": body.get("lastModified"), "started": time.time()}
    return {"id": media_id, "chunk_size": CHUNK_SIZE}


@app.put("/api/upload/{media_id}/part/{number}")
async def upload_part(request: Request, media_id: str, number: int):
    auth.require_admin(request)
    up = UPLOADS.get(media_id)
    if not up:
        raise HTTPException(404, "Upload expired — try again")
    if number < up["next"]:
        return {"ok": True}  # retry of a part we already have
    if number != up["next"]:
        raise HTTPException(409, "Parts must arrive in order")
    data = await request.body()
    etag = await run_in_threadpool(storage.mp_part, up["key"], up["s3_id"], number, data)
    up["sha"].update(data)
    up["parts"].append({"PartNumber": number, "ETag": etag})
    up["next"] += 1
    return {"ok": True}


@app.post("/api/upload/{media_id}/complete")
def upload_complete(request: Request, media_id: str):
    auth.require_admin(request)
    up = UPLOADS.pop(media_id, None)
    if not up:
        raise HTTPException(404, "Upload expired — try again")
    storage.mp_finish(up["key"], up["s3_id"], up["parts"])
    sha = up["sha"].hexdigest()
    if (twin := db.find_by_sha(sha)):
        storage.delete(up["key"])
        return duplicate_of(twin)
    return ingest(media_id=media_id, key=up["key"], kind=up["kind"], name=up["name"],
                  size=up["size"], mime=up["mime"], sha=sha,
                  last_modified_ms=up["last_modified"])


@app.post("/api/upload/{media_id}/abort")
def upload_abort(request: Request, media_id: str):
    auth.require_admin(request)
    up = UPLOADS.pop(media_id, None)
    if up:
        storage.mp_abort(up["key"], up["s3_id"])
    return {"ok": True}


# --- single-request upload (iOS Shortcut) ----------------------------------------

@app.post("/api/shortcut/upload")
def shortcut_upload(request: Request, file: UploadFile = File(...), taken: str | None = Form(None)):
    if not (auth.token_ok(request) or auth.role_of(request) == "admin"):
        raise HTTPException(401, "Bad upload token")
    name = file.filename or "upload"
    mime = file.content_type or "application/octet-stream"
    kind = media.kind_for(name, mime)
    if not kind:
        raise HTTPException(415, "Not a photo or video")

    # delete=False and an explicit unlink: on Windows nothing else can open the file
    # while NamedTemporaryFile still holds it, and storage/ffmpeg both need to.
    tmp = tempfile.NamedTemporaryFile(suffix=_ext(name), delete=False)
    try:
        sha, size = hashlib.sha256(), 0
        while chunk := file.file.read(1024 * 1024):
            sha.update(chunk)
            size += len(chunk)
            tmp.write(chunk)
        tmp.close()
        digest = sha.hexdigest()
        if (twin := db.find_by_sha(digest)):
            return duplicate_of(twin)
        media_id = str(uuid.uuid4())
        key = f"originals/{media_id}{_ext(name)}"
        storage.put_file(key, tmp.name, mime)

        taken_dt = None
        if taken:
            try:
                taken_dt = datetime.fromisoformat(taken.strip().replace("Z", "+00:00"))
                if taken_dt.tzinfo:
                    taken_dt = taken_dt.astimezone(settings.tz).replace(tzinfo=None)
            except ValueError:
                taken_dt = None
        return ingest(media_id=media_id, key=key, kind=kind, name=name, size=size, mime=mime,
                      sha=digest, taken_override=taken_dt, local_path=tmp.name)
    finally:
        tmp.close()
        Path(tmp.name).unlink(missing_ok=True)


# --- the Home page's data (one call, served from memory) -------------------------

@app.get("/api/stats")
def api_stats(request: Request):
    if not auth.role_of(request):
        raise HTTPException(401)
    return no_store(JSONResponse(stats.with_urls(stats.payload())))


@app.get("/api/random")
def api_random(request: Request, scope: str = "any", value: str | None = None):
    """Surprise me: one photo out of the chosen slice of the album."""
    if not auth.role_of(request):
        raise HTTPException(401)
    if scope not in stats.SCOPES:
        raise HTTPException(400, "Unknown scope")
    pick = stats.random_photo(scope, value)
    if not pick:
        raise HTTPException(404, "No photos match that")
    return no_store(JSONResponse(pick))


# --- admin: delete, make a missing poster ----------------------------------------

@app.post("/api/media/{media_id}/poster")
def remake_poster(request: Request, media_id: uuid.UUID):
    auth.require_admin(request)
    m = db.get_media(str(media_id))
    if not m:
        raise HTTPException(404)
    if m["kind"] != "video":
        raise HTTPException(400, "Only videos have posters")
    if not media.have_ffmpeg():
        raise HTTPException(503, "ffmpeg isn't available here")
    try:
        made = make_poster(m)
    except Exception as exc:
        raise HTTPException(500, f"Couldn't read the video: {type(exc).__name__}")
    if not made:
        raise HTTPException(422, "ffmpeg couldn't get a frame out of this video")
    return {"ok": True}


MAX_COVER_BYTES = 12 * 1024 * 1024


@app.post("/api/covers")
async def save_cover(request: Request, image: UploadFile = File(...),
                     settings_json: str = Form(..., alias="settings"),
                     media_id: str | None = Form(None), cover_id: str | None = Form(None)):
    """Store the JPEG the editor rendered, plus the settings needed to edit it again."""
    auth.require_admin(request)
    data = await image.read()
    if not data:
        raise HTTPException(400, "The cover came through empty")
    if len(data) > MAX_COVER_BYTES:
        raise HTTPException(413, "That cover came out too large")
    try:
        saved = json.loads(settings_json)
        if not isinstance(saved, dict):
            raise ValueError("not an object")
    except ValueError:
        raise HTTPException(400, "Couldn't read the cover settings")
    try:
        info = await run_in_threadpool(media.process_cover, data)
    except Exception as exc:
        raise HTTPException(415, f"Couldn't read the cover image: {type(exc).__name__}")

    source = _as_uuid(media_id)
    if source and not await run_in_threadpool(db.get_media, source):
        source = None
    existing = db.get_cover(_as_uuid(cover_id)) if _as_uuid(cover_id) else None
    cid = str(existing["id"]) if existing else str(uuid.uuid4())

    image_key, thumb_key = f"covers/{cid}.jpg", f"covers/thumb/{cid}.webp"
    await run_in_threadpool(storage.put, image_key, data, "image/jpeg")
    if info["thumb"]:
        await run_in_threadpool(storage.put, thumb_key, info["thumb"], "image/webp")

    now = datetime.now(settings.tz).replace(tzinfo=None)
    row = {"media_id": source, "settings": json.dumps(saved, ensure_ascii=False),
           "image_key": image_key, "thumb_key": thumb_key if info["thumb"] else None,
           "width": info["width"], "height": info["height"], "updated_at": now}
    if existing:
        await run_in_threadpool(db.update_cover, cid, row)
    else:
        await run_in_threadpool(db.insert_cover, {"id": cid, "created_at": now, **row})
    stats.invalidate()
    return {"id": cid}


@app.delete("/api/covers/{cover_id}")
def delete_cover_item(request: Request, cover_id: uuid.UUID):
    auth.require_admin(request)
    c = db.get_cover(str(cover_id))
    if not c:
        raise HTTPException(404)
    storage.delete(c["image_key"], c["thumb_key"])
    db.delete_cover(str(cover_id))
    stats.invalidate()
    return {"ok": True}


@app.delete("/api/media/{media_id}")
def delete_item(request: Request, media_id: uuid.UUID):
    auth.require_admin(request)
    m = db.get_media(str(media_id))
    if not m:
        raise HTTPException(404)
    storage.delete(m["original_key"], m["display_key"], m["thumb_key"])
    db.clear_cover_source(str(media_id))  # covers made from it stay in /covers
    db.delete_media(str(media_id))
    stats.invalidate()
    return {"ok": True}
