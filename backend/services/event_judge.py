"""LLM 裁决：用户问的**是不是**这件事。

## 它补的是算术的哪个洞

语义匹配（余弦）在真实事件标题上标定出一个**无解的重叠**：

    该命中的最低分 : 0.54   （论文造假 → 中大康某论文调查）
    该拒绝的最高分 : 0.56   （宿舍热水 → 中大宿舍火情通报）

该命中的比该拒绝的分还低——**没有任何阈值能分开它们**。这不是阈值没调好，而是
这件事本身不是"可测量"的：

    余弦回答的是「这两段文本**有多像**」——一个标量。
    用户真正的问题是「我问的**是不是**这件事」——那是判断。

「宿舍热水」和「宿舍火情」字面和语义都很像（同属宿舍后勤），却**不是同一件事**；
「论文造假」和「康某论文调查」字面毫不沾边，却**就是同一件事**。
余弦分不开，因为它没有"是不是"的概念，只有"像不像"。

    **可测量的用算术** —— 「有多像」→ 余弦，12 毫秒，免费
    **需要判断的用 AI** —— 「是不是」→ LLM，0.8 秒

## 模型选型（14 条评测集实测，10 个真实事件标题）

    glm-4-plus    14/14   0.8s   ← 默认选它
    glm-4-air     14/14   1.1s
    glm-4-flashx  13/14   0.6s   ← 便宜的 flash 在「论文造假」上和余弦犯同一个错
    glm-4-flash   13/14   1.3s   ← 同上
    gpt-5.4       14/14   3.6s
    gpt-4o-mini   不可用（InternalServerError）

**省钱省不出判断力**：flash 系列快、便宜，但它们同样分不开"像"和"是"——
在唯一需要判断的那个 case 上，它们和余弦一起翻了车。

## 幻觉防线

模型只被允许从**给定的事件标题列表**里选一个，或者答 null。它返回一个列表里没有的
标题时（编了个不存在的事件），一律当作"都不是"——检索层绝不凭空造出一个事件来。
"""

from __future__ import annotations

from backend.services.llm_client import call_llm, extract_json_object
from backend.services.llm_config import (
    EVENT_JUDGE_API_KEY,
    EVENT_JUDGE_BASE_URL,
    EVENT_JUDGE_MODEL,
)


JUDGE_SYSTEM_PROMPT = """你是校园舆情系统的检索路由。判断用户问的话题**是不是**下面某一个已知事件。

已知事件：
{events}

判断标准是「**是不是同一件事**」，不是「像不像」：
- 「宿舍热水维修」和「宿舍火灾」都属于宿舍后勤，但**不是同一件事** -> null
- 「论文造假」和「康某论文调查」字面毫不沾边，但**就是同一件事** -> 命中

只能从上面的列表里原样选一个标题，或者判定都不是。不要自己造事件。
只输出一个 JSON：{{"event": "事件标题原文" 或 null}}"""


def judge_event_match(keyword: str, titles: list[str]) -> str | None:
    """用户问的 ``keyword`` 是不是 ``titles`` 里的某一件事？是就返回那个标题，否则 None。

    异常一律向上抛：调用方（event_read_model）负责降级——裁决挂了就按余弦的原判走，
    绝不能让一次模型故障弄挂整个对话。
    """

    if not keyword or not titles:
        return None

    block = "\n".join(f"{i + 1}. {title}" for i, title in enumerate(titles))
    result = call_llm(
        [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT.format(events=block)},
            {"role": "user", "content": f"用户问的话题：{keyword}"},
        ],
        temperature=0,
        model=EVENT_JUDGE_MODEL,
        base_url=EVENT_JUDGE_BASE_URL,
        api_key=EVENT_JUDGE_API_KEY,
    )
    if not result.content:
        raise RuntimeError(f"event judge failed: {result.error or 'empty response'}")

    payload = extract_json_object(result.content)
    if not isinstance(payload, dict):
        return None

    event = payload.get("event")
    if not isinstance(event, str):
        return None
    # 幻觉防线：模型只能从给定列表里选。它编了个不存在的标题 -> 当作"都不是"。
    return event if event in titles else None


__all__ = ["JUDGE_SYSTEM_PROMPT", "judge_event_match"]
