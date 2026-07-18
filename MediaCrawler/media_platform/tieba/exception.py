# -*- coding: utf-8 -*-
"""贴吧专用异常：让 core 能按类型区分"可重试的访问受阻"与"需人工适配的解析失配"。

此前 client 只抛裸 Exception，core.search 的页级 except 无从辨别瞬时/致命
（对比 ks/zhihu 的 DataFetchError），只能一律 STOP_EXCEPTION。
"""


class TiebaAccessBlockedError(Exception):
    """搜索页数据未加载：疑似风控 / Cookie 过期 / 未完整登录。

    特征（老排障文档 §3.5 实测）：页面含"数据加载失败/安全验证/验证码"类文案，
    或正文根本不含搜索关键词。换号或过验证码后重试即可，属可重试故障。
    """


class TiebaSearchParserMismatchError(Exception):
    """搜索页有帖子卡片但解析结果为 0：DOM 结构又变了，需要适配解析器。

    重试无用——落 run_history 的 stop_reason=parser_mismatch，提示人工修解析器。
    """
