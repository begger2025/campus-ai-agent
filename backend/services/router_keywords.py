"""路由话题词表刷新：语料的播种关键词 → intent_router 的动态词表。

播种关键词就是语料的话题词表（「宿舍搬迁」「食堂涨价」……），每爬一轮自动
长出新词——比手写 KNOWN_KEYWORDS 及时，也比从事件标题分词干净（标题是
LLM 精修的整句，不是检索词）。

intent_router 在 sync 白名单里必须保持可移植，所以查库的活在这里做，
结果通过 set_dynamic_keywords() 注入。app 启动时刷一次（见 backend/main.py）；
爬取入库后重启即生效，不重启也只是少了新词的抢答，不影响正确性
（失败方向：词不在表里 → 交给 LLM，多付 4 秒，绝不误答）。
"""

from __future__ import annotations

from backend.models import ProcessedPost
from backend.services.intent_router import _ALL_INTENT_SIGNALS, set_dynamic_keywords


# 单字太泛（「水」会命中一切），超长的多半是搜索串不是话题词。
MIN_KEYWORD_LEN = 2
MAX_KEYWORD_LEN = 12

# 主题限定词：它是每个搜索词的公共前缀，不是话题（老数据存的是「中山大学 X」组合形）。
_QUALIFIER = "中山大学"


def refresh_router_keywords(db) -> list[str]:
    """从 processed_posts 刷出话题词并注入路由；返回注入的词表。

    失败/空结果都**不清**已注入的词表——降级不降配：库抖动时上一次的词表
    仍然有效，最坏也只是没收进新词。
    """

    try:
        rows = (
            db.query(ProcessedPost.source_keyword)
            .filter(ProcessedPost.excluded.is_(False))  # 剔除切断所有下游，包括这里
            .distinct()
            .all()
        )
    except Exception:
        return []

    words: list[str] = []
    for (raw,) in rows:
        word = str(raw or "").strip()
        if word.startswith(_QUALIFIER):  # 「中山大学 宿舍搬迁」→「宿舍搬迁」
            word = word[len(_QUALIFIER):].strip()
        if not (MIN_KEYWORD_LEN <= len(word) <= MAX_KEYWORD_LEN):
            continue
        # 含意图信号的词（「风险监测」含「风险」）不收：话题词会先被消解，
        # 意图判定就少了一票——宁可漏收（多付 4 秒），不误判。
        if any(signal in word for signal in _ALL_INTENT_SIGNALS):
            continue
        if word not in words:
            words.append(word)

    if words:
        set_dynamic_keywords(words)
    return words
