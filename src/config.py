"""Config + env loading. Foundational, so this one is real (not a stub)."""
from __future__ import annotations
import os
from pathlib import Path
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"


def _load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config() -> dict:
    """Load settings + personas + sources and the .env into one dict."""
    load_dotenv(ROOT / ".env")
    settings = _load_yaml("settings.yaml")
    personas = _load_yaml("personas.yaml").get("personas", [])
    handles = _load_handles()                       # overlay edited handles
    for p in personas:
        if p["id"] in handles:
            p["handle"] = handles[p["id"]]
    sources = [h for h in _load_yaml("sources.yaml").get("sources", []) if h]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "settings": settings,
        "personas": personas,
        "sources": sources,
        "secrets": {
            "anthropic": os.getenv("ANTHROPIC_API_KEY"),
            "openai": os.getenv("OPENAI_API_KEY"),
            "x_bearer": os.getenv("X_BEARER_TOKEN"),
            "ollama_host": os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            "twitterapi_io": os.getenv("TWITTERAPI_IO_KEY"),
        },
    }


HANDLES_FILE = CONFIG_DIR / "handles.yaml"          # overlay; keeps personas.yaml pristine


def _load_handles() -> dict:
    if HANDLES_FILE.exists():
        return yaml.safe_load(HANDLES_FILE.read_text(encoding="utf-8")) or {}
    return {}


def save_persona_handle(persona_id: str, handle: str) -> None:
    """Persist an edited handle to the overlay (personas.yaml is left untouched)."""
    handles = _load_handles()
    handles[persona_id] = handle
    HANDLES_FILE.write_text(
        yaml.safe_dump(handles, sort_keys=False, allow_unicode=True), encoding="utf-8")
