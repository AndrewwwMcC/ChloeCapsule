"""Database access: one table of media items. Plain SQL, no ORM.

Postgres on Railway; a SQLite file (local-data/capsule.db) when running locally."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from .config import settings

PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS media (
    id            uuid PRIMARY KEY,
    kind          text NOT NULL CHECK (kind IN ('photo', 'video')),
    taken_at      timestamp NOT NULL,          -- local wall-clock time the photo/video was taken
    date_source   text NOT NULL,               -- exif | video | file | upload | shortcut
    original_key  text NOT NULL,
    display_key   text,
    thumb_key     text,
    width         integer,
    height        integer,
    duration      real,
    bytes         bigint,
    mime          text,
    original_name text,
    sha256        text UNIQUE,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS media_kind_taken ON media (kind, taken_at DESC);
CREATE INDEX IF NOT EXISTS media_name_size ON media (original_name, bytes);
"""

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS media (
    id            text PRIMARY KEY,
    kind          text NOT NULL CHECK (kind IN ('photo', 'video')),
    taken_at      timestamp NOT NULL,
    date_source   text NOT NULL,
    original_key  text NOT NULL,
    display_key   text,
    thumb_key     text,
    width         integer,
    height        integer,
    duration      real,
    bytes         integer,
    mime          text,
    original_name text,
    sha256        text UNIQUE,
    created_at    timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS media_kind_taken ON media (kind, taken_at DESC);
CREATE INDEX IF NOT EXISTS media_name_size ON media (original_name, bytes);
"""

SQLITE = settings.use_sqlite
pool = None

if SQLITE:
    sqlite3.register_adapter(datetime, lambda d: d.isoformat(" "))
    sqlite3.register_converter("timestamp", lambda b: datetime.fromisoformat(b.decode()))
    DB_PATH = settings.local_dir / "capsule.db"
else:
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
    pool = ConnectionPool(settings.database_url, min_size=1, max_size=5, open=False,
                          kwargs={"row_factory": dict_row})


def _sql(query: str) -> str:
    """Write queries Postgres-style (%s, %(name)s); translate for SQLite."""
    if not SQLITE:
        return query
    import re
    query = re.sub(r"%\((\w+)\)s", r":\1", query)
    return query.replace("%s", "?")


@contextmanager
def _conn():
    if SQLITE:
        conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    else:
        with pool.connection() as conn:
            yield conn


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def _one(cur) -> dict | None:
    r = cur.fetchone()
    return dict(r) if r else None


def init() -> None:
    if SQLITE:
        settings.local_dir.mkdir(parents=True, exist_ok=True)
        with _conn() as conn:
            conn.executescript(SQLITE_SCHEMA)
    else:
        pool.open(wait=True)
        with _conn() as conn:
            conn.execute(PG_SCHEMA)


def close() -> None:
    if pool:
        pool.close()


def insert_media(row: dict) -> None:
    cols = ", ".join(row.keys())
    vals = ", ".join(f"%({k})s" for k in row.keys())
    with _conn() as conn:
        conn.execute(_sql(f"INSERT INTO media ({cols}) VALUES ({vals})"), row)


def find_by_sha(sha: str) -> dict | None:
    with _conn() as conn:
        return _one(conn.execute(_sql("SELECT * FROM media WHERE sha256 = %s"), (sha,)))


def find_by_name_size(name: str, size: int) -> dict | None:
    with _conn() as conn:
        return _one(conn.execute(
            _sql("SELECT id FROM media WHERE original_name = %s AND bytes = %s LIMIT 1"), (name, size)))


def get_media(media_id: str) -> dict | None:
    with _conn() as conn:
        return _one(conn.execute(_sql("SELECT * FROM media WHERE id = %s"), (media_id,)))


def delete_media(media_id: str) -> None:
    with _conn() as conn:
        conn.execute(_sql("DELETE FROM media WHERE id = %s"), (media_id,))


def year_counts(kind: str) -> list[dict]:
    year = ("CAST(strftime('%Y', taken_at) AS INTEGER)" if SQLITE
            else "EXTRACT(YEAR FROM taken_at)::int")
    with _conn() as conn:
        return _rows(conn.execute(
            _sql(f"SELECT {year} AS year, count(*) AS n FROM media WHERE kind = %s "
                 "GROUP BY 1 ORDER BY 1 DESC"), (kind,)))


def media_in_year(kind: str, year: int) -> list[dict]:
    with _conn() as conn:
        return _rows(conn.execute(
            _sql("SELECT * FROM media WHERE kind = %s AND taken_at >= %s AND taken_at < %s "
                 "ORDER BY taken_at DESC"),
            (kind, datetime(year, 1, 1), datetime(year + 1, 1, 1))))


def all_media(kind: str) -> list[dict]:
    with _conn() as conn:
        return _rows(conn.execute(
            _sql("SELECT * FROM media WHERE kind = %s ORDER BY taken_at DESC"), (kind,)))
