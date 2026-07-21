"""Strict Chinese language consistency for citizen-facing bot replies.

Detects English / mixed IT-helpdesk residue (legacy Rasa Helpdesk templates)
and replaces with a fixed Chinese fallback. Applied at Orchestrator and Rasa
proxy exits so no unauthorised English reaches the frontend.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Fixed Chinese fallback when a reply fails the language check
LANGUAGE_FALLBACK_MESSAGE = (
    "我主要提供政策咨询、办事指南、投诉建议、公共事务求助和工单进度查询。"
    "请用中文描述您的需求，例如：咨询某项政策、提交投诉建议，或查询工单进度。"
)

# Known English Helpdesk / ServiceNow residue that must never reach citizens
FORBIDDEN_ENGLISH_PHRASES = (
    "I can help you open a service request ticket",
    "Open an incident",
    "Help me reset my password",
    "I'm having a issue with my email",
    "I'm having an issue with my email",
    "What's the status of the ticket I opened",
    "What is your email address",
    "I am a bot, powered by Rasa",
    "I'm a bot",
    "Could not connect to ServiceNow",
    "ServiceNow error",
    "Problem resetting password",
    "Problem with email",
    "Input help for more info",
    "What else can I help you with",
    "Alright, I have cancelled the incident",
    "What is the priority of this issue",
    "What is the problem description",
    "Would you like to use the last email",
    "It looks like you want to be transferred",
    "Since you haven't configured a host",
)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z]{3,}")
# Allowlisted short Latin tokens (ticket ids, brands, technical codes)
_ALLOW_LATIN = re.compile(
    r"\b(QT\d{12,16}|PDF|API|SLA|RAG|LLM|DeepSeek|HTTP|HTTPS|OK|ID)\b",
    re.IGNORECASE,
)


def contains_forbidden_english(text: str) -> bool:
    lowered = (text or "").lower()
    return any(phrase.lower() in lowered for phrase in FORBIDDEN_ENGLISH_PHRASES)


def is_chinese_dominant(text: str) -> bool:
    """Return True if text is acceptably Chinese for citizen-facing UI."""
    if not text or not text.strip():
        return True
    if contains_forbidden_english(text):
        return False

    # Strip allowlisted Latin tokens before measuring
    scrubbed = _ALLOW_LATIN.sub("", text)
    cjk_count = len(_CJK_RE.findall(scrubbed))
    latin_words = _LATIN_WORD_RE.findall(scrubbed)

    if not latin_words:
        return True
    # Pure English paragraph (no CJK, several Latin words)
    if cjk_count == 0 and len(latin_words) >= 3:
        return False
    # Mostly English mixed with a few Chinese chars
    if len(latin_words) >= 5 and cjk_count < len(latin_words):
        return False
    return True


def ensure_chinese_response(
    text: str,
    *,
    fallback: str = LANGUAGE_FALLBACK_MESSAGE,
    source: str = "unknown",
) -> str:
    """Replace non-Chinese / forbidden English replies with Chinese fallback."""
    if is_chinese_dominant(text):
        return text
    logger.warning(
        "language_guard replaced non-Chinese reply source=%s preview=%r",
        source,
        (text or "")[:120],
    )
    return fallback


def sanitize_rasa_messages(messages: list[dict], *, source: str = "rasa") -> list[dict]:
    """Apply language guard to each Rasa webhook message's text field."""
    out: list[dict] = []
    for msg in messages:
        item = dict(msg)
        if "text" in item and item["text"]:
            item["text"] = ensure_chinese_response(item["text"], source=source)
        out.append(item)
    return out
