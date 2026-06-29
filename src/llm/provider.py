"""Provider-agnostic LLM layer.

Default = Anthropic (Claude). Swap to OpenAI / Ollama via settings.llm.provider
with a single config change. Every provider implements just `complete()`; the
N-candidate `generate()` is a free function that wraps it, so adapters stay thin.
"""
from __future__ import annotations

import json
import re

import requests


# -- providers --------------------------------------------------------------
class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str | None, model: str):
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set (llm.provider=anthropic)")
        from anthropic import Anthropic            # lazy import: dep is optional
        self.client = Anthropic(api_key=api_key)
        self.model = model

    def complete(self, system: str, user: str, *,
                 max_tokens: int = 1024, temperature: float = 0.7) -> str:
        msg = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, temperature=temperature,
            system=system, messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str | None, model: str):
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set (llm.provider=openai)")
        from openai import OpenAI                   # lazy import
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def complete(self, system: str, user: str, *,
                 max_tokens: int = 1024, temperature: float = 0.7) -> str:
        r = self.client.chat.completions.create(
            model=self.model, max_tokens=max_tokens, temperature=temperature,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        return r.choices[0].message.content or ""


class OllamaProvider:
    name = "ollama"

    def __init__(self, host: str, model: str):
        self.host = host.rstrip("/")
        self.model = model

    def complete(self, system: str, user: str, *,
                 max_tokens: int = 1024, temperature: float = 0.7) -> str:
        r = requests.post(
            f"{self.host}/api/chat",
            json={"model": self.model, "stream": False,
                  "options": {"temperature": temperature, "num_predict": max_tokens},
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
            timeout=120,
        )
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "")


class XAIProvider:
    """xAI Grok — OpenAI-compatible API at https://api.x.ai/v1."""
    name = "xai"
    _BASE_URL = "https://api.x.ai/v1"

    def __init__(self, api_key: str | None, model: str):
        if not api_key:
            raise RuntimeError("XAI_API_KEY not set (llm.provider=xai)")
        from openai import OpenAI                   # lazy import
        self.client = OpenAI(api_key=api_key, base_url=self._BASE_URL)
        self.model = model

    def complete(self, system: str, user: str, *,
                 max_tokens: int = 1024, temperature: float = 0.7) -> str:
        r = self.client.chat.completions.create(
            model=self.model, max_tokens=max_tokens, temperature=temperature,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        return r.choices[0].message.content or ""


def get_provider(cfg: dict):
    llm = cfg["settings"].get("llm", {})
    provider = llm.get("provider", "anthropic")
    model = llm.get("model", "claude-sonnet-4-6")
    secrets = cfg.get("secrets", {})
    if provider == "anthropic":
        return AnthropicProvider(secrets.get("anthropic"), model)
    if provider == "openai":
        return OpenAIProvider(secrets.get("openai"), model)
    if provider == "ollama":
        return OllamaProvider(secrets.get("ollama_host", "http://localhost:11434"), model)
    if provider == "xai":
        return XAIProvider(secrets.get("xai"), model)
    raise ValueError(f"unknown llm.provider: {provider!r} (anthropic | openai | ollama | xai)")


# -- N-candidate generation (works with any provider) -----------------------
_PREAMBLES = (
    "here are", "here is", "tweet:", "post:", "draft:", "sure,",
    "certainly,", "of course,", "in the style", "example tweet",
    "candidate tweet", "based on", "i'll write", "i will write",
)


def _clean(text: str) -> str:
    """Strip model preamble and extract the actual tweet text."""
    text = text.strip()
    # strip markdown bold/italic wrapping (common in Ollama output)
    text = re.sub(r'\*{1,2}([^*\n]+)\*{1,2}', r'\1', text)
    text = re.sub(r'_{1,2}([^_\n]+)_{1,2}', r'\1', text)
    # strip surrounding quotes
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        text = text[1:-1].strip()
    # if preamble detected, try to pull out first quoted passage or skip first line
    if any(text.lower().startswith(p) for p in _PREAMBLES):
        m = re.search(r'"([^"]{15,})"', text)
        if m:
            return m.group(1).strip()
        lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
        if len(lines) > 1:
            return lines[1].strip().strip('"\'')
    return text


def generate(provider, system: str, user: str, n: int, *,
             max_tokens: int = 400, temperature: float = 0.9) -> list[str]:
    """Generate n candidate posts. For n=1 skips JSON (smaller models handle direct better)."""
    if n == 1:
        raw = provider.complete(system, user, max_tokens=max_tokens,
                                temperature=temperature)
        return [_clean(raw)]

    # for n>1 try JSON first, fall back to individual calls
    instruction = (
        f"{user}\n\nProduce exactly {n} DISTINCT candidate posts. "
        f'Return STRICT JSON only — no prose, no markdown: {{"posts": ["tweet 1", "tweet 2"]}}. '
        f'If your persona conditions are not met and you must skip, '
        f'return {{"posts": ["SKIP"]}} instead of plain text.'
    )
    raw = provider.complete(system, instruction,
                            max_tokens=max_tokens, temperature=temperature)
    # fast-path: model returned plain SKIP before attempting JSON
    if raw.strip().upper() == "SKIP":
        return ["SKIP"]
    try:
        posts = parse_json_object(raw).get("posts", [])
        posts = [_clean(p) for p in posts if isinstance(p, str) and p.strip()]
        if posts and posts[0].upper() == "SKIP":
            return ["SKIP"]
        if len(posts) >= n:
            return posts[:n]
    except Exception:
        pass
    # fallback: independent single completions — replace multi-tweet instruction with single
    single_user = re.sub(r'\nWrite \d+ candidate tweets[^\n]*',
                         '\nWrite 1 candidate tweet in your persona\'s voice.',
                         user)
    return [_clean(provider.complete(system, single_user, max_tokens=max_tokens,
                                     temperature=temperature)) for _ in range(n)]


# -- shared helper ----------------------------------------------------------
def parse_json_object(text: str) -> dict:
    """Tolerant JSON extraction: strips code fences, grabs the first {...} block."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise
