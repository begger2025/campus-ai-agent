# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tools/topic_scope.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#
# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

"""爬取主题限定的纯函数工具（中山大学校园舆情）。

查询侧：搜索关键词自动附加主题限定词；结果侧：文本命中主题相关词表才保留。
设计：主项目 docs/superpowers/specs/2026-07-10-topic-scope-design.md
"""

from __future__ import annotations

from typing import Any, Iterable, List, Optional


def _normalized_terms(relevance_terms: Optional[Iterable[str]]) -> List[str]:
    return [str(term).strip().lower() for term in (relevance_terms or []) if str(term).strip()]


def compose_topic_keyword(
    keyword: Any,
    qualifier: Optional[str],
    relevance_terms: Optional[Iterable[str]] = None,
) -> str:
    """给搜索关键词附加主题限定词；关键词已含任一相关词（或限定词本身）时原样返回。"""

    keyword = str(keyword or "").strip()
    qualifier = str(qualifier or "").strip()
    if not keyword or not qualifier:
        return keyword
    lowered = keyword.lower()
    terms = _normalized_terms(relevance_terms)
    if qualifier.lower() not in terms:
        terms.append(qualifier.lower())
    if any(term in lowered for term in terms):
        return keyword
    return f"{qualifier} {keyword}"


def matches_topic(texts: Iterable[Any], relevance_terms: Optional[Iterable[str]]) -> bool:
    """任一文本命中任一相关词即视为主题相关；词表为空时全部保留。"""

    terms = _normalized_terms(relevance_terms)
    if not terms:
        return True
    for text in texts:
        lowered = str(text or "").strip().lower()
        if not lowered:
            continue
        if any(term in lowered for term in terms):
            return True
    return False


def is_marketing_noise(
    texts: Iterable[Any],
    negative_terms: Optional[Iterable[str]],
    rescue_terms: Optional[Iterable[str]] = None,
) -> bool:
    """任一文本命中任一负面词 且 所有文本均未命中任何救回词 → 营销噪声。

    救回词（投诉/维权/避雷等）优先：投诉这些机构本身是真舆情，不过滤；
    负面词表为空时直通。大小写不敏感子串匹配。
    """

    negatives = _normalized_terms(negative_terms)
    if not negatives:
        return False
    rescues = _normalized_terms(rescue_terms)
    hit_negative = False
    for text in texts or []:
        lowered = str(text or "").strip().lower()
        if not lowered:
            continue
        if any(term in lowered for term in rescues):
            return False
        if any(term in lowered for term in negatives):
            hit_negative = True
    return hit_negative
