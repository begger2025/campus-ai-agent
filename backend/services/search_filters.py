"""LIKE 搜索的通配符转义——用户输入里的 % 和 _ 一律按字面处理。

SQL LIKE 里 `%` 匹配任意串、`_` 匹配任意单字符。把用户搜索词直接拼进
`%{keyword}%` 会让"搜 %"变成"匹配全部"、"搜 _"变成"匹配任意单字"——搜索结果
不符预期（对抗测试实测：搜 '%' 返回全部帖子）。

统一在这里转义 `\ % _`，配合 `.like(pattern, escape="\\")` 使用。
"""

from __future__ import annotations

LIKE_ESCAPE_CHAR = "\\"


def escape_like(keyword: str) -> str:
    """转义 LIKE 元字符，使 keyword 按字面参与匹配。

    顺序要紧：先转义反斜杠自身，再转义 % 和 _，否则会二次转义。
    """
    return (
        keyword.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def like_contains(keyword: str) -> str:
    """构造一个"包含 keyword"的 LIKE 模式串（已转义）。

    用法：column.like(like_contains(kw), escape=LIKE_ESCAPE_CHAR)
    """
    return f"%{escape_like(keyword)}%"
