"""Module 5 — generation orchestration.

Prompt structure:
  SYSTEM = GLOBAL_BLOCK + persona.system_prompt
  USER   = sorted/filtered market data + VOICE REFERENCE tweets (tone/style stealing)
"""
from __future__ import annotations

import re
import random
import time

from src import routing
from src.classify.classifier import get_classifications
from src.ingestion import tweets as tw
from src.ingestion.polymarket import (Market, fetch_markets, add_movement,
                                      snapshot_and_diff)
from src.llm import provider as llm

_CONTEXT_PER_SOURCE = 5
_MAX_CONTEXT = 20
_MAX_CONTEXT_VOICE_ONLY = 40  # no market data competing for tokens
_MARKETS_PER_PERSONA = 5

# Personas that get 0% (or 100%) markets filtered out — these prices create absurd calls
_FILTER_ZERO_MARKETS = {"edge_printr"}

# Tweets containing these terms are stripped from voice-only persona context
_MARKET_KEYWORDS = {
    "polymarket", "kalshi", "manifold", "prediction market",
    "$poly", "poly odds", "metaculus", "augur", "limitless",
}

# Matches any percentage figure — catches implicit market language ("at 34%", "odds cratering to 12%")
_PERCENT_RE = re.compile(r'\b\d{1,3}%')

# ---------------------------------------------------------------------------
# GLOBAL BLOCK — Grok-optimised: tight and direct
# ---------------------------------------------------------------------------
GLOBAL_BLOCK = """
You are a real Twitter account with opinions. You take sides. You are not neutral, cautious, or an assistant.

BANNED (hard rules):
- Hashtags. NFA/DYOR disclaimers. Saying or implying you are an AI. Em-dashes.
- Emoji only where your persona's voice calls for it — not sprinkled in.
- Corporate or brand tone. Forced jokes.

OUTPUT:
- English only. 280 character hard limit.
- When market data is present: every candidate covers a DIFFERENT market — never two candidates on the same market. One tweet = one market only.
- Output tweet text only. No labels, no intro, no surrounding quotes, no explanation.
""".strip()

_NUMBER_DISCIPLINE_BLOCK = """NUMBER DISCIPLINE:
Use only numbers from the market data below. Never invent probabilities, prices, or point changes.
Only mention a price movement if the data explicitly shows a before/after value or a "moved Xpts" line."""

_GLOBAL_BLOCK_VOICE_ONLY = """
You are a real Twitter account with opinions. You take sides. You are not neutral, cautious, or an assistant.

BANNED (hard rules):
- Hashtags. NFA/DYOR disclaimers. Saying or implying you are an AI. Em-dashes.
- Emoji only where your persona's voice calls for it — not sprinkled in.
- Corporate or brand tone. Forced jokes.
- Any reference to prediction markets, betting platforms, odds, prices, trading positions, or market outcomes. Never name Polymarket, Kalshi, Manifold, or any similar platform. Never use betting or trading language ("edge", "fade", "priced in", "at X%", "volume", "flow").

OUTPUT:
- English only. 280 character hard limit.
- Each candidate covers a different topic.
- Output tweet text only. No labels, no intro, no surrounding quotes, no explanation.
""".strip()

_MARKET_HANDLE_TAGS = {"crypto", "quant"}

# Prediction market platform official accounts — always excluded from voice-only context
# regardless of how the classifier tagged them (often mis-tagged as general/news)
_PLATFORM_HANDLES = {
    "kalshi", "kalshi_film", "kalshihq", "kalshinewsroom",
    "kalshipolitics", "kalshisports",
    "caronpolymarket", "polymarketsport", "polymarkettrade",
    "predofficial", "predmtrader",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _movement_magnitude(m: Market) -> float:
    mv = m.movement or {}
    return abs(mv.get("change", 0.0)) if mv.get("available") else 0.0


def _is_zero_market(m: Market) -> bool:
    """True if any outcome is effectively resolved (<1%) — no real edge to express."""
    return any(p < 0.01 for p in m.prices)


def format_market(m: Market) -> str:
    odds = " | ".join(f"{o}: {p*100:.0f}%" for o, p in zip(m.outcomes, m.prices))
    line = f'"{m.question}" — {odds}'
    mv = m.movement or {}
    if mv.get("available"):
        line += f" — moved {mv['change']*100:+.1f}pts over {mv['interval']}"
    if m.volume_24h:
        line += f" — vol ${m.volume_24h:,.0f}"
    return line


def markets_for_persona(persona: dict, markets: list[Market],
                        offset: int = 0) -> list[Market]:
    pool = markets

    # filter 0% markets for personas that make bad calls on them
    if persona["id"] in _FILTER_ZERO_MARKETS:
        pool = [m for m in pool if not _is_zero_market(m)]

    # fade needs a real chalk (≥65% favorite) — close markets produce weak fades
    if persona["id"] == "fade_the_chalk":
        chalk_pool = [m for m in pool if max(m.prices, default=0) >= 0.65]
        pool = chalk_pool if chalk_pool else pool  # fall back if no chalk exists

    # whale-watch persona needs top volume markets — no offset, always highest flow
    if persona["id"] == "size_is_hitting":
        return sorted(pool, key=lambda m: m.volume_24h or 0, reverse=True)[:_MARKETS_PER_PERSONA]

    # goblin needs niche/weird markets — lowest volume, most obscure
    if persona["id"] == "market_goblin":
        return sorted(pool, key=lambda m: m.volume_24h or 0)[:_MARKETS_PER_PERSONA]

    # degen needs absurdly low-probability markets — "so you're saying there's a chance"
    if persona["id"] == "still_has_value":
        return sorted(pool, key=lambda m: min(m.prices) if m.prices else 1.0)[:_MARKETS_PER_PERSONA]

    # sort by movement magnitude; each persona gets a shifted window for variety
    ranked = sorted(pool, key=_movement_magnitude, reverse=True)
    start = (offset * _MARKETS_PER_PERSONA) % max(len(ranked), 1)
    return (ranked + ranked)[start:start + _MARKETS_PER_PERSONA]


def _collect_tweets(source, handles: list[str], per: int, cap: int,
                    seed: int | None = None,
                    exclude_keywords: set[str] | None = None) -> list[str]:
    rng = random.Random(seed)
    shuffled = rng.sample(handles, len(handles))
    out: list[str] = []
    for h in shuffled:
        all_tweets = [t["text"] for t in source.fetch(h, 20)]
        if exclude_keywords:
            all_tweets = [
                t for t in all_tweets
                if not any(kw in t.lower() for kw in exclude_keywords)
                and not _PERCENT_RE.search(t)
            ]
        sampled = rng.sample(all_tweets, min(per, len(all_tweets)))
        for text in sampled:
            out.append(text)
            if len(out) >= cap:
                return out
    return out


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------
def build_system_prompt(persona: dict) -> str:
    if persona.get("ignore_markets"):
        return _GLOBAL_BLOCK_VOICE_ONLY + "\n\n---\n\n" + persona["system_prompt"].strip()
    block = GLOBAL_BLOCK + "\n\n" + _NUMBER_DISCIPLINE_BLOCK
    return block + "\n\n---\n\n" + persona["system_prompt"].strip()


def build_user_prompt(markets: list[Market],
                      voice_tweets: list[str], n: int, *,
                      voice_only: bool = False) -> str:
    parts: list[str] = []

    if markets:
        parts.append(
            "PREDICTION MARKET DATA — each line is a separate independent market.\n"
            "Use only names and numbers that appear below. Do not combine odds across markets."
        )
        for i, m in enumerate(markets):
            parts.append(f"  [{i+1}] {format_market(m)}")

    if voice_tweets:
        if voice_only:
            parts.append(
                "\nVOICE REFERENCE — these are real tweets happening right now on Twitter. "
                "This is your only source material. Pick topics, reactions, and conversations "
                "that are alive in here and work from them. Do not copy sentences verbatim:"
            )
        else:
            parts.append(
                "\nVOICE REFERENCE — these tweets contain real events, opinions, and reactions happening right now. "
                "Mine them for ideas and angles: what just happened, what people are reacting to, what the narrative is. "
                "Connect those events and ideas to the market data above — that connection is the tweet. "
                "Also steal their tone, energy, and speaking style. Do not copy sentences verbatim:"
            )
        for t in voice_tweets:
            parts.append(f"  - {t}")

    if voice_only:
        parts.append(
            f"\nWrite {n} candidate tweets in your persona's voice, each about a different topic from the tweets above."
        )
    else:
        parts.append(
            f"\nWrite {n} candidate tweets in your persona's voice, each from a different angle."
        )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run_batch(cfg: dict, *, market_limit: int | None = None,
              with_movement: bool = True,
              persona_counts: dict | None = None) -> dict[str, list[str]]:
    settings = cfg["settings"]
    n_default = max(1, min(4, settings.get("llm", {}).get("candidates_per_run", 3)))
    shared_tags = settings.get("shared_tags", ["general", "news"])
    pm = settings.get("polymarket", {})

    classifications = get_classifications(cfg)
    provider = llm.get_provider(cfg)
    source = tw.get_source(cfg)

    limit = market_limit or pm.get("markets_limit", 50)
    markets = fetch_markets(cfg, limit=limit)
    if with_movement:
        add_movement(markets, interval=pm.get("movement_interval", "1d"),
                     fidelity=pm.get("movement_fidelity", 60))
    snapshot_and_diff(markets)

    out: dict[str, list[str]] = {}
    for persona_idx, persona in enumerate(cfg["personas"]):
        n = int((persona_counts or {}).get(persona["id"], n_default))
        if n == 0:
            out[persona["id"]] = []
            continue

        voice_only = bool(persona.get("ignore_markets"))
        if voice_only:
            persona_markets = []
        else:
            persona_markets = markets_for_persona(persona, markets, offset=persona_idx)
            if not persona_markets:
                out[persona["id"]] = []
                continue

        voice_h, info_h = routing.sources_split(persona, classifications, shared_tags)
        all_handles = voice_h + [h for h in info_h if h not in voice_h]
        if voice_only:
            all_handles = [
                h for h in all_handles
                if h.lower() not in _PLATFORM_HANDLES
                and not (_MARKET_HANDLE_TAGS & set(classifications.get(h, {}).get("tags", [])))
            ]
            if not all_handles:
                print(f"[skip] {persona['id']}: no handles left after voice-only filter")
                out[persona["id"]] = []
                continue
        tweet_cap = _MAX_CONTEXT_VOICE_ONLY if voice_only else _MAX_CONTEXT
        voice_tweets = _collect_tweets(source, all_handles,
                                       _CONTEXT_PER_SOURCE, tweet_cap,
                                       seed=(persona_idx + int(time.time()) // 1800) if voice_only else None,
                                       exclude_keywords=_MARKET_KEYWORDS if voice_only else None)

        system = build_system_prompt(persona)
        user = build_user_prompt(persona_markets, voice_tweets, n,
                                 voice_only=voice_only)
        temperature = persona.get("temperature", 0.8)

        candidates = llm.generate(provider, system, user, n, temperature=temperature)
        filtered, dropped = [], 0
        for t in candidates:
            if t.strip().upper() == "SKIP":
                continue
            if len(t) > 280:
                print(f"[drop] {persona['id']}: {len(t)} chars — over 280, excluded")
                dropped += 1
                continue
            filtered.append(t)
        if dropped > 0:
            retry_user = user + "\n\nIMPORTANT: Every tweet must be strictly under 280 characters. Count carefully before outputting."
            retry = llm.generate(provider, system, retry_user, dropped, temperature=temperature)
            for t in retry:
                if t.strip().upper() != "SKIP" and len(t) <= 280:
                    filtered.append(t)
        out[persona["id"]] = filtered

    return out


if __name__ == "__main__":
    from src.config import load_config
    import json
    cfg = load_config()
    batch = run_batch(cfg)
    print(json.dumps(batch, indent=2, ensure_ascii=False))
