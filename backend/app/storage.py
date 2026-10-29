"""Document storage. Local disk for development; the key layout maps 1:1 onto a private S3 bucket."""

import hashlib
import uuid
from pathlib import Path

from app.config import get_settings


def _root() -> Path:
    root = Path(get_settings().storage_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def save(case_id: uuid.UUID, data: bytes) -> tuple[str, str]:
    key = f"cases/{case_id}/{uuid.uuid4()}.pdf"
    path = _root() / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return key, hashlib.sha256(data).hexdigest()


def load(key: str) -> bytes:
    path = (_root() / key).resolve()
    if _root().resolve() not in path.parents:
        raise ValueError("Invalid storage key")
    return path.read_bytes()
