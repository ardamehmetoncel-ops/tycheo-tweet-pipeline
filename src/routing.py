"""Module 4 — tag-based source -> persona routing.

A source's effective tags = {its tier} | {its topic tags}.
A persona receives a source when EITHER:
  - the source is in the shared pool (its tags intersect settings.shared_tags,
    e.g. general/news) -> goes to ALL personas (information, not voice), or
  - the source's tags intersect the persona's declared tags (voice match).
"""
from __future__ import annotations


def effective_tags(classification: dict) -> set[str]:
    return {classification.get("tier", "middle")} | set(classification.get("tags", []))


def is_shared(classification: dict, shared_tags: list[str]) -> bool:
    return bool(effective_tags(classification) & set(shared_tags))


def sources_for_persona(persona: dict, classifications: dict[str, dict],
                        shared_tags: list[str]) -> list[str]:
    """Handles whose tags match this persona, plus the shared pool."""
    persona_tags = set(persona.get("tags", []))
    shared = set(shared_tags)
    out = []
    for handle, c in classifications.items():
        tags = effective_tags(c)
        if (tags & shared) or (tags & persona_tags):
            out.append(handle)
    return out


def route_all(personas: list[dict], classifications: dict[str, dict],
              shared_tags: list[str]) -> dict[str, list[str]]:
    """{persona_id: [handles feeding it]} for the whole roster."""
    return {p["id"]: sources_for_persona(p, classifications, shared_tags)
            for p in personas}


def sources_split(persona: dict, classifications: dict[str, dict],
                  shared_tags: list[str]) -> tuple[list[str], list[str]]:
    """Split a persona's sources into (voice, info).

    info  = shared-pool sources (general/news) -> information, tone ignored.
    voice = persona-tag matches that are NOT in the shared pool -> style.
    A shared source is treated as info-only even if it also voice-matches,
    so the news wire can't leak its tone into a persona's voice.
    """
    persona_tags = set(persona.get("tags", []))
    shared = set(shared_tags)
    voice, info = [], []
    for handle, c in classifications.items():
        tags = effective_tags(c)
        if tags & shared:
            info.append(handle)
        elif tags & persona_tags:
            voice.append(handle)
    return voice, info
