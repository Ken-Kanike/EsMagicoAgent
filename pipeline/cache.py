"""Content-addressed result cache: sha256(file) + backend/model + prompt version -> result JSON."""
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from config.settings import settings


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _cache_dir(namespace: str) -> Path:
    d = settings.resolve_path(settings.cache_dir) / namespace
    d.mkdir(parents=True, exist_ok=True)
    return d


def make_key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:40]


def get(namespace: str, key: str) -> Optional[Dict[str, Any]]:
    p = _cache_dir(namespace) / f"{key}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def put(namespace: str, key: str, value: Dict[str, Any]) -> None:
    d = _cache_dir(namespace)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False)
    os.replace(tmp, d / f"{key}.json")
