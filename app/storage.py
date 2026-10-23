"""S3-compatible object storage (MinIO locally)."""

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import boto3

from app.core.config import get_settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client  # dev-only stubs


@lru_cache
def _client() -> "S3Client":
    s = get_settings()
    client = boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        region_name=s.s3_region,
    )
    try:
        client.head_bucket(Bucket=s.s3_bucket)
    except client.exceptions.ClientError:
        client.create_bucket(Bucket=s.s3_bucket)
    return client


def put(key: str, data: bytes) -> None:
    _client().put_object(Bucket=get_settings().s3_bucket, Key=key, Body=data)


def get(key: str) -> bytes:
    return _client().get_object(Bucket=get_settings().s3_bucket, Key=key)["Body"].read()


def put_file(key: str, path: Path) -> None:
    """Streams from disk; use for large uploads (audio)."""
    _client().upload_file(str(path), get_settings().s3_bucket, key)


def download(key: str, path: Path) -> None:
    _client().download_file(get_settings().s3_bucket, key, str(path))


def delete(key: str) -> None:
    _client().delete_object(Bucket=get_settings().s3_bucket, Key=key)


def delete_prefix(prefix: str) -> int:
    """Delete every object under `prefix` (e.g. a whole project). Returns how many."""
    bucket, n = get_settings().s3_bucket, 0
    for page in _client().get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if keys:
            _client().delete_objects(Bucket=bucket, Delete={"Objects": keys})  # type: ignore[typeddict-item]
            n += len(keys)
    return n


def list_keys(prefix: str) -> list[str]:
    bucket = get_settings().s3_bucket
    pages = _client().get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
    return [o["Key"] for page in pages for o in page.get("Contents", [])]


def project_prefix(org_id: str, project_id: str) -> str:
    """All of a project's objects live under one prefix, so deleting a project is one sweep."""
    return f"orgs/{org_id}/projects/{project_id}/"
