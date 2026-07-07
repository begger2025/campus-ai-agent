"""Prompt-injection defense for untrusted crawled content.

Crawled posts go straight into LLM prompts. A malicious post could embed
instructions like "ignore previous instructions and ...". This module
provides:

1. detect_injection -- find instruction-override phrases in one text.
2. sanitize_text    -- replace those phrases with a visible filter marker and
                       escape <data> fence breakout attempts.
3. guard_payload    -- recursively sanitize every string in a JSON-like
                       payload before it is embedded in a prompt.

Patterns are intentionally conservative: normal campus complaints must never
be touched, so we only match explicit override/leak phrasing.
"""

from __future__ import annotations

import re
from typing import Any


FILTER_MARK = "[已过滤可疑指令]"

INJECTION_PATTERNS: list[re.Pattern[str]] = [
    # 中文：覆盖/无视既有指令
    re.compile(r"(忽略|无视|忘记|抛弃)[^。！？\n]{0,12}(指令|提示词?|规则|设定|约束)"),
    re.compile(r"不要(遵守|理会|执行)[^。！？\n]{0,8}(指令|提示|规则|设定)"),
    re.compile(r"从现在开始[，,]?你(必须|要|是|只能)"),
    re.compile(r"(扮演|假装|重新设定)[^。！？\n]{0,8}(角色|身份|系统|管理员)"),
    re.compile(r"(泄露|输出|打印|告诉我)[^。！？\n]{0,8}(系统提示词?|system ?prompt)", re.IGNORECASE),
    # English: override / leak attempts
    re.compile(r"ignore\s+(all\s+|the\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)", re.IGNORECASE),
    re.compile(r"disregard\s+(the\s+)?(system\s+)?(prompt|instructions?|rules?)", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+)?(previous|your)\s+(instructions?|rules?)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+", re.IGNORECASE),
    re.compile(r"reveal\s+(your\s+)?(system\s+)?prompt", re.IGNORECASE),
    re.compile(r"new\s+instructions?\s*[:：]", re.IGNORECASE),
]

# 防止帖子内容伪造数据围栏提前闭合（fence breakout）。
_FENCE_ESCAPES = [
    (re.compile(r"</\s*data\s*>", re.IGNORECASE), "＜/data＞"),
    (re.compile(r"<\s*data\s*>", re.IGNORECASE), "＜data＞"),
]


def detect_injection(text: str) -> list[str]:
    """Return the suspicious snippets found in text (empty list if clean)."""

    if not text:
        return []
    hits: list[str] = []
    for pattern in INJECTION_PATTERNS:
        hits.extend(match.group(0) for match in pattern.finditer(text))
    return hits


def sanitize_text(text: str) -> str:
    """Replace injection phrases with FILTER_MARK and escape fence breakouts."""

    if not text:
        return text
    sanitized = text
    for pattern in INJECTION_PATTERNS:
        sanitized = pattern.sub(FILTER_MARK, sanitized)
    for pattern, replacement in _FENCE_ESCAPES:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def guard_payload(payload: Any) -> tuple[Any, list[str]]:
    """Recursively sanitize all strings in a JSON-like structure.

    Returns the sanitized copy and the list of suspicious snippets found.
    """

    warnings: list[str] = []
    sanitized = _guard_value(payload, warnings)
    return sanitized, warnings


def _guard_value(value: Any, warnings: list[str]) -> Any:
    if isinstance(value, str):
        warnings.extend(detect_injection(value))
        return sanitize_text(value)
    if isinstance(value, dict):
        return {key: _guard_value(item, warnings) for key, item in value.items()}
    if isinstance(value, list):
        return [_guard_value(item, warnings) for item in value]
    if isinstance(value, tuple):
        return tuple(_guard_value(item, warnings) for item in value)
    return value
