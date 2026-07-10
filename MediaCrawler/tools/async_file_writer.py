# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tools/async_file_writer.py
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

import asyncio
import csv
import json
import os
import pathlib
from typing import Dict, List, Optional
import aiofiles
import config
from tools.utils import utils
from tools.words import AsyncWordCloudGenerator


class _DedupGuard:
    """进程内去重：同一 (platform, crawler_type, item_type, id) 只允许写入一次。

    为什么用类级共享状态而不是实例级：store 工厂 create_store() 对每一个
    note/comment 都会新建一个 store（进而新建 AsyncFileWriter，或取到 Excel 单例）。
    若 _seen 挂在实例上，csv/json/jsonl 每写一条就是一个全新的空 guard，去重永远
    失效（早期实现只有 Excel 因为走单例才碰巧生效）。改成类级 dict 后，同一进程内
    所有实例共享去重状态，各存储后端行为一致，且与"一个爬取进程 = 一次 run"对齐。

    键里带上 platform + crawler_type，避免不同平台 / 不同爬取类型之间串味
    （例如 xhs 的 note_id 不该挡住 weibo 的同名 id）。

    id 提取优先级由 item_type 决定：评论项（"comments"）同时带着自己的
    comment_id 和所属帖子的 note_id，若先取 note_id 会把同一帖子下的所有评论
    误判成重复而漏写；因此评论优先取 comment_id，其余（主要是 "contents"）
    优先取 note_id。两个字段都取不到时不去重，直接放行——避免误伤没有这两个
    字段的数据（比如 creators）。

    只做进程内、单次运行范围的去重；进程退出即清空。跨进程/跨文件去重不做
    （需全文件扫描，代价不划算），设计文档"范围外"已注明。
    """

    # 类级共享：键 = (platform, crawler_type, item_type, id)，进程生命周期
    _seen: set = set()

    def __init__(self, platform: str = "", crawler_type: str = "") -> None:
        self._platform = platform
        self._crawler_type = crawler_type

    @classmethod
    def reset(cls) -> None:
        """清空全进程去重状态。生产环境无需调用（进程天然隔离一次 run），
        主要供测试在用例之间还原这份跨实例共享的状态。"""
        cls._seen.clear()

    @staticmethod
    def _extract_id(item_type: str, item: Dict) -> Optional[object]:
        candidates = ("comment_id", "note_id") if item_type == "comments" else ("note_id", "comment_id")
        for field_name in candidates:
            value = item.get(field_name)
            if value not in (None, ""):
                return value
        return None

    def should_write(self, item_type: str, item: Dict) -> bool:
        """True = 应当写入（首次出现，或没有可用的 id 字段无法判断）；
        False = 本次进程运行内已经写过同一键，应当跳过。"""
        item_id = self._extract_id(item_type, item)
        if item_id is None:
            return True
        key = (self._platform, self._crawler_type, item_type, item_id)
        if key in _DedupGuard._seen:
            return False
        _DedupGuard._seen.add(key)
        return True


class AsyncFileWriter:
    def __init__(self, platform: str, crawler_type: str):
        self.lock = asyncio.Lock()
        self.platform = platform
        self.crawler_type = crawler_type
        self.wordcloud_generator = AsyncWordCloudGenerator() if config.ENABLE_GET_WORDCLOUD else None
        self._dedup_guard = _DedupGuard(platform, crawler_type)

    def _get_file_path(self, file_type: str, item_type: str) -> str:
        if config.SAVE_DATA_PATH:
            base_path = f"{config.SAVE_DATA_PATH}/{self.platform}/{file_type}"
        else:
            base_path = f"data/{self.platform}/{file_type}"
        pathlib.Path(base_path).mkdir(parents=True, exist_ok=True)
        file_name = f"{self.crawler_type}_{item_type}_{utils.get_current_date()}.{file_type}"
        return f"{base_path}/{file_name}"

    async def write_to_csv(self, item: Dict, item_type: str):
        if not self._dedup_guard.should_write(item_type, item):
            utils.logger.info(f"[AsyncFileWriter.write_to_csv] Skip duplicate {item_type} item in this run")
            return
        file_path = self._get_file_path('csv', item_type)
        async with self.lock:
            file_exists = os.path.exists(file_path)
            async with aiofiles.open(file_path, 'a', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=item.keys())
                if not file_exists or await f.tell() == 0:
                    await writer.writeheader()
                await writer.writerow(item)

    async def write_to_jsonl(self, item: Dict, item_type: str):
        if not self._dedup_guard.should_write(item_type, item):
            utils.logger.info(f"[AsyncFileWriter.write_to_jsonl] Skip duplicate {item_type} item in this run")
            return
        file_path = self._get_file_path('jsonl', item_type)
        async with self.lock:
            async with aiofiles.open(file_path, 'a', encoding='utf-8') as f:
                await f.write(json.dumps(item, ensure_ascii=False) + '\n')

    async def write_single_item_to_json(self, item: Dict, item_type: str):
        if not self._dedup_guard.should_write(item_type, item):
            utils.logger.info(f"[AsyncFileWriter.write_single_item_to_json] Skip duplicate {item_type} item in this run")
            return
        file_path = self._get_file_path('json', item_type)
        async with self.lock:
            existing_data = []
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                    try:
                        content = await f.read()
                        if content:
                            existing_data = json.loads(content)
                        if not isinstance(existing_data, list):
                            existing_data = [existing_data]
                    except json.JSONDecodeError:
                        existing_data = []

            existing_data.append(item)

            async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(existing_data, ensure_ascii=False, indent=4))

    async def generate_wordcloud_from_comments(self):
        """
        Generate wordcloud from comments data
        Only works when ENABLE_GET_WORDCLOUD and ENABLE_GET_COMMENTS are True
        """
        if not config.ENABLE_GET_WORDCLOUD or not config.ENABLE_GET_COMMENTS:
            return

        if not self.wordcloud_generator:
            return

        try:
            # Read comments from JSON or JSONL file
            comments_data = []
            jsonl_file_path = self._get_file_path('jsonl', 'comments')
            json_file_path = self._get_file_path('json', 'comments')

            if os.path.exists(jsonl_file_path) and os.path.getsize(jsonl_file_path) > 0:
                async with aiofiles.open(jsonl_file_path, 'r', encoding='utf-8') as f:
                    async for line in f:
                        line = line.strip()
                        if line:
                            try:
                                comments_data.append(json.loads(line))
                            except json.JSONDecodeError:
                                continue
            elif os.path.exists(json_file_path) and os.path.getsize(json_file_path) > 0:
                async with aiofiles.open(json_file_path, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    if content:
                        comments_data = json.loads(content)
                        if not isinstance(comments_data, list):
                            comments_data = [comments_data]

            if not comments_data:
                utils.logger.info(f"[AsyncFileWriter.generate_wordcloud_from_comments] No comments data found")
                return

            # Filter comments data to only include 'content' field
            # Handle different comment data structures across platforms
            filtered_data = []
            for comment in comments_data:
                if isinstance(comment, dict):
                    # Try different possible content field names
                    content_text = comment.get('content') or comment.get('comment_text') or comment.get('text') or ''
                    if content_text:
                        filtered_data.append({'content': content_text})

            if not filtered_data:
                utils.logger.info(f"[AsyncFileWriter.generate_wordcloud_from_comments] No valid comment content found")
                return

            # Generate wordcloud
            if config.SAVE_DATA_PATH:
                words_base_path = f"{config.SAVE_DATA_PATH}/{self.platform}/words"
            else:
                words_base_path = f"data/{self.platform}/words"
            pathlib.Path(words_base_path).mkdir(parents=True, exist_ok=True)
            words_file_prefix = f"{words_base_path}/{self.crawler_type}_comments_{utils.get_current_date()}"

            utils.logger.info(f"[AsyncFileWriter.generate_wordcloud_from_comments] Generating wordcloud from {len(filtered_data)} comments")
            await self.wordcloud_generator.generate_word_frequency_and_cloud(filtered_data, words_file_prefix)
            utils.logger.info(f"[AsyncFileWriter.generate_wordcloud_from_comments] Wordcloud generated successfully at {words_file_prefix}")

        except Exception as e:
            utils.logger.error(f"[AsyncFileWriter.generate_wordcloud_from_comments] Error generating wordcloud: {e}")
