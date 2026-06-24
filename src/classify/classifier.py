"""Module 4 — LLM source auto-classifier (cached).

For each handle: take its recent tweets (module 3), ask the LLM to assign
  tier  -> one of settings.classifier.tiers   (serious | middle | degen)
  tags  -> subset of settings.classifier.topic_tags (quant, macro, football, ...)

Results are persisted to data/cache/source_classifications.json and reused.
Re-classify only on demand (force=True) or for handles not yet in the cache.
"""
from __future__ import annotations

import datetime as dt

from src.config import CACHE_DIR
from src import cache
from src.ingestion import tweets as tw
from src.llm import provider as llm

CLASS_CACHE = CACHE_DIR / "source_classifications.json"

_SYSTEM = (
    "You classify a Twitter/X account from a sample of its recent posts. "
    "Judge the account's voice on a spectrum tier and its subject matter. "
    "Reply with STRICT JSON only — no prose, no code fences."
)


def _prompt(handle: str, texts: list[str], tiers: list[str], topics: list[str]) -> str:
    sample = "\n".join(f"- {t}" for t in texts)
    return (
        f"Account: @{handle}\n\nRecent posts:\n{sample}\n\n"
        f"Assign:\n"
        f"1. tier: exactly one of {tiers} "
        f"(serious = analytical/precise; middle = explanatory/mixed; "
        f"degen = meme/hype/banter).\n"
        f"2. tags: one or more of {topics} describing subject matter.\n\n"
        f'Return JSON: {{"tier": "...", "tags": ["...", "..."]}}'
    )


def classify_handle(handle: str, texts: list[str], provider, cfg: dict) -> dict:
    """Classify a single handle from its tweet texts. Returns {tier, tags}."""
    conf = cfg["settings"].get("classifier", {})
    tiers = conf.get("tiers", ["serious", "middle", "degen"])
    topics = conf.get("topic_tags", ["quant", "macro", "football", "news", "general"])

    if not texts:
        return {"tier": "middle", "tags": [], "note": "no_tweets"}

    raw = provider.complete(_SYSTEM, _prompt(handle, texts, tiers, topics),
                            max_tokens=200, temperature=0.0)
    try:
        parsed = llm.parse_json_object(raw)
    except Exception:
        return {"tier": "middle", "tags": [], "note": "parse_failed"}

    tier = parsed.get("tier")
    tier = tier if tier in tiers else "middle"                  # clamp to vocabulary
    tags = [t for t in (parsed.get("tags") or []) if t in topics]   # drop unknown tags
    return {"tier": tier, "tags": tags}


def get_classifications(cfg: dict, *, force: bool = False,
                        only: list[str] | None = None) -> dict[str, dict]:
    """Load cache; classify missing (or forced) handles; persist; return all.

    force -> re-classify everything.  only -> restrict to these handles.
    """
    existing: dict[str, dict] = cache.load_if_fresh(CLASS_CACHE, ttl_seconds=float("inf")) \
        if CLASS_CACHE.exists() else {}
    existing = existing or {}

    handles = [tw._norm(h) for h in (only if only is not None else cfg["sources"]) if h]
    todo = handles if force else [h for h in handles if h not in existing]

    if todo:
        provider = llm.get_provider(cfg)
        fetched = tw.fetch_for_handles(cfg, handles=todo)
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        for h in todo:
            texts = [t["text"] for t in fetched.get(h, [])]
            result = classify_handle(h, texts, provider, cfg)
            result["classified_at"] = now
            existing[h] = result
        cache.save(CLASS_CACHE, existing)

    return {h: existing[h] for h in handles if h in existing}


if __name__ == "__main__":
    from src.config import load_config
    cfg = load_config()
    for handle, c in get_classifications(cfg).items():
        print(f"{handle:20s} tier={c['tier']:8s} tags={c['tags']}")
