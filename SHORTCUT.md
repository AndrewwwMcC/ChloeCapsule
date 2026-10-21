# "Send to Capsule" — iPhone Shortcut

Select photos in the Photos app → Share → **Send to Capsule**. The originals go straight up with their dates, and duplicates are skipped. Set it up once on each of your phones.

You need two things: your site address (e.g. `https://your-app.up.railway.app`) and the `UPLOAD_TOKEN` you set in Railway.

## Build it

1. Open **Shortcuts** → **+** → name it **Send to Capsule**.
2. Tap the **(i)** / settings icon → turn on **Show in Share Sheet**. Under *Share Sheet Types*, keep only **Images** and **Media**.
3. Add these actions in order:

   **Repeat with Each** — item in *Shortcut Input*

   Inside the repeat:

   **Get Contents of URL**
   - URL: `https://YOUR-SITE/api/shortcut/upload`
   - Method: **POST**
   - Headers: add `Authorization` = `Bearer YOUR_UPLOAD_TOKEN` (the word *Bearer*, a space, then the token)
   - Request Body: **Form**
     - add field → type **File**, key `file`, value **Repeat Item**

   **End Repeat**

   **Show Notification** — "Sent to Capsule"

4. Done. Try it with one photo first and check it appears on the site.

## Notes
- Each file must be under roughly 100 MB this way. For long videos, use the Upload page on the site instead (it sends big files in pieces).
- Keep the token private. If a phone is lost, change `UPLOAD_TOKEN` in Railway and update the Shortcut.
- Later this same Shortcut can run automatically each night to back up new photos.
