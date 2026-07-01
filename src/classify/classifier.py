"""Module 4 — LLM source auto-classifier (cached).

For each handle: read its cached tweets (written by src.ingestion.fetch_handles),
ask the LLM to assign:
  tier  -> one of settings.classifier.tiers   (serious | middle | degen)
  tags  -> subset of settings.classifier.topic_tags (quant, macro, football, ...)

Results are persisted to data/cache/source_classifications.json and reused.
Re-classify only on demand (force=True) or for handles not yet in the cache.

Run order:
  1. python -m src.ingestion.fetch_handles   (fetch + cache tweets, no LLM)
  2. python -m src.classify.classifier       (classify from cache, LLM only)
"""
from __future__ import annotations

import datetime as dt

from src import cache
from src.config import CACHE_DIR
from src.ingestion import tweets as tw
from src.llm import provider as llm

CLASS_CACHE = CACHE_DIR / "source_classifications.json"
_TWEET_CACHE_DIR = CACHE_DIR / "tweets"

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


def _load_tweet_cache(handle: str, ttl: float) -> list[str]:
    """Read tweet texts for a handle from the tweet file cache."""
    path = _TWEET_CACHE_DIR / f"{handle}.json"
    data = cache.load_if_fresh(path, ttl)
    if not data:
        return []
    return [t["text"] for t in data if t.get("text")]


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
    tier = tier if tier in tiers else "middle"
    tags = [t for t in (parsed.get("tags") or []) if t in topics]
    return {"tier": tier, "tags": tags}


def get_classifications(cfg: dict, *, force: bool = False,
                        only: list[str] | None = None) -> dict[str, dict]:
    """Classify handles from tweet cache. Makes no tweet-fetch network calls.

    Handles with no tweet cache are skipped with a warning — run
    src.ingestion.fetch_handles first to populate the cache.
    """
    existing: dict[str, dict] = cache.load_if_fresh(CLASS_CACHE, ttl_seconds=float("inf")) \
        if CLASS_CACHE.exists() else {}
    existing = existing or {}

    handles = [tw._norm(h) for h in (only if only is not None else cfg["sources"]) if h]
    todo = handles if force else [h for h in handles if h not in existing]

    if todo:
        ts = cfg["settings"].get("tweet_source", {})
        ttl = ts.get("cache_ttl_hours", 24) * 3600

        tweet_cache = {h: _load_tweet_cache(h, ttl) for h in todo}
        ready = [h for h, texts in tweet_cache.items() if texts]
        missing = [h for h, texts in tweet_cache.items() if not texts]

        if missing:
            print(f"[classifier] no tweet cache for: {', '.join(missing)}")
            print("[classifier] run src.ingestion.fetch_handles to fetch them first")

        if ready:
            provider = llm.get_provider(cfg)
            now = dt.datetime.now(dt.timezone.utc).isoformat()
            for h in ready:
                texts = tweet_cache[h]
                result = classify_handle(h, texts, provider, cfg)
                result["classified_at"] = now
                existing[h] = result
                print(f"[classifier] {h:20s} tier={result['tier']:8s} tags={result['tags']}")
            cache.save(CLASS_CACHE, existing)

    return {h: existing[h] for h in handles if h in existing}


if __name__ == "__main__":
    from src.config import load_config
    cfg = load_config()
    results = get_classifications(cfg)
    if results:
        print(f"\n[classifier] {len(results)} handle(s) classified:")
        for handle, c in results.items():
            print(f"  {handle:20s} tier={c['tier']:8s} tags={c['tags']}")
