"""File storage.

On Railway: a private S3-compatible Storage Bucket. Every file is served through a
short-lived signed link, and uploads are chunked so large videos never hit a
single-request size limit.

Locally (no BUCKET set): a plain folder, local-data/files, served by the app
itself at /files/... to logged-in visitors only."""
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from .config import settings

LOCAL = settings.use_local_files
LINK_TTL = 3600  # signed links stay valid for one hour, no longer

if LOCAL:
    FILES = settings.local_dir / "files"
    PARTS = settings.local_dir / "uploads-in-progress"
    FILES.mkdir(parents=True, exist_ok=True)
    PARTS.mkdir(parents=True, exist_ok=True)
    s3 = None
    BUCKET = None
else:
    import boto3
    from botocore.config import Config
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


def local_path(key: str) -> Path:
    """Filesystem path for a key (local mode). Refuses anything outside the folder."""
    path = (FILES / key).resolve()
    if FILES not in path.parents:
        raise ValueError("bad key")
    return path


def put(key: str, data: bytes, content_type: str) -> None:
    if LOCAL:
        p = local_path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    else:
        s3.put_object(Bucket=BUCKET, Key=key, Body=data, ContentType=content_type)


def put_file(key: str, path: str, content_type: str) -> None:
    if LOCAL:
        p = local_path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, p)
    else:
        with open(path, "rb") as fh:
            s3.upload_fileobj(fh, BUCKET, key, ExtraArgs={"ContentType": content_type})


def get(key: str) -> bytes:
    if LOCAL:
        return local_path(key).read_bytes()
    return s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()


def stream(key: str, chunk: int = 1024 * 1024):
    """Yield one stored file in pieces, so a download never has to fit in memory."""
    if LOCAL:
        with open(local_path(key), "rb") as fh:
            while data := fh.read(chunk):
                yield data
        return
    body = s3.get_object(Bucket=BUCKET, Key=key)["Body"]
    try:
        yield from body.iter_chunks(chunk)
    finally:
        body.close()


def size(key: str) -> int | None:
    """Bytes of a stored file, or None if it has gone missing."""
    try:
        if LOCAL:
            return local_path(key).stat().st_size
        return s3.head_object(Bucket=BUCKET, Key=key)["ContentLength"]
    except Exception:
        return None


def delete(*keys: str | None) -> None:
    for key in keys:
        if not key:
            continue
        try:
            if LOCAL:
                local_path(key).unlink(missing_ok=True)
            else:
                s3.delete_object(Bucket=BUCKET, Key=key)
        except Exception:
            pass


def url(key: str | None, download_name: str | None = None) -> str | None:
    if not key:
        return None
    if LOCAL:
        link = "/files/" + quote(key)
        return link + ("?download=" + quote(download_name) if download_name else "")
    params = {"Bucket": BUCKET, "Key": key}
    if download_name:
        safe = download_name.replace('"', "")
        params["ResponseContentDisposition"] = f'attachment; filename="{safe}"'
    return s3.generate_presigned_url("get_object", Params=params, ExpiresIn=LINK_TTL)


def ffmpeg_source(key: str) -> str:
    """What to hand ffmpeg/ffprobe: a local path, or a signed link it can stream from."""
    return str(local_path(key)) if LOCAL else url(key)


# --- chunked (multipart) uploads -------------------------------------------------

def mp_start(key: str, content_type: str) -> str:
    if LOCAL:
        upload_id = uuid.uuid4().hex
        (PARTS / upload_id).write_bytes(b"")
        return upload_id
    return s3.create_multipart_upload(Bucket=BUCKET, Key=key, ContentType=content_type)["UploadId"]


def mp_part(key: str, upload_id: str, number: int, data: bytes) -> str:
    if LOCAL:
        with open(PARTS / upload_id, "ab") as fh:
            fh.write(data)
        return str(number)
    return s3.upload_part(Bucket=BUCKET, Key=key, UploadId=upload_id,
                          PartNumber=number, Body=data)["ETag"]


def mp_finish(key: str, upload_id: str, parts: list[dict]) -> None:
    if LOCAL:
        target = local_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(PARTS / upload_id), target)
        return
    s3.complete_multipart_upload(Bucket=BUCKET, Key=key, UploadId=upload_id,
                                 MultipartUpload={"Parts": parts})


def mp_abort(key: str, upload_id: str) -> None:
    try:
        if LOCAL:
            (PARTS / upload_id).unlink(missing_ok=True)
        else:
            s3.abort_multipart_upload(Bucket=BUCKET, Key=key, UploadId=upload_id)
    except Exception:
        pass


def abort_stale_uploads(older_than_hours: int = 24) -> None:
    """Clean up chunked uploads that were never finished (so they don't cost storage)."""
    try:
        if LOCAL:
            cutoff = datetime.now().timestamp() - older_than_hours * 3600
            for f in PARTS.iterdir():
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
            return
        cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
        for u in s3.list_multipart_uploads(Bucket=BUCKET).get("Uploads", []):
            if u["Initiated"] < cutoff:
                mp_abort(u["Key"], u["UploadId"])
    except Exception:
        pass
