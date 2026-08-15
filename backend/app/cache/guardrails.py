"""Semantic-cache guardrails.

A cache entry may ONLY be served when every guardrail passes:

1. cosine similarity >= threshold (stricter when cache is used as a fallback)
2. intent matches exactly
3. language matches
4. entities match (Jaccard >= min AND key date/number entities equal)
5. no time-sensitive mismatch (fresh entries only for time-sensitive queries)
6. confidence >= threshold (judge score at write time)
7. TTL not expired

Any single failure rejects the hit — "when in doubt, regenerate".
"""
from __future__ import annotations

import math
from datetime import UTC, datetime


def _as_utc(dt: datetime) -> datetime:
    """SQLite drops tzinfo; treat naive datetimes as UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def entity_set(entities: dict[str, list[str]]) -> set[str]:
    return {
        f"{kind}:{value}"
        for kind, values in entities.items()
        if kind not in ("dates", "numbers")
        for value in values
    }


def key_entities_match(entities_q: dict[str, list[str]], entities_e: dict[str, list[str]]) -> bool:
    """Exact equality for keyed temporal/numeric entities — a date difference
    invalidates the entry even if everything else looks similar."""
    for kind in ("dates", "numbers"):
        q_values = sorted(v.lower() for v in entities_q.get(kind, []))
        e_values = sorted(v.lower() for v in entities_e.get(kind, []))
        if q_values != e_values:
            return False
    return True


def guardrails_pass(
    *,
    similarity: float,
    intent_q: str | None,
    intent_e: str | None,
    lang_q: str | None,
    lang_e: str | None,
    entities_q: dict,
    entities_e: dict,
    time_sensitive_q: bool,
    entry_created_at: datetime,
    now: datetime,
    confidence: float,
    expires_at: datetime,
    threshold: float,
    entity_jaccard_min: float,
    confidence_threshold: float,
    time_sensitive_max_age_s: int,
) -> tuple[bool, list[str]]:
    failed: list[str] = []

    if similarity < threshold:
        failed.append(f"similarity={similarity:.3f}<{threshold}")
    if intent_q and intent_e and intent_q != intent_e:
        failed.append(f"intent:{intent_q}!={intent_e}")
    elif not (intent_q and intent_e):
        failed.append("intent_unknown")
    if lang_q and lang_e and lang_q != lang_e:
        failed.append(f"language:{lang_q}!={lang_e}")
    elif not (lang_q and lang_e):
        failed.append("language_unknown")
    if jaccard(entity_set(entities_q), entity_set(entities_e)) < entity_jaccard_min:
        failed.append("entity_overlap_below_threshold")
    if not key_entities_match(entities_q, entities_e):
        failed.append("key_entities_mismatch")
    created = _as_utc(entry_created_at)
    now_utc = _as_utc(now)
    if time_sensitive_q and (now_utc - created).total_seconds() > time_sensitive_max_age_s:
        failed.append("time_sensitive_stale")
    if confidence < confidence_threshold:
        failed.append(f"confidence={confidence:.3f}<{confidence_threshold}")
    if _as_utc(expires_at) <= now_utc:
        failed.append("expired")

    return (not failed), failed
