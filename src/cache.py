"""Tiny JSON file cache, shared by ingestion (module 3) and classification (module 4)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def load_if_fresh(path: Path, ttl_seconds: float) -> Any | None:
    """Return cached JSON if the file exists and is younger than ttl, else None."""
    if path.exists() and (time.time() - path.stat().st_mtime) < ttl_seconds:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
    return None


def save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
