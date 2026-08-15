"""Conservative fusion of the top two candidate answers.

Fusion NEVER generates new sentences: it concatenates unique sentences from
the runner-up onto the winner, deduplicates near-identical sentences, keeps
citations, and aborts entirely when the candidates contradict each other or
either is below the quality bar. The fused text is re-scored and only used if
it is not worse than the winner.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.config import Settings, get_settings
from app.judge.scoring import Candidate, HeuristicJudge, cosine, split_sentences
from app.orchestrator.normalize import STOPWORDS, NormalizedQuery

_NEGATIONS = ("not", "no", "never", "cannot", "can't", "isn't", "aren't", "don't",
              "doesn't", "didn't", "won't", "without", "unlike", "false", "wrong")
_RARE_RE = re.compile(r"\b([A-Za-z]{6,}|\d{2,4})\b")
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def _rare_terms(text: str) -> set[str]:
    return {t.lower() for t in _RARE_RE.findall(text)}


def _negated_terms(sentence: str) -> set[str]:
    lowered = sentence.lower()
    if not any(w in lowered.split() for w in _NEGATIONS):
        return set()
    return _rare_terms(sentence)


def _token_sets(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower())) - STOPWORDS


def _sentences_contradict(a: str, b: str) -> bool:
    """Heuristic contradiction check: a rare term asserted in one sentence and
    negated in another, or different years/dates asserted for the same fact."""
    for sa in split_sentences(a):
        for sb in split_sentences(b):
            neg_a, neg_b = _negated_terms(sa), _negated_terms(sb)
            if neg_a and not _negated_terms(sb):
                if neg_a & _rare_terms(sb):
                    return True
            if neg_b and not neg_a:
                if neg_b & _rare_terms(sa):
                    return True
            years_a, years_b = set(_YEAR_RE.findall(sa)), set(_YEAR_RE.findall(sb))
            if years_a and years_b and years_a != years_b:
                return True
    return False


def _sentences_equivalent(a: str, b: str, embedder_emb=None) -> bool:
    """True when two sentences convey the same content."""
    ta, tb = _token_sets(a), _token_sets(b)
    if not ta or not tb:
        return False
    jaccard = len(ta & tb) / len(ta | tb)
    if jaccard >= 0.85:
        return True
    if embedder_emb is not None and len(embedder_emb) == 2:
        return cosine(embedder_emb[0], embedder_emb[1]) >= 0.97
    return False


@dataclass
class FusionResult:
    text: str
    sources: list[str] = field(default_factory=list)
    used: bool = False
    skipped_reason: str | None = None


class FusionEngine:
    def __init__(self, settings: Settings | None = None, judge: HeuristicJudge | None = None):
        self.settings = settings or get_settings()
        self.judge = judge or HeuristicJudge(self.settings)

    def fuse(
        self,
        query: NormalizedQuery,
        top: Candidate,
        second: Candidate,
        *,
        query_embedding: list[float] | None = None,
        embeddings: list[list[float]] | None = None,
    ) -> FusionResult:
        assert top.score is not None and second.score is not None
        min_score = self.settings.judge_fusion_min_score
        margin = self.settings.judge_fusion_score_margin
        if top.score.total < min_score or second.score.total < min_score:
            return FusionResult(top.text, skipped_reason="below_fusion_quality_bar")
        if top.score.total - second.score.total > margin:
            return FusionResult(top.text, skipped_reason="winner_too_strong")
        if _sentences_contradict(top.text, second.text):
            return FusionResult(top.text, skipped_reason="contradictory_candidates")

        base_sentences = split_sentences(top.text)

        max_words = self.settings.judge_max_answer_tokens * 2
        word_count = len(re.findall(r"\w+", top.text))
        appended: list[str] = []
        for sentence in split_sentences(second.text):
            duplicate = False
            for base in base_sentences:
                if _sentences_equivalent(base, sentence, embedder_emb=None):
                    duplicate = True
                    break
            if duplicate:
                continue
            n_words = len(re.findall(r"\w+", sentence))
            if word_count + n_words > max_words:
                break
            appended.append(sentence)
            word_count += n_words

        if not appended:
            return FusionResult(top.text, skipped_reason="runner_up_fully_redundant")

        fused_text = " ".join(base_sentences + appended)
        fused_score = self.judge.score(
            query, fused_text, top.latency_ms,
            query_embedding=query_embedding,
        )
        if fused_score.total < top.score.total:
            return FusionResult(top.text, skipped_reason="fusion_scored_worse")

        sources: list[str] = []
        seen: set[str] = set()
        for candidate in (top, second):
            for src in candidate.sources:
                if src not in seen:
                    seen.add(src)
                    sources.append(src)
        return FusionResult(fused_text, sources=sources, used=True)
