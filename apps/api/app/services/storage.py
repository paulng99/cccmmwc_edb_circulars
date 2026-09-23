from __future__ import annotations

import hashlib
import io
from pathlib import Path

from app.services.runtime_settings import resolved_settings


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _local_root() -> Path:
    rs = resolved_settings()
    root = Path(rs["local_storage_path"])
    root.mkdir(parents=True, exist_ok=True)
    return root


def _local_path(key: str) -> Path:
    path = _local_root() / key
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_minio_client():
    from minio import Minio

    rs = resolved_settings()
    return Minio(
        rs["minio_endpoint"],
        access_key=rs["minio_access_key"],
        secret_key=rs["minio_secret_key"],
        secure=bool(rs["minio_secure"]),
    )


def ensure_bucket() -> None:
    rs = resolved_settings()
    if rs.get("storage_backend") == "local":
        _local_root()
        return
    client = get_minio_client()
    if not client.bucket_exists(rs["minio_bucket"]):
        client.make_bucket(rs["minio_bucket"])


def put_object(key: str, data: bytes, content_type: str = "application/pdf") -> str:
    rs = resolved_settings()
    if rs.get("storage_backend") == "local":
        path = _local_path(key)
        path.write_bytes(data)
        return key
    ensure_bucket()
    client = get_minio_client()
    client.put_object(
        rs["minio_bucket"],
        key,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    return key


def get_object_bytes(key: str) -> bytes:
    rs = resolved_settings()
    if rs.get("storage_backend") == "local":
        return _local_path(key).read_bytes()
    client = get_minio_client()
    response = client.get_object(rs["minio_bucket"], key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def object_exists(key: str) -> bool:
    rs = resolved_settings()
    if rs.get("storage_backend") == "local":
        return _local_path(key).exists()
    from minio.error import S3Error

    client = get_minio_client()
    try:
        client.stat_object(rs["minio_bucket"], key)
        return True
    except S3Error:
        return False
