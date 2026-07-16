"""bge-small-zh embedding wrapper for semantic clustering.

The heavy dependency (sentence-transformers + torch) lives only here and is
imported lazily on first use. When the library is not installed or
EMBEDDING_ENABLED is off, get_embedder() returns None and the analysis
pipeline falls back to rule clustering automatically.

国内网络下载模型：在 backend/.env 写 HF_ENDPOINT=https://hf-mirror.com，
load_dotenv 会注入进程环境，huggingface_hub 自动走镜像。
"""

from __future__ import annotations

from collections.abc import Callable
from importlib.util import find_spec
import logging
import threading

from backend.services.llm_config import EMBEDDING_ENABLED, EMBEDDING_MODEL_NAME


logger = logging.getLogger(__name__)

_find_spec = find_spec
_model = None
# 模型加载实测 26.3 秒（之后每次 embed 只要 0.015 秒）。舆情助手的语义检索在请求路径上
# 用它，而 FastAPI 的同步路由跑在线程池里——两个请求同时撞上冷启动会各加载一次。加锁。
_model_lock = threading.Lock()


def embedding_available() -> bool:
    return bool(EMBEDDING_ENABLED) and _find_spec("sentence_transformers") is not None


def get_embedder() -> Callable[[list[str]], list[list[float]]] | None:
    return embed_texts if embedding_available() else None


def embed_texts(texts: list[str]) -> list[list[float]]:
    model = _load_model()
    # normalize_embeddings=True：归一化后余弦相似度等于点积，聚类侧不再做二次归一。
    vectors = model.encode(list(texts), normalize_embeddings=True)
    return [[float(value) for value in vector] for vector in vectors]


def warm_up() -> None:
    """后台预热模型（应用启动时调），别让第一个提问的用户替所有人付这 26 秒。

    在**后台线程**里跑：同步加载会把 uvicorn 的启动拖慢 26 秒。用户登录、点进聊天、
    打字的这段时间足够模型加载完；万一真的抢在前面，embed 会在锁上等，而不是出错。
    未装 sentence-transformers 时直接返回——语义检索本来就会降级到纯字面。
    """

    if not embedding_available():
        return

    def _warm() -> None:
        try:
            _load_model()
            logger.info("embedding model warmed up: %s", EMBEDDING_MODEL_NAME)
        except Exception as exc:  # 预热失败不该影响服务启动
            logger.warning("embedding warm-up failed (%s); semantic match will degrade", exc)

    threading.Thread(target=_warm, name="embedding-warmup", daemon=True).start()


def _resolve_local_snapshot(probe: Callable[[], object] | None = None) -> str | None:
    """模型缓存完整时返回本地快照目录路径；缺失/异常返回 None。

    为什么要它：按模型名加载时 hub 会为一堆**可选**配置文件逐个发 HEAD 校验
    更新——代理关闭的网络下每个文件 5 次退避重试，26 秒的加载被拖成分钟级
    挂死（2026-07-16 实测：关 Clash 跑 build_post_vectors 卡死在
    adapter_config.json）。从本地目录加载天然零网络请求；不用 HF_HUB_OFFLINE
    环境变量是因为 hub 在 import 时就固化了该标志，事后设置不保证生效。
    """
    try:
        if probe is None:
            from huggingface_hub import snapshot_download

            def probe():
                # local_files_only=True：只查本地缓存，不发任何网络请求
                return snapshot_download(EMBEDDING_MODEL_NAME, local_files_only=True)

        path = probe()
        return str(path) if path else None
    except Exception:
        return None  # 缓存缺失（新机器首跑）→ 回退在线加载，允许首次下载


def _load_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:  # 双检：拿到锁之后别再加载一遍
                from sentence_transformers import SentenceTransformer

                source = _resolve_local_snapshot() or EMBEDDING_MODEL_NAME
                _model = SentenceTransformer(source)
    return _model
