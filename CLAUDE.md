# Chloé capsule — notes for Claude Code

A private, password-protected family photo and video album for one child (Chloé). Built for
Ando and his wife (admins) and their family (viewers). Deployed on Railway from `main`.

## Run it locally
- Windows: `run-local.cmd` (creates `.venv`, installs deps, starts http://localhost:8000 with auto-reload).
- Anywhere: `LOCAL_DEV=1 uvicorn app.main:app --reload --reload-dir app`.
- Local mode needs no Postgres or bucket: data goes to `local-data/` (SQLite + a files folder,
  served at `/files/...` to logged-in users). Passwords default to `admin` / `family`.
- Optional `local.env` (gitignored) for e.g. `BIRTH_DATE=2023-04-02` to see age labels.
- ffmpeg is optional locally; without it videos upload but have no poster or duration.
- After changing Python, the server reloads itself. Templates and CSS update on browser refresh.

## Stack
- FastAPI + Jinja templates + plain CSS/JS. No frontend framework or build step — keep it that way.
- `app/main.py` routes and upload pipeline · `app/db.py` SQL (Postgres or SQLite; write queries
  Postgres-style with `%s`, `_sql()` translates) · `app/storage.py` Railway bucket or local folder ·
  `app/media.py` EXIF/HEIC/thumbnails and ffprobe/ffmpeg posters · `app/auth.py` passwords and cookie ·
  `app/stats.py` everything the Home page counts · `app/places.py` offline reverse geocoding.
- Photos: original kept untouched; `thumb/<id>.webp` (720px) and `display/<id>.webp` (2400px) derived.
- Dates come from EXIF (photos) or QuickTime metadata (videos); `taken_at` is local wall-clock time.
- Uploads: browser sends 16 MB chunks in order (`/api/upload/init → part/N → complete`); the iOS
  Shortcut posts whole files to `/api/shortcut/upload` with `Authorization: Bearer <UPLOAD_TOKEN>`.
- Home (`/`, "the almanac") is where everyone lands: totals, on this day, surprise me, just added,
  one calendar year of days as a heatmap, photos per month, and small charts for hour/weekday/place.
  It is server-rendered from `stats.payload()`, which is computed once and kept in memory until an
  upload or delete calls `stats.invalidate()`. `GET /api/stats` returns the same thing as JSON;
  `GET /api/random` backs Surprise me; `GET /api/heatmap?year=` redraws the heatmap when the year
  picker changes (one cached grid per year). Signed links expire, so the cache holds storage keys only.
- Places come from EXIF GPS at upload time via the `reverse_geocode` package (offline, no API).
  Photos from before that: `python -m app.backfill_places` (add `--dry-run` to look first).
- Covers: `app/static/cover.js` draws a 1600×2080 cover on a canvas from one album photo and posts
  the JPEG to `/api/covers`; the `covers` table keeps the settings so a cover can be edited again.
  The photo is loaded through `/media/<id>/image` (same-origin, or the canvas can't be exported).

## Design
Quiet, photo-first, editorial. Tokens live at the top of `app/static/style.css`:
ground `#FAFAF8`, ink `#1A1A18`, muted `#5E5E58`, accent `#2E4A7A`; display type Instrument Serif,
body Geist. Big serif year and month headings, pill buttons, 44px minimum touch targets.
Must work well on a phone (most viewing and uploading happens there).

## Rules
- Privacy first: nothing public, no analytics or third-party scripts, keep `noindex` and robots.txt.
- Never commit `local-data/`, `.env` or `local.env`.
- Don't add replicas: in-progress uploads are tracked in memory (single instance).
- Pushing to `main` deploys to Railway. Run the site locally and check the page you changed first.

## Roadmap
1. Timelapse builder: pick a date range, face-aligned frames (MediaPipe landmarks → align eyes), ffmpeg render.
   `/timelapse` is a placeholder page until then — the nav links to it.
2. Automatic backup from phones via the Shortcut on a schedule.
3. Optional: transcode HEVC videos to H.264 for non-Apple browsers.

Done: cover maker (3 layouts, 6 mastheads — all original designs, never a real magazine's logo);
Home almanac with place names and charts.
