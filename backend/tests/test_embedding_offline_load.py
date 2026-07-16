"""embedding 模型加载：本地缓存命中时必须走本地快照路径，零网络请求。

## 缺陷（2026-07-16 用户实测）

按模型名加载时，huggingface_hub 会为一堆**可选**配置文件（adapter_config/
processor_config/...）逐个发 HEAD 校验更新。平时代理在，这些请求秒回；
跑爬虫时关了 Clash + 清了代理，每个文件 5 次退避重试，26 秒的加载被拖成
分钟级挂死（build_post_vectors 卡死在 adapter_config.json 上）。

修法不玩 HF_HUB_OFFLINE 环境变量的时序戏法（hub 在 import 时就固化了该
标志，事后设置不保证生效），而是：缓存完整 → 解析出本地快照目录路径、
从路径加载（目录加载天然不触网）；缓存缺失（新机器首跑）→ 回退模型名，
保持在线允许首次下载。
"""

from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

from backend.services import embedding


class ResolveLocalSnapshotTests(unittest.TestCase):
    def test_returns_path_when_cache_is_complete(self) -> None:
        path = embedding._resolve_local_snapshot(probe=lambda: "C:/hf/models--BAAI--bge/snap/abc")

        self.assertEqual(path, "C:/hf/models--BAAI--bge/snap/abc")

    def test_returns_none_when_cache_is_missing(self) -> None:
        def missing():
            raise FileNotFoundError("not cached")

        self.assertIsNone(embedding._resolve_local_snapshot(probe=missing))

    def test_returns_none_when_probe_yields_empty(self) -> None:
        self.assertIsNone(embedding._resolve_local_snapshot(probe=lambda: ""))


class LoadModelSourceTests(unittest.TestCase):
    """_load_model 的取材顺序：本地快照优先，缺失才回退模型名（允许联网下载）。"""

    def _load_with(self, snapshot: str | None) -> str:
        captured: dict[str, str] = {}

        class FakeModel:
            def __init__(self, source: str) -> None:
                captured["source"] = source

        fake_module = types.ModuleType("sentence_transformers")
        fake_module.SentenceTransformer = FakeModel

        with (
            mock.patch.dict(sys.modules, {"sentence_transformers": fake_module}),
            mock.patch.object(embedding, "_resolve_local_snapshot", return_value=snapshot),
            mock.patch.object(embedding, "_model", None),
        ):
            embedding._load_model()
        return captured["source"]

    def test_prefers_local_snapshot_path(self) -> None:
        self.assertEqual(self._load_with("C:/hf/snap"), "C:/hf/snap")

    def test_falls_back_to_model_name_for_first_download(self) -> None:
        self.assertEqual(self._load_with(None), embedding.EMBEDDING_MODEL_NAME)


if __name__ == "__main__":
    unittest.main()
