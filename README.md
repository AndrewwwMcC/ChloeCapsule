# Kid Capsule

A private, password-protected photo and video album for one family.

- **Photos** are sorted by year and month using the date each one was *taken* (EXIF), not when it was uploaded. iPhone HEIC works.
- **Videos** live in their own section.
- **Two passwords:** the family password lets people view and download; the admin password (you and your wife) also lets you upload and delete.
- **Uploads** go up in 16 MB pieces, two files at a time, so long videos work from a phone. Duplicates are skipped automatically.
- Originals are kept untouched in a private Railway bucket; the site shows fast WebP copies. Every image link expires after 6 hours, so copied links stop working.
- Search engines are told to stay away (`noindex`, `robots.txt`).

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
Open the app service → **Variables** → *Raw Editor* and paste this, replacing the `<...>` parts. For the bucket lines, swap `Bucket` for your bucket service's name as shown in Railway (the editor autocompletes `${{`).

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

FAMILY_PASSWORD=<what you'll give family>
ADMIN_PASSWORD=<long, just for you two>
SESSION_SECRET=<random string, 40+ characters>
UPLOAD_TOKEN=<another random string, for the iPhone Shortcut>
```

- `BIRTH_DATE` turns on the age labels ("age 2", "1 yr 4 mo"). Leave it out if you'd rather not.
- Random strings: run `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` twice, or use a password manager.
- If the bucket's **Credentials** tab says it uses *path-style* URLs, also add `S3_ADDRESSING_STYLE=path`.
- Changing `SESSION_SECRET` logs everyone out — handy if a password leaks (change the password too).

### 5. Go live
App service → **Settings → Networking → Generate Domain**. Open it, log in with the admin password, and upload.

A custom domain can be added on the same screen later.

### On your phones
Open the site in Safari → Share → **Add to Home Screen**. It opens full-screen like an app. Tap **Upload**, choose photos, and keep the screen open until it says *all finished*.

For one-tap sharing from the Photos app, set up the Shortcut in `SHORTCUT.md`.

---

## Good to know

- **Keep one instance.** Uploads in progress are tracked in memory, so don't add replicas (`railway.json` already sets 1).
- **iPhone videos** are usually HEVC. They play on iPhone, iPad and Mac; some browsers on Windows/Android can't play HEVC, and the player then says so — downloading still works. Converting videos to a universal format can be added later.
- **Wrong date on a photo?** That means the file had no "date taken" (screenshots, some messaging-app saves). It falls back to the file's own date, then the upload date.
- **Backups:** keep iCloud/Google Photos running alongside this. Railway's bucket is durable, but this shouldn't be the only copy.
- **Costs:** storage is about $0.015 per GB a month; family viewing is free (bucket downloads aren't charged). Uploading counts as service traffic, a few cents per GB.

## Running locally

```
pip install -r requirements.txt   # plus ffmpeg on your system
export ...                        # the variables above, pointing at any Postgres + S3-compatible bucket
uvicorn app.main:app --reload
```
Add `SECURE_COOKIES=0` when testing over plain http.

## Roadmap
1. Timelapse builder (face-aligned, "6 months → 4 years")
2. Cover maker (editable masthead, layouts, export)
3. Automatic backup from your phones
