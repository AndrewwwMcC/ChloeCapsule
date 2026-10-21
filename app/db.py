"""Postgres access: one table of media items. Plain SQL, no ORM."""
from datetime import datetime

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import settings

pool = ConnectionPool(settings.database_url, min_size=1, max_size=5, open=False,
                      kwargs={"row_factory": dict_row})

SCHEMA = """
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


def init() -> None:
    pool.open(wait=True)
    with pool.connection() as conn:
        conn.execute(SCHEMA)


def insert_media(row: dict) -> None:
    cols = ", ".join(row.keys())
    vals = ", ".join(f"%({k})s" for k in row.keys())
    with pool.connection() as conn:
        conn.execute(f"INSERT INTO media ({cols}) VALUES ({vals})", row)


def find_by_sha(sha: str) -> dict | None:
    with pool.connection() as conn:
        return conn.execute("SELECT * FROM media WHERE sha256 = %s", (sha,)).fetchone()


def find_by_name_size(name: str, size: int) -> dict | None:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT id FROM media WHERE original_name = %s AND bytes = %s LIMIT 1", (name, size)
        ).fetchone()


def get_media(media_id: str) -> dict | None:
    with pool.connection() as conn:
        return conn.execute("SELECT * FROM media WHERE id = %s", (media_id,)).fetchone()


def delete_media(media_id: str) -> None:
    with pool.connection() as conn:
        conn.execute("DELETE FROM media WHERE id = %s", (media_id,))


def year_counts(kind: str) -> list[dict]:
    with pool.connection() as conn:
        return conn.execute(
            """SELECT EXTRACT(YEAR FROM taken_at)::int AS year, count(*) AS n
               FROM media WHERE kind = %s GROUP BY 1 ORDER BY 1 DESC""",
            (kind,),
        ).fetchall()


def media_in_year(kind: str, year: int) -> list[dict]:
    with pool.connection() as conn:
        return conn.execute(
            """SELECT * FROM media WHERE kind = %s
               AND taken_at >= %s AND taken_at < %s
               ORDER BY taken_at DESC""",
            (kind, datetime(year, 1, 1), datetime(year + 1, 1, 1)),
        ).fetchall()


def all_media(kind: str) -> list[dict]:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT * FROM media WHERE kind = %s ORDER BY taken_at DESC", (kind,)
        ).fetchall()
