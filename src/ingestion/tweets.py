"""Module 3 — tweet inspiration source (flat handle list, cached).

Adapters:
  CuratedSource     -> example tweets you provide in data/curated_tweets.yaml (no network)
  OfficialXSource   -> X API v2 (needs X_BEARER_TOKEN); network calls are cached
  UnofficialXSource -> twitterapi.io proxy (needs TWITTERAPI_IO_KEY; violates X ToS)

The TweetSource Protocol stays open if you add your own adapter.

Tweet dict shape: {"id", "text", "created_at", "handle", "source"}
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Protocol

import requests
import yaml

from src import cache
from src.config import CACHE_DIR, DATA_DIR

CURATED_FILE = DATA_DIR / "curated_tweets.yaml"
_TWEET_CACHE_DIR = CACHE_DIR / "tweets"


class TweetSource(Protocol):
    name: str
    def fetch(self, handle: str, limit: int) -> list[dict]: ...


def _norm(handle: str) -> str:
    return handle.lstrip("@").strip().lower()


def _synth_id(handle: str, text: str) -> str:
    return hashlib.sha1(f"{handle}:{text}".encode("utf-8")).hexdigest()[:16]


# -- curated: local example tweets, no network ------------------------------
class CuratedSource:
    name = "curated"

    def __init__(self, path: Path = CURATED_FILE):
        self.path = path
        self._data: dict | None = None

    def _load(self) -> dict:
        if self._data is None:
            if not self.path.exists():
                self._data = {}
            else:
                raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
                self._data = {_norm(k): (v or [])
                              for k, v in (raw.get("handles") or {}).items()}
        return self._data

    def fetch(self, handle: str, limit: int) -> list[dict]:
        texts = self._load().get(_norm(handle), [])[:limit]
        return [{"id": _synth_id(handle, t), "text": t, "created_at": None,
                 "handle": _norm(handle), "source": self.name} for t in texts]


# -- official X API v2 (compliant; needs a bearer token) --------------------
class OfficialXSource:
    name = "official_x"
    BASE = "https://api.twitter.com/2"

    def __init__(self, bearer_token: str | None):
        self.bearer = bearer_token

    def _headers(self) -> dict:
        if not self.bearer:
            raise RuntimeError(
                "X_BEARER_TOKEN not set; required for tweet_source.adapter=official_x")
        return {"Authorization": f"Bearer {self.bearer}"}

    def _user_id(self, handle: str) -> str:
        r = requests.get(f"{self.BASE}/users/by/username/{_norm(handle)}",
                         headers=self._headers(), timeout=30)
        r.raise_for_status()
        return r.json()["data"]["id"]

    def fetch(self, handle: str, limit: int) -> list[dict]:
        uid = self._user_id(handle)
        max_results = max(5, min(limit, 100))          # v2 floors at 5, caps at 100
        r = requests.get(f"{self.BASE}/users/{uid}/tweets",
                         params={"max_results": max_results,
                                 "tweet.fields": "created_at",
                                 "exclude": "retweets,replies"},
                         headers=self._headers(), timeout=30)
        r.raise_for_status()
        data = r.json().get("data", [])[:limit]
        return [{"id": t["id"], "text": t["text"], "created_at": t.get("created_at"),
                 "handle": _norm(handle), "source": self.name} for t in data]


# -- unofficial X source via twitterapi.io ----------------------------------
class UnofficialXSource:
    name = "unofficial_x"
    BASE = "https://api.twitterapi.io"

    def __init__(self, api_key: str | None):
        if not api_key:
            raise RuntimeError(
                "TWITTERAPI_IO_KEY not set (tweet_source.adapter=unofficial_x)")
        self.headers = {"X-API-Key": api_key}

    def fetch(self, handle: str, limit: int) -> list[dict]:
        r = requests.get(
            f"{self.BASE}/twitter/user/last_tweets",
            headers=self.headers,
            params={"userName": _norm(handle), "count": min(limit, 100)},
            timeout=30,
        )
        r.raise_for_status()
        tweets = r.json().get("data", {}).get("tweets", [])[:limit]
        out = []
        for t in tweets:
            text = t.get("text") or t.get("full_text", "")
            if not text:
                continue
            out.append({
                "id": str(t.get("id", _synth_id(handle, text))),
                "text": text,
                "created_at": t.get("createdAt") or t.get("created_at"),
                "handle": _norm(handle),
                "source": self.name,
            })
        return out


# -- cache wrapper for network sources --------------------------------------
class CachedSource:
    """Wraps a network source with a per-handle TTL JSON cache (cost control)."""

    def __init__(self, inner: TweetSource, ttl_seconds: float):
        self.inner = inner
        self.ttl = ttl_seconds
        self.name = inner.name

    def fetch(self, handle: str, limit: int) -> list[dict]:
        path = _TWEET_CACHE_DIR / f"{_norm(handle)}.json"
        cached = cache.load_if_fresh(path, self.ttl)
        if cached is not None:
            return cached[:limit]
        fresh = self.inner.fetch(handle, limit)
        cache.save(path, fresh)
        return fresh


# -- factory + batch helper -------------------------------------------------
def get_source(cfg: dict) -> TweetSource:
    ts = cfg["settings"].get("tweet_source", {})
    adapter = ts.get("adapter", "curated")
    if adapter == "curated":
        return CuratedSource()                          # local file; no caching
    if adapter == "official_x":
        ttl = ts.get("cache_ttl_hours", 24) * 3600
        return CachedSource(OfficialXSource(cfg["secrets"].get("x_bearer")), ttl)
    if adapter == "unofficial_x":
        ttl = ts.get("cache_ttl_hours", 24) * 3600
        return CachedSource(
            UnofficialXSource(cfg["secrets"].get("twitterapi_io")), ttl)
    raise ValueError(
        f"unknown tweet_source.adapter: {adapter!r} (curated | official_x | unofficial_x)")


def fetch_for_handles(cfg: dict,
                      handles: list[str] | None = None) -> dict[str, list[dict]]:
    """Fetch up to per_account_limit tweets for each handle. Used by the classifier."""
    ts = cfg["settings"].get("tweet_source", {})
    limit = ts.get("per_account_limit", 15)
    delay = ts.get("request_delay_seconds", 0)
    src = get_source(cfg)
    handles = handles if handles is not None else cfg["sources"]
    out: dict[str, list[dict]] = {}
    for i, h in enumerate(handles):
        if not h:
            continue
        if delay and i > 0:
            time.sleep(delay)
        try:
            tweets = src.fetch(h, limit)
            out[_norm(h)] = tweets
            if tweets:
                print(f"[fetch] {h}: fetched {len(tweets)} tweets")
            else:
                print(f"[fetch] {h}: no tweets returned")
        except Exception as e:        # one bad handle shouldn't kill the whole batch
            out[_norm(h)] = []
            print(f"[fetch] {h}: failed — {e}")
    return out


if __name__ == "__main__":
    from src.config import load_config
    cfg = load_config()
    result = fetch_for_handles(cfg)
    for handle, tweets in result.items():
        print(f"{handle}: {len(tweets)} tweets")
