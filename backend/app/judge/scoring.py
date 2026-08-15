"""Hybrid judge — deterministic heuristic scoring + optional local model tie-break.

Scoring dimensions and weights (spec):
  relevance 35% · factuality 30% · completeness 15% · readability 10% · latency 10%

The safety gate (judge/safety.py) is a hard gate applied *before* scoring: an
unsafe candidate is never scored and never shown.

Every dimension is a deterministic function — reproducible in tests and
explainable in the audit trail. ``HeuristicJudge`` can be extended with a
lightweight local judge model (``local_tie_breaker``) that only breaks ties
within ``tie_margin``, keeping costs near zero.
"""
from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from app.core.config import Settings, get_settings
from app.judge.safety import is_refusal
from app.orchestrator.normalize import STOPWORDS, NormalizedQuery

DIMENSION_WEIGHTS = {
    "relevance": 0.35,
    "factuality": 0.30,
    "completeness": 0.15,
    "readability": 0.10,
    "latency": 0.10,
}
assert abs(sum(DIMENSION_WEIGHTS.values()) - 1.0) < 1e-9

_HEDGES = {
    "maybe", "perhaps", "i think", "i believe", "probably", "might", "could be",
    "not sure", "possibly", "appears to", "seems to", "i guess", "approximately",
    "roughly", "i'm not entirely sure", "it is possible that", "likely",
}
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?\u0964])\s+(?=[A-Z0-9\u0900-\u097F])")


@dataclass
class ScoreResult:
    relevance: float = 0.0
    factuality: float = 0.0
    completeness: float = 0.0
    readability: float = 0.0
    latency: float = 0.0
    total: float = 0.0
    passed_gate: bool = False
    flags: list[str] = field(default_factory=list)


@dataclass
class Candidate:
    """A single model answer + provenance (internal only — never user-facing)."""

    model_id: str
    provider: str
    tier: str
    text: str
    latency_ms: float
    tokens_in: int = 0
    tokens_out: int = 0
    finish_reason: str | None = None
    score: ScoreResult | None = None
    sources: list[str] = field(default_factory=list)

    def anonymized_label(self, index: int) -> str:
        return f"Candidate {chr(ord('A') + index)}"


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_SPLIT_RE.split(text) if p.strip()]
    if not parts:
        return [text.strip()] if text.strip() else []
    # Merge orphaned list markers ("1.", "•", "-") into the following sentence
    # so numbered lists don't distort sentence statistics.
    merged: list[str] = []
    for part in parts:
        if re.fullmatch(r"[\d]{1,3}[.)]?", part) or part in ("-", "•", "*"):
            if merged:
                merged[-1] = f"{merged[-1]} {part}"
            continue
        merged.append(part)
    return merged or parts


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9\u0900-\u097F]+", text.lower())) - STOPWORDS


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _is_question_echo(query: NormalizedQuery, answer: str) -> bool:
    q = re.sub(r"[^a-z0-9\u0900-\u097F ]", "", query.text.lower())
    a = re.sub(r"[^a-z0-9\u0900-\u097F ]", "", answer.lower())
    if len(q) >= 16 and q in a:
        return True
    # Nearly-verbatim echo: >80% of the query's non-stopword tokens appear in
    # the same order inside the answer.
    key = [t for t in query.key_tokens if len(t) > 2]
    if len(key) >= 3:
        seq = " ".join(key)
        if seq in a:
            return True
    return False


def _lexical_relevance(query: NormalizedQuery, answer: str) -> float:
    q_tokens = query.key_tokens
    if not q_tokens:
        return 0.5
    a_tokens = _tokens(answer)
    covered = [t for t in q_tokens if t in a_tokens]
    # Rare-looking tokens (long, not trivially common) count double.
    weighted = sum(2.0 if len(t) >= 5 else 1.0 for t in covered)
    max_weighted = sum(2.0 if len(t) >= 5 else 1.0 for t in q_tokens)
    return weighted / max_weighted if max_weighted else 0.0


def _factuality(query: NormalizedQuery, answer: str, sources: list[str] | None) -> tuple[float, list[str]]:
    flags: list[str] = []
    score = 1.0
    sentences = split_sentences(answer)
    if sentences:
        hedged = sum(1 for s in sentences if any(h in s.lower() for h in _HEDGES))
        hedge_ratio = hedged / len(sentences)
        if hedge_ratio > 0.5:
            score -= 0.4
            flags.append("heavily_hedged")
        elif hedge_ratio > 0.25:
            score -= 0.2
            flags.append("hedged")
    if is_refusal(answer):
        score = min(score, 0.45)
        flags.append("refusal")
    # Naive self-contradiction: a rare noun asserted and negated in the same answer.
    noun_pos = re.findall(r"\b(?:is|are|was|were|has|have)\s+(?:a|an|the)?\s*([a-z]{5,})", answer.lower())
    neg_pos = re.findall(r"\b(?:is not|isn't|are not|aren't|was not|wasn't)\s+(?:a|an|the)?\s*([a-z]{5,})", answer.lower())
    overlap = set(noun_pos) & set(neg_pos)
    if overlap:
        score -= 0.15 * min(len(overlap), 2)
        flags.append("self_contradiction")
    if sources and re.search(r"\[\d+\]|\(\d{4}\)|https?://", answer):
        score = min(1.0, score + 0.05)
    return max(0.0, min(1.0, score)), flags


def _completeness(query: NormalizedQuery, answer: str) -> float:
    q_tokens = query.key_tokens
    a_tokens = _tokens(answer)
    entity_coverage = 0.0
    if q_tokens:
        entity_coverage = sum(1 for t in q_tokens if t in a_tokens) / len(q_tokens)
    # Sub-question coverage for multi-part questions.
    sub_parts = [p for p in re.split(r"[?;\n]|(?:\band\s+also\b)", query.text) if len(p.strip()) > 6]
    subq_score = 1.0
    if len(sub_parts) > 1:
        covered_parts = 0
        for part in sub_parts:
            part_tokens = _tokens(part)
            if not part_tokens or any(t in a_tokens for t in part_tokens):
                covered_parts += 1
        subq_score = covered_parts / len(sub_parts)
    # Length adequacy (log-ish target; penalties for terse or bloated answers).
    target = 40 + 8 * len(q_tokens)
    ratio = len(re.findall(r"\w+", answer)) / max(1.0, target)
    if ratio >= 0.5:
        length_score = max(0.0, 1.0 - abs(ratio - 1.0) / 1.5)
    else:
        length_score = ratio / 0.5
    return max(0.0, min(1.0, 0.4 * entity_coverage + 0.35 * subq_score + 0.25 * length_score))


def _readability(answer: str) -> float:
    sentences = split_sentences(answer)
    if not sentences:
        return 0.0
    words = re.findall(r"\w+", answer)
    if not words:
        return 0.0
    avg = len(words) / len(sentences)
    if 6 <= avg <= 26:
        length_score = 1.0
    elif avg < 6:
        length_score = avg / 6
    else:
        length_score = max(0.0, 1.0 - (avg - 26) / 40)
    caps = [w for w in words if len(w) > 2 and w.isupper()]
    caps_ratio = len(caps) / len(words)
    caps_penalty = 0.3 if caps_ratio > 0.25 else 0.0
    structure_bonus = 0.08 if re.search(r"\n|•|-\s|\d+\.\s", answer) else 0.0
    top_word = max(set(words), key=words.count)
    repeat_penalty = 0.1 if words.count(top_word) / len(words) > 0.18 else 0.0
    return max(0.0, min(1.0, length_score + structure_bonus - caps_penalty - repeat_penalty))


def _latency_score(latency_ms: float, settings: Settings) -> float:
    t = latency_ms / 1000.0
    soft, hard = settings.soft_timeout_s, settings.hard_timeout_s
    if t <= soft * 0.4:
        return 1.0
    denom = hard - soft * 0.4
    if denom <= 0:
        return 0.0
    return max(0.0, min(1.0, (hard - t) / denom))


class HeuristicJudge:
    """Deterministic multi-dimension scorer.

    ``local_tie_breaker`` (optional callable ``(query, a_text, b_text) -> int``)
    is invoked only when two candidates score within ``tie_margin`` — this is
    where a lightweight local judge model plugs in, keeping cloud spend at zero.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        local_tie_breaker: Callable[[NormalizedQuery, str, str], int] | None = None,
        tie_margin: float = 0.03,
    ):
        self.settings = settings or get_settings()
        self.local_tie_breaker = local_tie_breaker
        self.tie_margin = tie_margin

    def score(
        self,
        query: NormalizedQuery,
        text: str,
        latency_ms: float,
        *,
        query_embedding: list[float] | None = None,
        answer_embedding: list[float] | None = None,
        sources: list[str] | None = None,
    ) -> ScoreResult:
        lexical_relevance = _lexical_relevance(query, text)
        if query_embedding is not None and answer_embedding is not None:
            embedding_relevance = max(0.0, min(1.0, cosine(query_embedding, answer_embedding)))
            # Two complementary signals: take the best. Embeddings dominate in
            # production (real embedder); lexical overlap protects against
            # weak/crude embeddings and vocabulary mismatches.
            relevance = max(embedding_relevance, lexical_relevance)
        else:
            relevance = lexical_relevance

        # Echo penalty: an answer that merely restates the question verbatim is
        # not answering it. Cap relevance hard when the query appears verbatim.
        if _is_question_echo(query, text):
            relevance = min(relevance, 0.4)

        factuality, flags = _factuality(query, text, sources)
        completeness = _completeness(query, text)
        readability = _readability(text)
        latency = _latency_score(latency_ms, self.settings)

        total = (
            DIMENSION_WEIGHTS["relevance"] * relevance
            + DIMENSION_WEIGHTS["factuality"] * factuality
            + DIMENSION_WEIGHTS["completeness"] * completeness
            + DIMENSION_WEIGHTS["readability"] * readability
            + DIMENSION_WEIGHTS["latency"] * latency
        )
        passed = total >= self.settings.judge_quality_gate
        return ScoreResult(
            relevance=round(relevance, 4),
            factuality=round(factuality, 4),
            completeness=round(completeness, 4),
            readability=round(readability, 4),
            latency=round(latency, 4),
            total=round(total, 4),
            passed_gate=passed,
            flags=flags,
        )

    def break_tie(self, query: NormalizedQuery, a: Candidate, b: Candidate) -> Candidate:
        if self.local_tie_breaker is None:
            return a
        assert a.score is not None and b.score is not None
        if abs(a.score.total - b.score.total) > self.tie_margin:
            return a if a.score.total >= b.score.total else b
        choice = self.local_tie_breaker(query, a.text, b.text)
        return a if choice == 0 else b
