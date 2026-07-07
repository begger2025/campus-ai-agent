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

from backend.services.llm_config import EMBEDDING_ENABLED, EMBEDDING_MODEL_NAME


_find_spec = find_spec
_model = None


def embedding_available() -> bool:
    return bool(EMBEDDING_ENABLED) and _find_spec("sentence_transformers") is not None


def get_embedder() -> Callable[[list[str]], list[list[float]]] | None:
    return embed_texts if embedding_available() else None


def embed_texts(texts: list[str]) -> list[list[float]]:
    model = _load_model()
    # normalize_embeddings=True：归一化后余弦相似度等于点积，聚类侧不再做二次归一。
    vectors = model.encode(list(texts), normalize_embeddings=True)
    return [[float(value) for value in vector] for vector in vectors]


def _load_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model
