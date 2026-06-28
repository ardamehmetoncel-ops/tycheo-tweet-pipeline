"""Module 5 — generation orchestration.

Per persona: assemble routed voice tweets (style) + shared-pool tweets (info)
+ live Polymarket context (+ optional FinBERT signal for reactive personas),
build the prompt, ask the LLM for N candidates. Returns {persona_id: [posts]}.
"""
from __future__ import annotations

from src import routing
from src.classify.classifier import get_classifications
from src.ingestion import tweets as tw
from src.ingestion.polymarket import (Market, fetch_markets, add_movement,
                                      snapshot_and_diff)
from src.llm import provider as llm

# prompt-size caps so context stays tight
_VOICE_PER_SOURCE = 3
_MAX_VOICE = 15
_INFO_PER_SOURCE = 2
_MAX_INFO = 10
_MARKETS_PER_PERSONA = 3

_FOOTBALL_KW = ("football", "premier league", "champions league", "epl", "uefa",
                "la liga", "serie a", "bundesliga", "soccer", "fc ", "match")


# -- context formatting -----------------------------------------------------
def format_market(m: Market) -> str:
    odds = " | ".join(f"{o}: {p*100:.0f}%" for o, p in zip(m.outcomes, m.prices))
    line = f'Q: "{m.question}" — {odds}'
    mv = m.movement or {}
    if mv.get("available"):
        line += f" — moved {mv['change']*100:+.1f}pts over {mv['interval']}"
    return line


def _is_football(m: Market) -> bool:
    blob = f"{m.question} {m.event_title or ''}".lower()
    return any(k in blob for k in _FOOTBALL_KW)


def markets_for_persona(persona: dict, markets: list[Market]) -> list[Market]:
    if persona["id"] == "football_crossover":
        footy = [m for m in markets if _is_football(m)]
        if footy:
            return footy[:_MARKETS_PER_PERSONA]
    return markets[:_MARKETS_PER_PERSONA]


def _collect(source, handles: list[str], per: int, cap: int) -> list[str]:
    out: list[str] = []
    for h in handles:
        for t in source.fetch(h, per):
            out.append(t["text"])
            if len(out) >= cap:
                return out
    return out


def build_user_prompt(persona: dict, markets: list[Market],
                      voice: list[str], info: list[str],
                      sentiment: dict | None) -> str:
    parts: list[str] = []
    if markets:
        parts.append(
            "CURRENT PREDICTION MARKETS — each is a SEPARATE independent question.\n"
            "Read each Q: line on its own. Do NOT combine or mix odds across questions.\n"
            "Use ONLY team names, countries, and numbers that appear below — invent nothing."
        )
        parts += [f"  [{i+1}] {format_market(m)}" for i, m in enumerate(markets)]
    if persona.get("sentiment_reactive") and sentiment:
        parts.append(f"\nMARKET MOOD (sentiment signal): {sentiment.get('label')} "
                     f"({sentiment.get('score'):+.2f})")
    if voice:
        parts.append("\nSTYLE INSPIRATION (match the energy and voice; do NOT copy "
                     "wording or reuse specifics):")
        parts += [f"- {t}" for t in voice]
    if info:
        parts.append("\nCONTEXT — WHAT'S HAPPENING (information only; ignore its tone):")
        parts += [f"- {t}" for t in info]
    parts.append(
        "\nWrite ONE post in your own voice. English. Hard limit: under 280 characters. "
        "Every number and name you use MUST come from the market data above — no inventions. "
        "Output only the tweet text — no intro, no label, no surrounding quotes, no explanation."
    )
    return "\n".join(parts)


_FINBERT_WARNED = False


def compute_sentiment(cfg: dict, classifications: dict, source,
                      markets: list[Market]) -> dict | None:
    """Run-level sentiment from the shared news pool + market movement.

    Returns None when FinBERT is off, deps are missing, or there's nothing to score.
    """
    global _FINBERT_WARNED
    if not cfg["settings"].get("finbert", {}).get("enabled"):
        return None

    shared_tags = cfg["settings"].get("shared_tags", ["general", "news"])
    handles = [h for h, c in classifications.items()
               if routing.is_shared(c, shared_tags)]
    texts = _collect(source, handles, _INFO_PER_SOURCE, _MAX_INFO)
    # add markets that actually moved, as natural-language context
    for m in markets:
        mv = m.movement or {}
        if mv.get("available") and abs(mv.get("change", 0)) >= 0.03:
            texts.append(f"{m.question} moved {mv['change']*100:+.0f} points.")
    if not texts:
        return None

    try:
        from src.sentiment import finbert
        return finbert.score(texts)
    except ImportError:
        if not _FINBERT_WARNED:
            print("[finbert] enabled but transformers/torch not installed — "
                  "run: pip install -r requirements-finbert.txt. Skipping sentiment.")
            _FINBERT_WARNED = True
        return None


# -- orchestration ----------------------------------------------------------
def run_batch(cfg: dict, *, sentiment_signal: dict | None = None,
              market_limit: int = 12, with_movement: bool = True) -> dict[str, list[str]]:
    settings = cfg["settings"]
    n = settings.get("llm", {}).get("candidates_per_run", 3)
    shared_tags = settings.get("shared_tags", ["general", "news"])
    pm = settings.get("polymarket", {})

    classifications = get_classifications(cfg)        # cached
    provider = llm.get_provider(cfg)
    source = tw.get_source(cfg)

    markets = fetch_markets(cfg, limit=market_limit)
    if with_movement:
        add_movement(markets, interval=pm.get("movement_interval", "1d"),
                     fidelity=pm.get("movement_fidelity", 60))
    snapshot_and_diff(markets)                         # persist run-over-run deltas

    if sentiment_signal is None:                       # compute once per run if enabled
        sentiment_signal = compute_sentiment(cfg, classifications, source, markets)

    out: dict[str, list[str]] = {}
    for persona in cfg["personas"]:
        voice_h, info_h = routing.sources_split(persona, classifications, shared_tags)
        voice = _collect(source, voice_h, _VOICE_PER_SOURCE, _MAX_VOICE)
        info = _collect(source, info_h, _INFO_PER_SOURCE, _MAX_INFO)
        user = build_user_prompt(persona, markets_for_persona(persona, markets),
                                 voice, info, sentiment_signal)
        out[persona["id"]] = llm.generate(provider, persona["system_prompt"], user, n)
    return out


if __name__ == "__main__":
    from src.config import load_config
    import json
    cfg = load_config()
    batch = run_batch(cfg)
    print(json.dumps(batch, indent=2, ensure_ascii=False))
