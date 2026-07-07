"""Citation ids for auditable LLM reports (grounded generation).

给压缩后的事件 payload 里每条代表帖编号（p1, p2, …），简报中的论断必须
以 [来源:pN] 标注出处；validate_citations 做零成本的确定性校验（引用了
不存在的编号 = 幻觉引用）。引用映射随响应返回，前端可渲染成跳原帖的角标。
"""

from __future__ import annotations

import re
from typing import Any


# 宽松匹配中文 LLM 常见格式漂移：全角冒号/括号、冒号后空格、大写 P、
# 全角数字、逗号/顿号分隔的合并写法 [来源:p1,p2]。提取后统一归一化。
CITATION_PATTERN = re.compile(
    r"[\[【［]\s*来源\s*[:：]\s*"
    r"([pPｐＰ][0-9０-９]+(?:\s*[,，、]\s*[pPｐＰ][0-9０-９]+)*)"
    r"\s*[\]】］]"
)
_ID_SEPARATOR = re.compile(r"\s*[,，、]\s*")
_FULLWIDTH_TRANS = str.maketrans("０１２３４５６７８９ｐＰ", "0123456789pP")
# 只有 http(s) 链接才随 cite_map 返回给前端（防 javascript: 之类的伪协议）。
_SAFE_URL_PREFIXES = ("http://", "https://")
# 爬取文本里可能混入伪造引用标记（污染 LLM 输出、骗过校验），编号前剥离这些字段。
_NOTE_TEXT_FIELDS = ("title", "content", "desc")

CITATION_INSTRUCTION = (
    "\n引用要求：每个事实性论断的句末必须标注来源，格式为 [来源:pN]，"
    "其中 pN 是数据中代表内容的 cite_id 编号。"
    "只能引用数据围栏内真实存在的编号；无法溯源到具体帖子的内容不要写进报告。"
)


def _extract_citation_ids(text: str) -> list[str]:
    """All cite ids in text (normalized to lowercase ASCII), in order, with repeats."""

    found: list[str] = []
    for match in CITATION_PATTERN.finditer(text or ""):
        for raw_id in _ID_SEPARATOR.split(match.group(1)):
            found.append(raw_id.translate(_FULLWIDTH_TRANS).lower())
    return found


def attach_citation_ids(
    events_payload: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    """Number every representative note; return (tagged copy, cite_id -> source)."""

    cite_map: dict[str, dict[str, str]] = {}
    tagged: list[dict[str, Any]] = []
    counter = 0
    for event in events_payload:
        event_copy = dict(event)
        notes = []
        for note in event.get("representative_notes", []):
            counter += 1
            cite_id = f"p{counter}"
            note_copy = dict(note)
            for field in _NOTE_TEXT_FIELDS:
                if note_copy.get(field):
                    note_copy[field] = CITATION_PATTERN.sub("", str(note_copy[field])).strip()
            note_copy["cite_id"] = cite_id
            notes.append(note_copy)
            url = str(note.get("url") or "")
            cite_map[cite_id] = {
                "title": str(note_copy.get("title") or ""),
                "url": url if url.startswith(_SAFE_URL_PREFIXES) else "",
                # 子项目 app schema 用 event_title，主项目核心 schema 用 title。
                "event_title": str(event.get("event_title") or event.get("title") or ""),
            }
        event_copy["representative_notes"] = notes
        tagged.append(event_copy)
    return tagged, cite_map


def validate_citations(text: str, cite_map: dict[str, Any]) -> dict[str, Any]:
    """Deterministic citation check: occurrences, distinct ids, hallucinated ids."""

    found = _extract_citation_ids(text or "")
    cited: list[str] = []
    for cite_id in found:
        if cite_id not in cited:
            cited.append(cite_id)
    return {
        "cited": cited,
        "unknown": [cite_id for cite_id in cited if cite_id not in cite_map],
        "count": len(found),
    }
