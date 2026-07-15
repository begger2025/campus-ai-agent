"""联网证据检索：GLM 独立检索接口 → ReAct 工具的观察值（站外信息）。

复用证据采集链路实测钉死的契约（backend/services/evidence/provider_adapters.py）：
POST <base>/web_search，body {"search_engine", "search_query"}，响应顶层
search_result[]（link 来自搜索引擎索引而非模型生成——伪造来源 URL 结构上不可能）。

与证据采集页的分工：那边是管理员触发、人工核验、审核后入库的**正式链路**；
这里是聊天里的**即时补充**——结果只进当轮回答（带「未经入库审核」标注），
不写任何表。要成为库内证据，仍然走证据采集页的三闸门。

护栏（联网是本项目最大的发散面）：
  标注    结果自带 source_notice，工具描述要求回答转述并列出来源；
  注入    网页内容过 prompt_guard 再进观察值；
  降级    key 未配置 → available=False（调用方不注册工具）；HTTP 失败 → 错误字典。
限次在调用方（opinion_chat_service：每次对话一次）。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from backend.services.evidence.provider_adapters import (
    DEFAULT_GLM_SEARCH_ENGINE,
    glm_search_query,
    glm_search_url,
)
from backend.services.prompt_guard import guard_payload


logger = logging.getLogger(__name__)

SOURCE_NOTICE = "站外信息（联网检索，未经入库审核）"
MAX_RESULTS = 5
CONTENT_CHARS = 200
TIMEOUT_SECONDS = 20.0


def _api_key() -> str:
    return (os.getenv("EVIDENCE_GLM_API_KEY") or "").strip()


def _search_url() -> str:
    return glm_search_url(os.getenv("EVIDENCE_GLM_BASE_URL"))


def web_search_available() -> bool:
    if (os.getenv("WEB_EVIDENCE_ENABLED") or "true").lower() in ("0", "false", "no"):
        return False
    if not _api_key():
        return False
    try:
        _search_url()
    except ValueError:
        return False
    return True


def _post_search(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    """真正的 HTTP 调用，拆出来供测试打桩。trust_env=False：Windows 上 httpx 会读
    注册表系统代理（Clash），清环境变量无效——证据链路踩过的坑（verification.py）。"""

    import httpx

    with httpx.Client(trust_env=False, timeout=TIMEOUT_SECONDS) as client:
        response = client.post(url, headers=headers, json=body)
        response.raise_for_status()
        return response.json()


def search_web(query: str, *, max_results: int = MAX_RESULTS) -> dict[str, Any]:
    """联网检索公开网页。返回观察值字典，绝不抛异常。"""

    query = (query or "").strip()
    if not query or not web_search_available():
        return {"source_notice": SOURCE_NOTICE, "results": [], "error": "联网检索不可用"}
    body = {
        "search_engine": (os.getenv("EVIDENCE_GLM_SEARCH_ENGINE") or DEFAULT_GLM_SEARCH_ENGINE).strip(),
        "search_query": glm_search_query(query),  # 自动补校名限定，防搜到台湾的国立中山大学
    }
    try:
        payload = _post_search(
            _search_url(), {"Authorization": f"Bearer {_api_key()}"}, body
        )
    except Exception as exc:
        logger.warning("web search failed (%s); answer degrades to corpus-only", type(exc).__name__)
        return {"source_notice": SOURCE_NOTICE, "results": [], "error": f"联网检索失败（{type(exc).__name__}）"}

    results = []
    for item in payload.get("search_result") or []:
        link = str(item.get("link") or "").strip()
        if not link.startswith(("http://", "https://")):
            continue  # 没有来源 URL 的条目做不了证据
        results.append(
            {
                "title": str(item.get("title") or ""),
                "link": link,
                "media": str(item.get("media") or ""),
                "publish_date": str(item.get("publish_date") or ""),
                "content": str(item.get("content") or "")[:CONTENT_CHARS],
            }
        )
        if len(results) >= max_results:
            break
    # 网页内容是不可信文本：注入语句在进 ReAct 观察值之前过滤掉
    safe, _warnings = guard_payload({"source_notice": SOURCE_NOTICE, "results": results, "error": ""})
    return safe
