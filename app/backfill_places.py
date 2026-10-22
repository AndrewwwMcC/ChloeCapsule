"""One-off: give photos uploaded before place names existed a place name.

    python -m app.backfill_places            # do it
    python -m app.backfill_places --dry-run  # just say what it would do

Reads each original again (the only place the GPS tags live), works out the town
offline, and writes lat/lon/place onto the row. Photos with no GPS — screenshots,
anything shared through WhatsApp — are marked as looked at and skipped from then
on. Safe to stop and run again; it only ever looks at photos it hasn't done."""
import io
import sys

from PIL import Image
from pillow_heif import register_heif_opener

from . import db, media, places, storage

register_heif_opener()


def run(dry_run: bool = False) -> None:
    db.init()
    rows = db.photos_without_place()
    print(f"{len(rows)} photo(s) to look at.")
    located = missing = failed = 0

    for i, row in enumerate(rows, 1):
        name = row["original_name"] or row["id"]
        try:
            img = Image.open(io.BytesIO(storage.get(row["original_key"])))
            lat, lon = media.gps_of(img.getexif())
        except Exception as exc:
            failed += 1
            print(f"  [{i}/{len(rows)}] {name}: couldn't read it ({type(exc).__name__})")
            continue

        if lat is None:
            missing += 1
            fields = {"place": ""}  # looked at, nothing there
        else:
            place = places.place_for(lat, lon)
            located += 1
            fields = {"lat": lat, "lon": lon, "place": place or ""}
            print(f"  [{i}/{len(rows)}] {name}: {place or 'no town nearby'}")
        if not dry_run:
            db.update_media(str(row["id"]), fields)

    print(f"\nDone{' (dry run, nothing written)' if dry_run else ''}: "
          f"{located} located, {missing} without GPS, {failed} unreadable.")
    if located and not dry_run:
        print("Restart the site (or upload anything) for Home to pick up the new places.")


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
