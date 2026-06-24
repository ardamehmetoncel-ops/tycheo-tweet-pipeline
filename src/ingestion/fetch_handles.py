"""Fetch and cache tweets for all source handles.

Run this before src.classify.classifier. Safe to re-run — handles that already
have tweets in cache are skipped. If rate-limited mid-run, run again; the handles
that succeeded won't be re-fetched.
"""
from __future__ import annotations

from src import cache as cache_mod
from src.config import load_config, CACHE_DIR
from src.ingestion import tweets as tw

_TWEET_CACHE_DIR = CACHE_DIR / "tweets"


def _is_cached(handle: str, ttl: float) -> bool:
    path = _TWEET_CACHE_DIR / f"{handle}.json"
    data = cache_mod.load_if_fresh(path, ttl)
    return data is not None and len(data) > 0


def fetch_all(cfg: dict) -> dict[str, list[dict]]:
    ts = cfg["settings"].get("tweet_source", {})
    ttl = ts.get("cache_ttl_hours", 24) * 3600
    handles = [tw._norm(h) for h in cfg["sources"] if h]

    already = [h for h in handles if _is_cached(h, ttl)]
    todo = [h for h in handles if not _is_cached(h, ttl)]

    if already:
        print(f"[fetch] already cached ({len(already)}): {', '.join(already)}")

    if not todo:
        print("[fetch] all handles cached — run src.classify.classifier next")
        return {}

    print(f"[fetch] fetching {len(todo)} handle(s)...")
    results = tw.fetch_for_handles(cfg, handles=todo)

    ok = [h for h, t in results.items() if t]
    failed = [h for h, t in results.items() if not t]

    if ok:
        print(f"[fetch] fetched ({len(ok)}):  {', '.join(ok)}")
    if failed:
        print(f"[fetch] failed  ({len(failed)}): {', '.join(failed)}")
        print("[fetch] re-run to retry failed handles")
    if not failed:
        print("[fetch] all done — run src.classify.classifier next")

    return results


if __name__ == "__main__":
    cfg = load_config()
    fetch_all(cfg)
