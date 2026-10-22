"""Everything the Home page shows, worked out in one pass over the media table.

The album only changes when something is uploaded or deleted, so the answer is
kept in memory until then (invalidate()) and the page costs nothing to serve
after the first visit. Signed file links are left out of the cache on purpose —
they expire after a few hours, so only the storage keys are kept and the links
are made fresh for each request (with_urls)."""
import random
import threading
from collections import Counter
from datetime import date, datetime, timedelta

from . import db, storage
from .config import settings

HEAT_DAYS = 365
HEAT_THRESHOLDS = (1, 4, 10, 20)  # levels: 0 · 1-3 · 4-9 · 10-19 · 20+
ON_THIS_DAY_PICKS = 3
ON_THIS_DAY_SLACK = 3  # days either side, when that exact day is empty
BATCH_TILES = 8        # the 4x2 grid under "Just added"
TOP_PLACES = 5

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_lock = threading.RLock()
_cache: dict | None = None
_rows: list[dict] | None = None


def invalidate() -> None:
    """Called whenever something is uploaded, deleted or saved."""
    global _cache, _rows
    with _lock:
        _cache = None
        _rows = None


# --- small shared formatting -----------------------------------------------------

def _local(dt: datetime | None) -> datetime | None:
    """Postgres hands back an aware created_at; everything else is wall-clock already."""
    if dt is None:
        return None
    return dt.astimezone(settings.tz).replace(tzinfo=None) if dt.tzinfo else dt


def _day_label(d: date | datetime) -> str:
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}"  # Tue 20 Oct


def _photo_date(d: date | datetime) -> str:
    return f"{d.strftime('%b')} {d.day}, {d.year}"  # Aug 9, 2025 — as the viewer shows it


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}" if n == 1 else f"{n:,} {word}s"


def _months_old(d: date | datetime) -> int | None:
    b = settings.birth_date
    if isinstance(d, datetime):
        d = d.date()
    if not b or d < b:
        return None
    return max((d.year - b.year) * 12 + (d.month - b.month) - (1 if d.day < b.day else 0), 0)


def age_long(d: date | datetime) -> str | None:
    """'2 years, 6 months' — the masthead. None without BIRTH_DATE."""
    months = _months_old(d)
    if months is None:
        return None
    if months == 0:
        return "newborn"
    years, rest = divmod(months, 12)
    bits = []
    if years:
        bits.append(_plural(years, "year"))
    if rest or not years:
        bits.append(_plural(rest, "month"))
    return ", ".join(bits)


def age_caption(d: date | datetime) -> str | None:
    """'age 2', or 'newborn' / '7 months' in the first year."""
    months = _months_old(d)
    if months is None:
        return None
    if months == 0:
        return "newborn"
    if months < 12:
        return _plural(months, "month")
    return f"age {months // 12}"


def duration_label(seconds: float | None) -> str:
    total = int(round(seconds or 0))
    if not total:
        return "none yet"
    if total < 60:
        return f"{total} sec"
    if total < 3600:
        return f"{total // 60} min"
    hours, rest = divmod(total, 3600)
    return f"{hours} h {rest // 60} min" if rest // 60 else f"{hours} h"


def _pct(n: int, biggest: int) -> int:
    """A bar with anything in it still shows, even beside a far busier one."""
    if not n or not biggest:
        return 0
    return max(2, round(n / biggest * 100))


def month_anchor(d: date | datetime) -> str:
    """Photos groups a year by month, with the month name as the anchor."""
    return f"/photos/{d.year}#{d.strftime('%B').lower()}"


# --- the rows the Home page is built from ----------------------------------------

def rows() -> list[dict]:
    global _rows
    with _lock:
        if _rows is None:
            _rows = [{**r, "id": str(r["id"]), "taken_at": _local(r["taken_at"]),
                      "created_at": _local(r["created_at"])} for r in db.media_index()]
        return _rows


def payload() -> dict:
    global _cache
    with _lock:
        if _cache is None:
            _cache = _build(rows())
        return _cache


def _tile(r: dict) -> dict:
    taken = r["taken_at"]
    return {"id": r["id"], "kind": r["kind"],
            "thumb_key": r["thumb_key"], "full_key": r["display_key"] or r["thumb_key"],
            "date": _photo_date(taken), "age": age_caption(taken) or "",
            "href": month_anchor(taken) if r["kind"] == "photo" else f"/videos?year={taken.year}"}


# --- the panels ------------------------------------------------------------------

def _streak(days: list[date]) -> int:
    best = run = 0
    prev = None
    for d in days:
        run = run + 1 if prev and (d - prev).days == 1 else 1
        best = max(best, run)
        prev = d
    return best


def _year_caption(taken: datetime) -> str:
    age = age_caption(taken)
    return f"{taken.year} · {age}" if age else str(taken.year)


def _on_this_day(photos: list[dict], today: date) -> dict:
    picks = []
    years = sorted({p["taken_at"].year for p in photos if p["taken_at"].year < today.year},
                   reverse=True)
    for year in years:
        try:
            target = date(year, today.month, today.day)
        except ValueError:  # 29 February in a year that didn't have one
            target = date(year, today.month, today.day - 1)
        near = [(abs((p["taken_at"].date() - target).days), p) for p in photos
                if p["taken_at"].year == year
                and abs((p["taken_at"].date() - target).days) <= ON_THIS_DAY_SLACK]
        if not near:
            continue
        gap, pick = min(near, key=lambda item: (item[0], not item[1]["thumb_key"]))
        picks.append({**_tile(pick), "caption": _year_caption(pick["taken_at"]), "exact": gap == 0})
        if len(picks) == ON_THIS_DAY_PICKS:
            break

    if picks:
        return {"title": "On this day", "picks": picks,
                "note": f"{today.day} {today.strftime('%B')}, in the years before"}
    if photos:
        newest = photos[0]
        return {"title": "Latest", "picks": [{**_tile(newest), "exact": True,
                                              "caption": _year_caption(newest["taken_at"])}],
                "note": "Nothing from this day in an earlier year, so here's the newest photo"}
    return {"title": "On this day", "picks": [], "note": "Nothing in the album yet"}


def _latest_batch(rows_: list[dict]) -> dict:
    uploaded = [r for r in rows_ if r["created_at"]]
    if not uploaded:
        return {"caption": "", "tiles": [], "link": None, "more": 0}
    day = max(r["created_at"].date() for r in uploaded)
    batch = sorted([r for r in uploaded if r["created_at"].date() == day],
                   key=lambda r: r["taken_at"], reverse=True)
    photos = [r for r in batch if r["kind"] == "photo"]
    videos = [r for r in batch if r["kind"] == "video"]
    bits = []
    if photos:
        bits.append(_plural(len(photos), "photo"))
    if videos:
        bits.append(_plural(len(videos), "video"))
    bits.append(_day_label(day))
    first = photos[0] if photos else batch[0]
    return {"caption": " · ".join(bits), "tiles": [_tile(r) for r in batch[:BATCH_TILES]],
            "link": _tile(first)["href"], "more": max(len(batch) - BATCH_TILES, 0)}


def _heatmap(by_day: Counter, today: date) -> dict:
    start = today - timedelta(days=HEAT_DAYS - 1)
    monday = start - timedelta(days=start.weekday())
    weeks, labels, last_month = [], [], None
    day = monday
    while day <= today:
        column = []
        for i in range(7):
            d = day + timedelta(days=i)
            if d < start or d > today:
                column.append(None)
                continue
            n = by_day.get(d, 0)
            level = sum(1 for t in HEAT_THRESHOLDS if n >= t)
            column.append({"n": n, "level": level, "href": month_anchor(d) if n else None,
                           "title": f"{_plural(n, 'photo') if n else 'No photos'} · {_day_label(d)}"})
        first_real = next((d for d in (day + timedelta(days=i) for i in range(7))
                           if start <= d <= today), None)
        if first_real and first_real.month != last_month and \
                (not labels or len(weeks) - labels[-1]["col"] >= 3):
            labels.append({"col": len(weeks), "label": first_real.strftime("%b")})
            last_month = first_real.month
        weeks.append(column)
        day += timedelta(days=7)
    total = sum(n for d, n in by_day.items() if start <= d <= today)
    return {"weeks": weeks, "months": labels, "columns": len(weeks), "total": total}


def _monthly(photos: list[dict], today: date) -> dict:
    if not photos:
        return {"bars": [], "ticks": [], "busiest": None}
    counts = Counter((p["taken_at"].year, p["taken_at"].month) for p in photos)
    biggest = max(counts.values())
    bars, ticks = [], []
    year, month = min(counts)
    while (year, month) <= (today.year, today.month):
        n = counts.get((year, month), 0)
        when = date(year, month, 1)
        bars.append({"n": n, "pct": _pct(n, biggest), "href": month_anchor(when),
                     "label": f"{when.strftime('%B')} {year}",
                     "title": f"{_plural(n, 'photo') if n else 'No photos'} · "
                              f"{when.strftime('%B')} {year}"})
        if not ticks or ticks[-1]["label"] != str(year):
            ticks.append({"col": len(bars) - 1, "label": str(year)})
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    top = max(bars, key=lambda b: b["n"])
    for b in bars:
        b["highlight"] = b is top
    return {"bars": bars, "ticks": ticks, "busiest": f"Busiest: {top['label']}, {top['n']:,}"}


def _hours(photos: list[dict]) -> dict:
    counts = [0] * 24
    for p in photos:
        counts[p["taken_at"].hour] += 1
    biggest = max(counts)
    peak = counts.index(biggest) if biggest else None
    bars = [{"n": n, "pct": _pct(n, biggest), "highlight": h == peak,
             "title": f"{_plural(n, 'photo') if n else 'No photos'} · {h:02d}:00"}
            for h, n in enumerate(counts)]
    return {"bars": bars, "peak": peak,
            "headline": f"Most photos around {peak:02d}:00" if peak is not None else "No photos yet"}


def _weekdays(photos: list[dict]) -> dict:
    counts = [0] * 7
    for p in photos:
        counts[p["taken_at"].weekday()] += 1
    biggest = max(counts)
    order = sorted(range(7), key=lambda i: counts[i], reverse=True)
    top2 = {i for i in order[:2] if counts[i]}
    bars = [{"n": n, "pct": _pct(n, biggest), "highlight": i in top2,
             "label": WEEKDAYS[i][:3], "day": WEEKDAYS[i]} for i, n in enumerate(counts)]
    return {"bars": bars,
            "headline": f"{WEEKDAYS[order[0]]}s most of all" if biggest else "No photos yet"}


def _places(photos: list[dict]) -> dict:
    counts = Counter(p["place"] for p in photos if p["place"])
    top = [{"rank": i + 1, "name": name, "n": n}
           for i, (name, n) in enumerate(counts.most_common(TOP_PLACES))]
    missing = sum(1 for p in photos if not p["place"])
    notes = []
    if missing:
        notes.append(f"{_plural(missing, 'photo')} {'has' if missing == 1 else 'have'} no location")
    if len(counts) > len(top):
        extra = len(counts) - len(top)
        notes.append(f"{extra} more place{'' if extra == 1 else 's'}")
    return {"top": top, "note": " · ".join(notes),
            "headline": f"Mostly around {top[0]['name']}" if top else "No locations yet"}


def _scopes(photos: list[dict]) -> dict:
    years = Counter(p["taken_at"].year for p in photos)
    months = Counter((p["taken_at"].year, p["taken_at"].month) for p in photos)
    places = Counter(p["place"] for p in photos if p["place"])
    weekdays = Counter(p["taken_at"].weekday() for p in photos)
    return {
        "year": [{"value": str(y), "label": f"{y} · {n:,}"}
                 for y, n in sorted(years.items(), reverse=True)],
        "month": [{"value": f"{y:04d}-{m:02d}",
                   "label": f"{date(y, m, 1).strftime('%B')} {y} · {n:,}"}
                  for (y, m), n in sorted(months.items(), reverse=True)],
        "place": [{"value": name, "label": f"{name} · {n:,}"} for name, n in places.most_common()],
        "weekday": [{"value": str(i), "label": f"{WEEKDAYS[i]} · {weekdays.get(i, 0):,}"}
                    for i in range(7)],
    }


def _build(rows_: list[dict]) -> dict:
    today = datetime.now(settings.tz).date()
    photos = [r for r in rows_ if r["kind"] == "photo"]
    videos = [r for r in rows_ if r["kind"] == "video"]
    by_day = Counter(p["taken_at"].date() for p in photos)
    days = sorted(by_day)
    video_seconds = sum(v["duration"] or 0 for v in videos)

    return {
        "today": today.isoformat(),
        "today_label": f"{today.strftime('%A')} {today.day} {today.strftime('%B')} {today.year}",
        "age": age_long(today),
        "totals": {
            "photos": len(photos), "videos": len(videos), "covers": db.cover_count(),
            "days": len(days), "streak": _streak(days),
            "video_seconds": round(video_seconds), "video_duration": duration_label(video_seconds),
        },
        "on_this_day": _on_this_day(photos, today),
        "latest": _latest_batch(rows_),
        "heatmap": _heatmap(by_day, today),
        "monthly": _monthly(photos, today),
        "hours": _hours(photos),
        "weekdays": _weekdays(photos),
        "places": _places(photos),
        "scopes": _scopes(photos),
    }


# --- signed links, made fresh for each request -----------------------------------

def _linked(tile: dict) -> dict:
    return {**tile, "thumb": storage.url(tile["thumb_key"]), "full": storage.url(tile["full_key"])}


def with_urls(data: dict) -> dict:
    """The cached payload plus links of the moment for the thumbnails on it."""
    out = dict(data)
    out["on_this_day"] = {**data["on_this_day"],
                          "picks": [_linked(p) for p in data["on_this_day"]["picks"]]}
    out["latest"] = {**data["latest"], "tiles": [_linked(t) for t in data["latest"]["tiles"]]}
    return out


# --- Surprise me -----------------------------------------------------------------

SCOPES = ("any", "year", "month", "place", "weekday")


def random_photo(scope: str, value: str | None) -> dict | None:
    """One photo out of the chosen slice of the album, ready for the viewer."""
    photos = [r for r in rows() if r["kind"] == "photo" and (r["display_key"] or r["thumb_key"])]
    if scope == "year":
        photos = [p for p in photos if str(p["taken_at"].year) == value]
    elif scope == "month":
        photos = [p for p in photos
                  if f"{p['taken_at'].year:04d}-{p['taken_at'].month:02d}" == value]
    elif scope == "place":
        photos = [p for p in photos if p["place"] == value]
    elif scope == "weekday":
        photos = [p for p in photos if str(p["taken_at"].weekday()) == value]
    if not photos:
        return None
    pick = random.choice(photos)
    return {**_linked(_tile(pick)), "where": pick["place"] or "",
            "weekday": WEEKDAYS[pick["taken_at"].weekday()]}
