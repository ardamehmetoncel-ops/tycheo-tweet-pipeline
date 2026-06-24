"""Module 6 — local web UI (Flask).

Persona cards showing this run's candidates: read, copy, post manually elsewhere.
Each card has an editable @handle that persists to config/handles.yaml.
No auto-posting, no scheduling, no X write integration.

Run:  python -m src.web.app   ->  http://127.0.0.1:5000
"""
from __future__ import annotations

import datetime as dt
import json

from flask import Flask, jsonify, render_template, request

from src import cache
from src.config import load_config, save_persona_handle, CACHE_DIR
from src.generate import run_batch

app = Flask(__name__)
_LAST_BATCH = CACHE_DIR / "last_batch.json"
_TIER_ORDER = {"serious": 0, "middle": 1, "degen": 2}


def _tier(persona: dict) -> str:
    for t in ("serious", "middle", "degen"):
        if t in persona.get("tags", []):
            return t
    return "middle"


def _personas_view(cfg: dict) -> list[dict]:
    view = []
    for p in cfg["personas"]:
        view.append({
            "id": p["id"], "name": p["name"], "handle": p.get("handle", ""),
            "tags": p.get("tags", []), "tier": _tier(p),
            "reactive": bool(p.get("sentiment_reactive")),
        })
    view.sort(key=lambda p: (_TIER_ORDER.get(p["tier"], 1), p["name"]))
    return view


def _load_last() -> dict:
    if _LAST_BATCH.exists():
        try:
            return json.loads(_LAST_BATCH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


@app.route("/")
def index():
    cfg = load_config()
    last = _load_last()
    return render_template("index.html",
                           personas=_personas_view(cfg),
                           batch=last.get("batch", {}),
                           ran_at=last.get("ran_at"),
                           provider=cfg["settings"].get("llm", {}).get("provider"))


@app.route("/run", methods=["POST"])
def run():
    cfg = load_config()
    try:
        batch = run_batch(cfg)
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500
    ran_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    cache.save(_LAST_BATCH, {"ran_at": ran_at, "batch": batch})
    return jsonify({"ran_at": ran_at})


@app.route("/handle", methods=["POST"])
def handle():
    data = request.get_json(force=True)
    pid = data.get("persona_id")
    value = (data.get("handle") or "").strip().lstrip("@").strip()
    if not pid:
        return jsonify({"error": "missing persona_id"}), 400
    save_persona_handle(pid, value)
    return jsonify({"ok": True, "handle": value})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
