"""Settings, all read from environment variables (set them in Railway → Variables).

LOCAL_DEV=1 runs the site on your own computer with no database server or bucket:
everything is kept in the ./local-data folder. Never set it on Railway."""
import os
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo


def _env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


class Settings:
    def __init__(self) -> None:
        self.local_dev: bool = _env("LOCAL_DEV", "0") == "1"
        self.local_dir = Path(_env("LOCAL_DATA_DIR", "local-data")).resolve()
        prod = not self.local_dev

        # Site
        self.site_name: str = _env("SITE_NAME", "Chloé")
        birth = _env("BIRTH_DATE")  # YYYY-MM-DD, optional — enables "age 2" labels
        self.birth_date: date | None = date.fromisoformat(birth) if birth else None
        self.tz = ZoneInfo(_env("TIMEZONE", "Europe/Vienna"))

        # Access — one password, shared by the two of us, granting everything.
        self.site_password: str = _env("SITE_PASSWORD", None if prod else "admin", required=True)
        self.session_secret: str = _env("SESSION_SECRET", None if prod else "local-dev-secret", required=True)
        self.shortcut_token: str | None = _env("SHORTCUT_TOKEN")  # upload-only, for the iOS Shortcut
        self.secure_cookies: bool = _env("SECURE_COOKIES", "1" if prod else "0") == "1"

        # Database (Railway Postgres provides DATABASE_URL). Local: a SQLite file.
        self.database_url: str | None = _env("DATABASE_URL", required=prod)

        # Bucket (Railway Storage Bucket variable names). Local: a plain folder.
        self.bucket: str | None = _env("BUCKET", required=prod)
        self.s3_endpoint: str | None = _env("ENDPOINT", required=prod and bool(self.bucket))
        self.s3_key: str | None = _env("ACCESS_KEY_ID", required=prod and bool(self.bucket))
        self.s3_secret: str | None = _env("SECRET_ACCESS_KEY", required=prod and bool(self.bucket))
        self.s3_region: str = _env("REGION", "auto")
        self.s3_addressing: str = _env("S3_ADDRESSING_STYLE", "virtual")  # or "path" for older buckets

    @property
    def use_sqlite(self) -> bool:
        return not self.database_url

    @property
    def use_local_files(self) -> bool:
        return not self.bucket


settings = Settings()
