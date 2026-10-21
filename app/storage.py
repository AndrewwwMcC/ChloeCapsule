"""Railway Storage Bucket (S3-compatible). The bucket is private: every file is
served through a short-lived signed link, and uploads are chunked so large videos
never hit a single-request size limit."""
from datetime import datetime, timedelta, timezone

import boto3
from botocore.config import Config

from .config import settings

s3 = boto3.client(
    "s3",
    endpoint_url=settings.s3_endpoint,
    aws_access_key_id=settings.s3_key,
    aws_secret_access_key=settings.s3_secret,
    region_name=settings.s3_region,
    config=Config(s3={"addressing_style": settings.s3_addressing}, signature_version="s3v4",
                  retries={"max_attempts": 4, "mode": "standard"}),
)
BUCKET = settings.bucket
LINK_TTL = 6 * 3600  # signed links stay valid for 6 hours


def put(key: str, data: bytes, content_type: str) -> None:
    s3.put_object(Bucket=BUCKET, Key=key, Body=data, ContentType=content_type)


def get(key: str) -> bytes:
    return s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()


def delete(*keys: str | None) -> None:
    for key in keys:
        if key:
            try:
                s3.delete_object(Bucket=BUCKET, Key=key)
            except Exception:
                pass


def url(key: str | None, download_name: str | None = None) -> str | None:
    if not key:
        return None
    params = {"Bucket": BUCKET, "Key": key}
    if download_name:
        safe = download_name.replace('"', "")
        params["ResponseContentDisposition"] = f'attachment; filename="{safe}"'
    return s3.generate_presigned_url("get_object", Params=params, ExpiresIn=LINK_TTL)


# --- chunked (multipart) uploads -------------------------------------------------

def mp_start(key: str, content_type: str) -> str:
    return s3.create_multipart_upload(Bucket=BUCKET, Key=key, ContentType=content_type)["UploadId"]


def mp_part(key: str, upload_id: str, number: int, data: bytes) -> str:
    return s3.upload_part(Bucket=BUCKET, Key=key, UploadId=upload_id,
                          PartNumber=number, Body=data)["ETag"]


def mp_finish(key: str, upload_id: str, parts: list[dict]) -> None:
    s3.complete_multipart_upload(Bucket=BUCKET, Key=key, UploadId=upload_id,
                                 MultipartUpload={"Parts": parts})


def mp_abort(key: str, upload_id: str) -> None:
    try:
        s3.abort_multipart_upload(Bucket=BUCKET, Key=key, UploadId=upload_id)
    except Exception:
        pass


def abort_stale_uploads(older_than_hours: int = 24) -> None:
    """Clean up chunked uploads that were never finished (so they don't cost storage)."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
        for u in s3.list_multipart_uploads(Bucket=BUCKET).get("Uploads", []):
            if u["Initiated"] < cutoff:
                mp_abort(u["Key"], u["UploadId"])
    except Exception:
        pass
