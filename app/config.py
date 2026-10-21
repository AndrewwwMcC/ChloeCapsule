"""Settings, all read from environment variables (set them in Railway → Variables)."""
import os
from datetime import date
from zoneinfo import ZoneInfo


def _env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


class Settings:
    def __init__(self) -> None:
        # Site
        self.site_name: str = _env("SITE_NAME", "Chloé")
        birth = _env("BIRTH_DATE")  # YYYY-MM-DD, optional — enables "age 2" labels
        self.birth_date: date | None = date.fromisoformat(birth) if birth else None
        self.tz = ZoneInfo(_env("TIMEZONE", "Europe/Vienna"))

        # Access
        self.family_password: str = _env("FAMILY_PASSWORD", required=True)
        self.admin_password: str = _env("ADMIN_PASSWORD", required=True)
        self.session_secret: str = _env("SESSION_SECRET", required=True)
        self.upload_token: str | None = _env("UPLOAD_TOKEN")  # for the iOS Shortcut
        self.secure_cookies: bool = _env("SECURE_COOKIES", "1") == "1"

        # Database (Railway Postgres provides DATABASE_URL)
        self.database_url: str = _env("DATABASE_URL", required=True)

        # Bucket (Railway Storage Bucket variable names)
        self.bucket: str = _env("BUCKET", required=True)
        self.s3_endpoint: str = _env("ENDPOINT", required=True)
        self.s3_key: str = _env("ACCESS_KEY_ID", required=True)
        self.s3_secret: str = _env("SECRET_ACCESS_KEY", required=True)
        self.s3_region: str = _env("REGION", "auto")
        self.s3_addressing: str = _env("S3_ADDRESSING_STYLE", "virtual")  # or "path" for older buckets


settings = Settings()
