"""Module 2 — Polymarket ingestion.

Two hosts (both public, no auth):
  Gamma  https://gamma-api.polymarket.com   -> current market odds/metadata
  CLOB   https://clob.polymarket.com        -> historical prices (movement)

Gotcha handled below: Gamma returns `outcomes`, `outcomePrices`, and
`clobTokenIds` as JSON-ENCODED STRINGS, not arrays. We json.loads() them.

Movement is provided two ways:
  - clob price-history window (works on first run, no prior state needed)
  - run-over-run snapshot diff (delta vs the previous run, cached locally)

Endpoints/fields verified against docs.polymarket.com (the API reality-check item).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from src.config import CACHE_DIR

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
_UA = {"User-Agent": "tweet-engine/0.1"}          # docs recommend sending a UA
_SNAPSHOT = CACHE_DIR / "polymarket_snapshot.json"
_MARKETS_CACHE = CACHE_DIR / "polymarket_markets.json"


# -- normalized model -------------------------------------------------------
@dataclass
class Market:
    id: str
    question: str
    slug: str
    condition_id: str
    outcomes: list[str]                  # e.g. ["Yes", "No"]
    prices: list[float]                  # implied probabilities, maps 1:1 to outcomes
    clob_token_ids: list[str]            # asset ids used by the CLOB price endpoints
    volume_24h: float
    liquidity: float
    last_trade_price: float
    end_date: str | None
    enable_order_book: bool
    event_title: str | None = None
    movement: dict = field(default_factory=dict)   # filled by add_movement()

    def to_context(self) -> dict:
        """Compact dict handed to the generator as market context."""
        pairs = list(zip(self.outcomes, self.prices))
        return {
            "question": self.question,
            "outcomes": [{"name": o, "prob": round(p, 4)} for o, p in pairs],
            "volume_24h": round(self.volume_24h, 2),
            "movement": self.movement,
            "slug": self.slug,
        }


# -- parsing helpers --------------------------------------------------------
def _loads_list(value) -> list:
    """Gamma sends these as JSON strings; be defensive if already a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


def _f(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_market(raw: dict) -> Market:
    prices = [_f(p) for p in _loads_list(raw.get("outcomePrices"))]
    event_title = None
    events = raw.get("events") or []
    if events and isinstance(events, list):
        event_title = events[0].get("title")
    return Market(
        id=str(raw.get("id", "")),
        question=raw.get("question", ""),
        slug=raw.get("slug", ""),
        condition_id=raw.get("conditionId", ""),
        outcomes=_loads_list(raw.get("outcomes")),
        prices=prices,
        clob_token_ids=_loads_list(raw.get("clobTokenIds")),
        volume_24h=_f(raw.get("volume24hr")),
        liquidity=_f(raw.get("liquidity")),
        last_trade_price=_f(raw.get("lastTradePrice")),
        end_date=raw.get("endDate"),
        enable_order_book=bool(raw.get("enableOrderBook", False)),
        event_title=event_title,
    )


# -- Gamma: current markets -------------------------------------------------
def fetch_markets(cfg: dict, *, limit: int | None = None,
                  order: str = "volume24hr", active: bool = True,
                  closed: bool = False, use_cache: bool = True) -> list[Market]:
    """Fetch active markets from Gamma, sorted by 24h volume by default."""
    settings = cfg["settings"].get("polymarket", {})
    base = settings.get("base_url", GAMMA_BASE)
    limit = limit or settings.get("markets_limit", 50)
    ttl = cfg["settings"].get("tweet_source", {}).get("cache_ttl_hours", 24) * 3600

    if use_cache and _fresh(_MARKETS_CACHE, ttl):
        raw_list = json.loads(_MARKETS_CACHE.read_text())
    else:
        resp = requests.get(
            f"{base}/markets",
            params={"limit": limit, "order": order,
                    "active": str(active).lower(), "closed": str(closed).lower(),
                    "ascending": "false"},
            headers=_UA, timeout=30,
        )
        resp.raise_for_status()
        raw_list = resp.json()
        _MARKETS_CACHE.write_text(json.dumps(raw_list))

    markets = [_parse_market(m) for m in raw_list]
    # keep only tradable binary markets with real prices
    return [m for m in markets if m.enable_order_book and len(m.prices) >= 2]


# -- CLOB: price history -> movement over a window --------------------------
def fetch_price_history(token_id: str, *, interval: str = "1d",
                        fidelity: int = 60) -> list[tuple[int, float]]:
    """CLOB price history for one outcome token. Returns [(unix_ts, price), ...].

    interval: max | all | 1m | 1w | 1d | 6h | 1h ; fidelity = minutes per point.
    Note: very small fidelity on old/closed markets can return [].
    """
    resp = requests.get(
        f"{CLOB_BASE}/prices-history",
        params={"market": token_id, "interval": interval, "fidelity": fidelity},
        headers=_UA, timeout=30,
    )
    resp.raise_for_status()
    hist = resp.json().get("history", [])
    return [(int(pt["t"]), float(pt["p"])) for pt in hist if "t" in pt and "p" in pt]


def window_movement(token_id: str, *, interval: str = "1d",
                    fidelity: int = 60) -> dict:
    """Start/end/change over the window from CLOB history."""
    hist = fetch_price_history(token_id, interval=interval, fidelity=fidelity)
    if len(hist) < 2:
        return {"available": False}
    start, end = hist[0][1], hist[-1][1]
    return {
        "available": True,
        "interval": interval,
        "start": round(start, 4),
        "end": round(end, 4),
        "change": round(end - start, 4),                       # in probability points
        "pct_change": round((end - start) / start * 100, 2) if start else None,
        "n_points": len(hist),
    }


def add_movement(markets: list[Market], *, interval: str = "1d",
                 fidelity: int = 60, pause: float = 0.15) -> None:
    """Attach CLOB window movement to each market's first (index-0) outcome."""
    for m in markets:
        if not m.clob_token_ids:
            continue
        try:
            m.movement = window_movement(m.clob_token_ids[0],
                                         interval=interval, fidelity=fidelity)
        except requests.RequestException:
            m.movement = {"available": False}
        time.sleep(pause)        # be polite to the Cloudflare-throttled endpoint


# -- run-over-run snapshot diff (delta since last run) ----------------------
def snapshot_and_diff(markets: list[Market]) -> dict[str, float]:
    """Save this run's prices; return {market_id: index-0 price delta vs last run}."""
    current = {m.id: (m.prices[0] if m.prices else None) for m in markets}
    prev = json.loads(_SNAPSHOT.read_text()) if _SNAPSHOT.exists() else {}
    deltas = {
        mid: round(p - prev[mid], 4)
        for mid, p in current.items()
        if p is not None and prev.get(mid) is not None
    }
    _SNAPSHOT.write_text(json.dumps(current))
    return deltas


# -- util -------------------------------------------------------------------
def _fresh(path: Path, ttl_seconds: float) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) < ttl_seconds


if __name__ == "__main__":
    from src.config import load_config
    cfg = load_config()
    mkts = fetch_markets(cfg, limit=10, use_cache=False)
    print(f"{len(mkts)} markets")
    add_movement(mkts[:3], interval="1d", fidelity=60)
    for m in mkts[:3]:
        print(json.dumps(m.to_context(), indent=2))
