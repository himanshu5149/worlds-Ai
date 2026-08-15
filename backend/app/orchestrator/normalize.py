"""Query normalization: language, intent, entity + time-sensitivity detection.

Deterministic and dependency-free so behaviour is reproducible in tests. In
production the intent classifier can be swapped for a small local model —
the interface (``normalize_query(text) -> NormalizedQuery``) stays the same.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "of", "to", "in", "on",
    "for", "with", "at", "by", "from", "as", "is", "are", "was", "were", "be", "been",
    "do", "does", "did", "have", "has", "had", "i", "you", "he", "she", "it", "we",
    "they", "me", "my", "your", "this", "that", "these", "those", "what", "which",
    "who", "whom", "how", "why", "when", "where", "can", "could", "should", "would",
    "will", "shall", "may", "might", "must", "not", "no", "yes", "so", "than", "too",
    "very", "just", "about", "into", "over", "under", "again", "once", "here", "there",
    "all", "any", "both", "each", "few", "more", "most", "other", "some", "such",
    "only", "own", "same", "up", "down", "out", "off", "also", "please", "like",
    "get", "got", "make", "made", "use", "using", "tell", "know", "think", "need",
    "want", "let", "give", "show", "explain", "list", "find", "help", "see", "say",
    "way", "thing", "things", "one", "two", "three", "many", "much", "really",
}

_LANG_STOPWORDS = {
    "es": {"el", "la", "los", "las", "un", "una", "que", "como", "para", "por", "con"},
    "fr": {"le", "la", "les", "un", "une", "que", "qui", "comment", "pour", "avec", "est"},
    "de": {"der", "die", "das", "und", "wie", "was", "für", "mit", "ist", "ein", "eine"},
    "ne": {"को", "का", "की", "के", "मा", "छ", "हो", "छैन", "यो", "त्यो"},
}

_DATE_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?)\b",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:%|percent|kg|km|miles?|hours?|minutes?|days?|years?|usd|\$|€|£)?\b", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s]+")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_QUOTED_RE = re.compile(r'"([^"]{2,60})"|\u201c([^\u201d]{2,60})\u201d')
_CAPSEQ_RE = re.compile(r"\b(?:[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,3})\b")

TIME_TOKENS = {
    "today", "now", "currently", "current", "latest", "recently", "this week",
    "this month", "this year", "tonight", "tomorrow", "yesterday", "right now",
    "as of", "up to date", "live", "real time", "real-time",
}
TIME_DOMAINS = {
    "weather", "stock", "stocks", "price", "prices", "exchange rate", "forex",
    "crypto", "bitcoin", "news", "score", "scores", "fixture", "schedule",
    "election", "poll", "traffic", "flight", "sports", "cricket", "football",
    "match", "standings", "leaderboard",
}

_QA_MARKERS = ("what", "who", "when", "where", "why", "which", "how")
_QA_DE_RE = re.compile(r"^(?:hey|hi|hello|yo|please|ok|okay|can you|could you|would you|tell me|show me|give me|explain|list|describe|summarize|write|generate|create|build|translate|compare|calculate|solve|find|help)\b", re.IGNORECASE)


@dataclass
class NormalizedQuery:
    text: str
    language: str = "en"
    intent: str = "chat"
    entities: dict[str, list[str]] = field(default_factory=dict)
    time_sensitive: bool = False
    tokens: list[str] = field(default_factory=list)
    query_hash: str = ""

    @property
    def key_tokens(self) -> list[str]:
        return [t for t in self.tokens if t not in STOPWORDS]


def _detect_language(text: str) -> str:
    if re.search(r"[\u0900-\u097F]", text):  # Devanagari
        return "ne"
    if re.search(r"[\u3040-\u30FF\u4E00-\u9FFF]", text):
        return "zh-ja"
    if re.search(r"[\u0400-\u04FF]", text):
        return "ru"
    if re.search(r"[\u0600-\u06FF]", text):
        return "ar"
    words = set(re.findall(r"[a-zà-ÿ]+", text.lower()))
    for lang, stop in _LANG_STOPWORDS.items():
        if len(words & stop) >= 2:
            return lang
    return "en"


def _detect_intent(text: str) -> str:
    t = text.lower().strip()
    if re.search(r"\b(?:vs\.?|versus|compared? to|difference between|better than)\b", t):
        return "compare"
    if re.search(r"\b(?:how do i|how to|how can i|how should i|steps? to|tutorial)\b", t):
        return "howto"
    if re.search(r"\b(?:python|javascript|typescript|java|golang|rust|c\+\+|sql|regex|function|class|api|code|programming|bug|error|exception)\b", t):
        return "code"
    if re.search(r"\b(?:write|draft|compose|generate|create|rewrite|improve)\b.*\b(?:email|essay|poem|story|blog|letter|resume|cv|report|article|copy|message)\b", t):
        return "creative"
    if re.search(r"\b(?:summarize|summary|summarise|tldr|tl;dr)\b", t):
        return "summarise"
    if re.search(r"\b(?:translate|translation)\b", t):
        return "translate"
    if re.search(r"\b(?:list|enumerate|what are (?:the|some|all) .+\??$|top \d+)\b", t):
        return "list"
    if re.search(r"\b(?:calculate|solve|compute|evaluate|math)\b", t) or re.fullmatch(
        r"[\d\s+\-*/().%^]+", t.strip()
    ):
        return "math"
    if re.search(r"\b(?:what|who|when|where|why|which|how|explain|define|describe|tell me about)\b", t):
        return "factual"
    return "chat"


def _extract_entities(text: str) -> dict[str, list[str]]:
    entities: dict[str, list[str]] = {}
    entities["dates"] = sorted({m.group(0).lower() for m in _DATE_RE.finditer(text)})[:8]
    entities["numbers"] = sorted({m.group(0).lower() for m in _NUMBER_RE.finditer(text)})[:12]
    entities["urls"] = sorted(set(_URL_RE.findall(text)))[:5]
    emails = sorted(set(_EMAIL_RE.findall(text)))[:5]
    if emails:
        entities["emails"] = emails
    quoted = [q for groups in _QUOTED_RE.findall(text) for q in groups if q]
    if quoted:
        entities["quotes"] = quoted[:8]
    caps = sorted({m.group(0) for m in _CAPSEQ_RE.finditer(text)})[:10]
    if caps:
        entities["proper_nouns"] = caps
    return entities


def _detect_time_sensitivity(text: str, intent: str) -> bool:
    t = text.lower()
    if any(tok in t for tok in TIME_TOKENS):
        return True
    if any(domain in t for domain in TIME_DOMAINS):
        return True
    if _DATE_RE.search(text):
        return True
    return intent in ("summarise",) and "latest" in t


def normalize_query(text: str) -> NormalizedQuery:
    cleaned = re.sub(r"\s+", " ", text).strip()
    tokens = re.findall(r"[a-z0-9\u0900-\u097F]+", cleaned.lower())
    intent = _detect_intent(cleaned)
    nq = NormalizedQuery(
        text=cleaned,
        language=_detect_language(cleaned),
        intent=intent,
        entities=_extract_entities(cleaned),
        time_sensitive=_detect_time_sensitivity(cleaned, intent),
        tokens=tokens,
    )
    nq.query_hash = hashlib.sha256(nq.text.lower().encode()).hexdigest()
    return nq
