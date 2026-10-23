# Kid Capsule

A private, password-protected photo and video album for one family — two people, one password.

- **Home** is an almanac: how many moments there are, this day in earlier years, a random photo on demand, the newest batch, a year of days as a heatmap, and where the photos were taken.
- **Photos** are sorted by year and month using the date each one was *taken* (EXIF), not when it was uploaded. iPhone HEIC works.
- **Videos** live in their own section.
- **One password** (`SITE_PASSWORD`) opens everything: viewing, uploading, deleting, covers and the full download. Sessions last 90 days, and changing the password logs every device out.
- **Uploads** go up in 16 MB pieces, two files at a time, so long videos work from a phone. Duplicates are skipped automatically.
- Originals are kept untouched in a private Railway bucket; the site shows fast WebP copies. Every bucket link is signed and expires after an hour, so a copied link stops working.
- **Download everything** streams the whole album back as one zip of the originals, with a `metadata.csv`, or a year at a time. It's in the footer.
- Nothing is reachable without a session: one gate checks every page, every API call and every file. Search engines are told to stay away (`noindex`, `X-Robots-Tag`, `robots.txt`), and every response carries HSTS, `nosniff`, `X-Frame-Options: DENY` and `Referrer-Policy: same-origin`.

---

## Setting it up on Railway (about 15 minutes)

### 1. Account
- Be on the **Hobby** plan or higher (storage buckets aren't on the trial).
- Settings → Usage → set a **hard limit** (e.g. $15–20) so nothing can surprise you.

### 2. Code
Put this folder in a **private** GitHub repo.

### 3. Project
In Railway: **New Project → Deploy from GitHub repo** → pick the repo. Then in the same project:
- **+ Create → Database → PostgreSQL**
- **+ Create → Bucket** (Storage Bucket)

### 4. Variables
Open the app service → **Variables** → *Raw Editor* and paste this, replacing the `<...>` parts (the same list is in `.env.example`). For the bucket lines, swap `Bucket` for your bucket service's name as shown in Railway (the editor autocompletes `${{`).

```
DATABASE_URL=${{Postgres.DATABASE_URL}}
BUCKET=${{Bucket.BUCKET}}
ENDPOINT=${{Bucket.ENDPOINT}}
ACCESS_KEY_ID=${{Bucket.ACCESS_KEY_ID}}
SECRET_ACCESS_KEY=${{Bucket.SECRET_ACCESS_KEY}}
REGION=${{Bucket.REGION}}

SITE_NAME=Chloé
BIRTH_DATE=<YYYY-MM-DD>
TIMEZONE=Europe/Vienna

SITE_PASSWORD=<long, just for you two>
SESSION_SECRET=<random string, 40+ characters>
SHORTCUT_TOKEN=<another random string, for the iPhone Shortcut>
```

- `BIRTH_DATE` turns on the age labels ("Age 2 years, 6 months" on Home, "age 2" on photos). Leave it out and the age text simply disappears.
- Random strings: run `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` for each, or use a password manager.
- If the bucket's **Credentials** tab says it uses *path-style* URLs, also add `S3_ADDRESSING_STYLE=path`.
- Changing `SITE_PASSWORD` logs every device out by itself — the session cookie is signed with the password as well as `SESSION_SECRET`.
- `SHORTCUT_TOKEN` is only good for uploading, and only on `/api/shortcut/upload`. Never use the site password there.
- The bucket must stay private. The app serves media either through itself behind the session, or as a signed link that expires within the hour.

### 5. Go live
App service → **Settings → Networking → Generate Domain**. Open it, log in, and upload.

A custom domain can be added on the same screen later.

### On your phones
Open the site in Safari → Share → **Add to Home Screen**. It opens full-screen like an app. Tap **Upload**, choose photos, and keep the screen open until it says *all finished*.

For one-tap sharing from the Photos app, set up the Shortcut in `SHORTCUT.md`.

---

## Good to know

- **Keep one instance.** Uploads in progress are tracked in memory, so don't add replicas (`railway.json` already sets 1).
- **iPhone videos** are usually HEVC. They play on iPhone, iPad and Mac; some browsers on Windows/Android can't play HEVC, and the player then says so — downloading still works. Converting videos to a universal format can be added later.
- **Wrong date on a photo?** That means the file had no "date taken" (screenshots, some messaging-app saves). It falls back to the file's own date, then the upload date.
- **Places** come from the GPS tags in the photos themselves, looked up offline — no mapping service ever sees them. Photos without GPS (screenshots, anything that came through WhatsApp) are left out of the Places list. Photos added before this existed get their place names from a one-off `python -m app.backfill_places`.
- **Backups:** the footer's *Download everything* gives you the whole album as a zip of the originals whenever you want it. Railway cuts any request off at 15 minutes, so once the album is big enough that the full zip can't finish on your connection, use the per-year zips on the same page. Keep iCloud/Google Photos running alongside this too.
- **Costs:** storage is about $0.015 per GB a month; family viewing is free (bucket downloads aren't charged). Uploading counts as service traffic, a few cents per GB.

## Running locally

```
pip install -r requirements.txt   # plus ffmpeg on your system
export ...                        # the variables above, pointing at any Postgres + S3-compatible bucket
uvicorn app.main:app --reload
```
Add `SECURE_COOKIES=0` when testing over plain http.

## Roadmap
1. Timelapse builder (face-aligned, "6 months → 4 years") — `/timelapse` is a placeholder for now
2. Automatic backup from your phones

Done: cover maker, and the Home almanac.
