"""Citation ids for auditable LLM reports (grounded generation).

给压缩后的事件 payload 编号：每条代表帖 p1, p2, …；**每个事件 e1, e2, …**。
简报中的论断必须以 [来源:pN] / [来源:eN] 标注出处；validate_citations 做零成本的
确定性校验（引用了不存在的编号 = 幻觉引用）。引用映射随响应返回，前端可渲染成
跳原帖的角标。

## 为什么事件也要编号（两级引用）

只给帖子编号时，简报里最重要的一批论断——风险等级、热度、条数、时间范围、
事件状态——是**事件级字段**，没有任何合法的引用方式。模型被夹在中间：不标，
确定性校验报「零引用」；硬标 pN，critic 逐条核对帖子内容又报「来源不符」。
实测一份简报被报 8 条 issue，全是这个形状——不是模型错了，是我们没给它出口。
事件级结论标 eN，帖子内容标 pN，生成/校验/审校三方口径才对得上。
"""

from __future__ import annotations

import re
from typing import Any


# 宽松匹配中文 LLM 常见格式漂移：全角冒号/括号、冒号后空格、大写 P/E、
# 全角数字、逗号/顿号分隔的合并写法 [来源:p1,p2]。提取后统一归一化。
CITATION_PATTERN = re.compile(
    r"[\[【［]\s*来源\s*[:：]\s*"
    r"([pPeEｐＰｅＥ][0-9０-９]+(?:\s*[,，、]\s*[pPeEｐＰｅＥ][0-9０-９]+)*)"
    r"\s*[\]】］]"
)
_ID_SEPARATOR = re.compile(r"\s*[,，、]\s*")
_FULLWIDTH_TRANS = str.maketrans("０１２３４５６７８９ｐＰｅＥ", "0123456789pPeE")
# 只有 http(s) 链接才随 cite_map 返回给前端（防 javascript: 之类的伪协议）。
_SAFE_URL_PREFIXES = ("http://", "https://")
# 爬取文本里可能混入伪造引用标记（污染 LLM 输出、骗过校验），编号前剥离这些字段。
_NOTE_TEXT_FIELDS = ("title", "content", "desc")
# 事件标题/摘要虽是 LLM 精修产物，但精修的原料同样是爬取文本——一并剥离。
_EVENT_TEXT_FIELDS = ("title", "summary")

CITATION_INSTRUCTION = (
    "\n引用要求：每个事实性论断的句末必须标注来源。"
    "转述某条帖子的内容时，标注该帖的 cite_id（格式 [来源:pN]）；"
    "引用事件级的聚合结论（风险等级、热度、内容条数、时间范围、事件状态等字段）时，"
    "标注该事件的 cite_id（格式 [来源:eN]）。"
    "只能引用数据围栏内真实存在的编号；无法溯源到具体帖子或事件字段的内容不要写进报告。"
)

# 问答意图的软版本：报告体强制逐句标注（上面那条），聊天体只要求"提到了就标"——
# 不逐句强制、不跑审校，别把对话逼回工作汇报腔。回答里的引用有两个用途：
# 用户可以点角标溯源；后端据此判断"这个回答实际用到了哪些事件"（弹出跟着引用走）。
CITATION_HINT = (
    "\n引用标注：转述某条帖子的内容时，在句末标注该帖的 cite_id（格式 [来源:pN]）；"
    "引用某个事件的聚合结论（风险等级、热度、条数等）时，标注该事件的 cite_id（格式 [来源:eN]）。"
    "只标注数据围栏内真实存在的编号；纯对话性的句子无需标注。"
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
    for event_index, event in enumerate(events_payload, start=1):
        event_copy = dict(event)
        for field in _EVENT_TEXT_FIELDS:
            if event_copy.get(field):
                event_copy[field] = CITATION_PATTERN.sub("", str(event_copy[field])).strip()
        # 事件自己的编号：事件级论断（风险等级/热度/条数/时间范围）标 [来源:eN]
        event_cite = f"e{event_index}"
        event_copy["cite_id"] = event_cite
        event_title = str(event_copy.get("event_title") or event_copy.get("title") or "")
        cite_map[event_cite] = {"title": event_title, "url": "", "event_title": event_title}
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
