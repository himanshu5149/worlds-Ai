"""Hard safety gate for model outputs + self-identity anonymization.

Anything that looks like a leaked provider error, a prompt-injection echo, or
an empty/garbage answer is rejected outright — the orchestrator then treats
that model's output as a failure and falls through the chain. Provider/model
self-identification is stripped from the *final* answer so the identity stays
hidden even if a model blurts its name.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field

# --- leaked provider/system errors must never be shown as "the answer" -------
_ERROR_PATTERNS = [
    re.compile(r"\brate\s*limit(?:ed)?\b", re.IGNORECASE),
    re.compile(r"\btoo many requests\b", re.IGNORECASE),
    re.compile(r"\b429\b"),
    re.compile(r"\b(?:insufficient_)?quota\b.*\bexceeded\b", re.IGNORECASE),
    re.compile(r"\binsufficient_quota\b", re.IGNORECASE),
    re.compile(r"\binvalid api key\b", re.IGNORECASE),
    re.compile(r"\bapi key (?:is )?(?:invalid|expired|missing)\b", re.IGNORECASE),
    re.compile(r"\bauthentication (?:error|failed)\b", re.IGNORECASE),
    re.compile(r"\bunauthorized\b.{0,40}\b(?:request|access)\b", re.IGNORECASE),
    re.compile(r"\binternal server error\b", re.IGNORECASE),
    re.compile(r"\bbad gateway\b", re.IGNORECASE),
    re.compile(r"\bservice (?:temporarily )?unavailable\b", re.IGNORECASE),
    re.compile(r"\bconnection (?:error|refused|reset|timed out)\b", re.IGNORECASE),
    re.compile(r"\brequest timed out\b", re.IGNORECASE),
    re.compile(r"\bplease retry (?:again )?later\b", re.IGNORECASE),
    re.compile(r"\ban error occurred while (?:processing|generating)\b", re.IGNORECASE),
    re.compile(r"\bupstream.{0,30}\berror\b", re.IGNORECASE),
]

# --- prompt-injection echoes in the *output* -----------------------------------
_INJECTION_PATTERNS = [
    re.compile(r"\bignore (?:all )?previous instructions\b", re.IGNORECASE),
    re.compile(r"\bdisregard (?:your|all) (?:instructions|guidelines|rules)\b", re.IGNORECASE),
    re.compile(r"\breveal (?:your|the) (?:system )?prompt\b", re.IGNORECASE),
    re.compile(r"\bshow me your (?:system )?prompt\b", re.IGNORECASE),
    re.compile(r"\byou are now (?:dan|freedom|evil)\b", re.IGNORECASE),
    re.compile(r"\bjailbreak\b", re.IGNORECASE),
    re.compile(r"\bas an ai language model,? you must\b", re.IGNORECASE),
    re.compile(r"\[system\s*prompt\s*(?:leak|dump)\]", re.IGNORECASE),
]

# --- self-identification (stripped, not rejected) -------------------------------
# Each entry is (pattern, replacement).
_SELF_ID_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(
            r"\b(?:an? ai(?: assistant| model| chatbot)?\s+"
            r"(?:created|developed|built|made|trained|designed)\s+by\s+"
            r"(?:openai|anthropic|google|xai|mistral(?:\s+ai)?|cohere|deepseek|meta))\b",
            re.IGNORECASE,
        ),
        "",
    ),
    (
        re.compile(
            r"\b(?:an?\s+(?:ai\s+)?(?:assistant|chatbot|model)\s+"
            r"(?:created|developed|built|made)\s+by\s+"
            r"(?:openai|anthropic|google|xai|mistral(?:\s+ai)?|cohere|deepseek|meta))\b",
            re.IGNORECASE,
        ),
        "",
    ),
    (
        re.compile(
            r"\bas (?:chatgpt|gpt-\d[\w.-]*|claude(?:\s+[\w.-]+)?|gemini|bard|"
            r"grok(?:\s+[\w.-]+)?|command\s?r\+?|deepseek(?:\s+[\w.-]+)?)\b",
            re.IGNORECASE,
        ),
        "I",
    ),
    (
        re.compile(
            r"\b(?:i am|i'm)\s+(?:an?\s+)?(?:ai|language model|assistant|chatbot)\s+"
            r"(?:created|developed|built|made|trained|designed)\s+by\s+(openai|anthropic|google|"
            r"xai|mistral(?:\s+ai)?|cohere|deepseek|meta)\b",
            re.IGNORECASE,
        ),
        "",
    ),
    (
        re.compile(
            r"\b(?:i am|i'm)\s+(?:chatgpt|gpt-\d[\w.-]*|claude(?:\s+[\w.-]+)?|gemini|bard|"
            r"grok(?:\s+[\w.-]+)?|command\s?r\+?|deepseek(?:\s+[\w.-]+)?|mistral(?:\s+[\w.-]+)?)\b",
            re.IGNORECASE,
        ),
        "I",
    ),
    (re.compile(r"\bmy name is (?:chatgpt|claude|gemini|grok|bard)\b", re.IGNORECASE), "I"),
    (
        re.compile(r"\b(?:i'm|i am)\s+(?:openai's|anthropic's|google's|xai's|mistral's|cohere's)\s+(?:model|assistant|ai)\b", re.IGNORECASE),
        "I",
    ),
    (
        re.compile(r"\b(?:i was|i'm|i am)\s+(?:created|developed|built|made)\s+by\s+(?:anthropic|openai|google|xai|mistral|cohere)\b", re.IGNORECASE),
        "",
    ),
]

# --- PII leakage in answers: redacted, not rejected ------------------------------
_PII_PATTERNS = [
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<email redacted>"),
    (re.compile(r"\b(?:\+?\d[\d\s().-]{8,}\d)\b"), "<phone redacted>"),
    (re.compile(r"\b\d{13,19}\b"), "<card redacted>"),
]

# --- refusal markers (legitimate but incomplete answers) --------------------------
REFUSAL_MARKERS = [
    "i cannot", "i can't", "i'm not able", "i am not able", "i'm unable",
    "as an ai", "i don't have access", "i do not have access", "i'm sorry, but i",
    "i cannot provide", "i can't provide", "i won't provide",
]


@dataclass
class SafetyVerdict:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    text: str = ""  # sanitized text (self-id stripped, PII redacted)


def _strip_self_identification(text: str) -> str:
    for pattern, replacement in _SELF_ID_PATTERNS:
        text = pattern.sub(replacement, text)
    # Clean punctuation artifacts left by removals (", ." -> ".", double spaces).
    text = re.sub(r"\s*[,;]\s*(?=[.,;!?])", "", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _redact_pii(text: str) -> str:
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _looks_like_base64_blob(text: str) -> bool:
    tokens = re.findall(r"[A-Za-z0-9+/=]{60,}", text)
    for token in tokens:
        try:
            if len(base64.b64decode(token, validate=True)) > 40:
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def check_safety(text: str, *, query: str = "") -> SafetyVerdict:
    reasons: list[str] = []
    stripped = text.strip()
    if not stripped:
        return SafetyVerdict(False, ["empty_response"])
    if len(stripped) < 20:
        return SafetyVerdict(False, ["too_short"])

    for pattern in _INJECTION_PATTERNS:
        if pattern.search(stripped):
            return SafetyVerdict(False, ["injection_echo"])
    if _looks_like_base64_blob(stripped):
        return SafetyVerdict(False, ["encoded_blob"])

    for pattern in _ERROR_PATTERNS:
        if pattern.search(stripped):
            # Provider error responses are terse; a long, substantive answer
            # *about* HTTP errors (e.g. "why do I get 429s?") is legitimate.
            if len(stripped) < 300:
                return SafetyVerdict(False, [f"error_leak:{pattern.pattern[:40]}"])

    clean = _redact_pii(_strip_self_identification(stripped))
    if clean != stripped:
        reasons.append("sanitized")
    return SafetyVerdict(True, reasons, clean)


def is_refusal(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in REFUSAL_MARKERS)
