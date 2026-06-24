"""Module 7 — optional FinBERT sentiment layer (behind settings.finbert.enabled).

FinBERT is an ENCODER/classifier: it SCORES text sentiment, it never generates.
Model: ProsusAI/finbert (labels: positive / negative / neutral).

score() turns a batch of texts into one signed signal in [-1, 1]:
    mean(P(positive) - P(negative))  ->  bearish | neutral | bullish

Heavy deps (transformers, torch) are imported lazily and installed separately
(requirements-finbert.txt), so the rest of the tool runs without them.
"""
from __future__ import annotations

_PIPE = None
_BULL = 0.15            # |signal| thresholds for the label band
_BEAR = -0.15


def _get_pipe():
    """Lazy singleton text-classification pipeline (loads the model once)."""
    global _PIPE
    if _PIPE is None:
        from transformers import pipeline          # heavy: torch + model download
        _PIPE = pipeline("text-classification", model="ProsusAI/finbert", top_k=None)
    return _PIPE


def _label(signal: float) -> str:
    if signal > _BULL:
        return "bullish"
    if signal < _BEAR:
        return "bearish"
    return "neutral"


def score(texts: list[str], *, pipe=None) -> dict:
    """Return {"label", "score", "n"} for a batch of texts.

    `pipe` is injectable for testing; defaults to the real FinBERT pipeline.
    """
    texts = [t for t in texts if t and t.strip()]
    if not texts:
        return {"label": "neutral", "score": 0.0, "n": 0}

    pipe = pipe or _get_pipe()
    results = pipe(texts, truncation=True)
    signed = []
    for r in results:
        probs = {x["label"].lower(): x["score"] for x in r}
        signed.append(probs.get("positive", 0.0) - probs.get("negative", 0.0))
    mean = sum(signed) / len(signed)
    return {"label": _label(mean), "score": round(mean, 3), "n": len(texts)}
