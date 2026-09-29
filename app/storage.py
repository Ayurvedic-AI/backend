import uuid
from pathlib import Path

from app.settings import settings


def save_audio(data: bytes, filename: str) -> str:
    """Persist raw upload, return its URL/path."""
    name = f"{uuid.uuid4().hex}{Path(filename).suffix.lower() or '.bin'}"
    if settings.storage == "s3":
        import boto3  # only needed when STORAGE=s3

        boto3.client("s3").put_object(Bucket=settings.s3_bucket, Key=name, Body=data)
        return f"s3://{settings.s3_bucket}/{name}"
    path = Path(settings.storage_dir) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)
