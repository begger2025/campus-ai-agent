# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/xhs/extractor.py
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

import json
import re
from typing import Any, Dict, List, Optional, Tuple

import humps


class XiaoHongShuExtractor:
    STATE_SCRIPT_PATTERNS: Tuple[Tuple[str, str], ...] = (
        ("window.__INITIAL_STATE__", r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>"),
        ("window.__PRELOADED_STATE__", r"window\.__PRELOADED_STATE__\s*=\s*(\{.*?\})\s*</script>"),
        ("window.__INITIAL_PROPS__", r"window\.__INITIAL_PROPS__\s*=\s*(\{.*?\})\s*</script>"),
    )
    LD_JSON_PATTERN = re.compile(
        r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        re.IGNORECASE | re.DOTALL,
    )

    def __init__(self):
        pass

    @staticmethod
    def _replace_js_undefined(value: str) -> str:
        return value.replace(":undefined", ":null").replace("undefined", "null")

    def _load_json_text(self, raw_json_text: str) -> Any:
        normalized_text = self._replace_js_undefined(raw_json_text.strip().rstrip(";"))
        return json.loads(normalized_text, strict=False)

    def extract_state_json_candidates_from_html(self, html: str) -> List[Tuple[str, str]]:
        candidates: List[Tuple[str, str]] = []
        if not html:
            return candidates

        for source_name, pattern in self.STATE_SCRIPT_PATTERNS:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                candidates.append((source_name, match.group(1)))
        return candidates

    def _extract_note_from_known_paths(self, note_id: str, state_data: Any) -> Optional[Dict]:
        if not isinstance(state_data, dict):
            return None

        known_paths = [
            ("note", "note_detail_map", note_id, "note"),
            ("note", "noteDetailMap", note_id, "note"),
            ("note_detail_map", note_id, "note"),
            ("noteDetailMap", note_id, "note"),
        ]
        for path in known_paths:
            current = state_data
            try:
                for part in path:
                    current = current[part]
                if isinstance(current, dict):
                    return current
            except (KeyError, TypeError, IndexError):
                continue
        return None

    def _is_note_candidate(self, candidate: Any, note_id: str) -> bool:
        if not isinstance(candidate, dict):
            return False

        candidate_note_id = candidate.get("note_id") or candidate.get("noteId") or candidate.get("id")
        if candidate_note_id and str(candidate_note_id) != note_id:
            return False

        candidate_keys = set(candidate.keys())
        return bool(
            {"title", "desc", "image_list", "user", "note_id"} & candidate_keys
            or {"title", "desc", "imageList", "user", "noteId"} & candidate_keys
        )

    def _find_note_candidate(self, data: Any, note_id: str) -> Optional[Dict]:
        if isinstance(data, dict):
            if self._is_note_candidate(data, note_id):
                return data
            for value in data.values():
                found = self._find_note_candidate(value, note_id)
                if found:
                    return found
        elif isinstance(data, list):
            for item in data:
                found = self._find_note_candidate(item, note_id)
                if found:
                    return found
        return None

    def _normalize_user(self, user_info: Any) -> Dict[str, Any]:
        if not isinstance(user_info, dict):
            return {}
        normalized_user = humps.decamelize(user_info)
        nickname = (
            normalized_user.get("nickname")
            or normalized_user.get("name")
            or normalized_user.get("user_name")
            or ""
        )
        return {
            "user_id": normalized_user.get("user_id") or normalized_user.get("id") or "",
            "nickname": nickname,
            "avatar": normalized_user.get("avatar") or normalized_user.get("image") or "",
        }

    def _normalize_image_list(self, image_list: Any) -> List[Dict[str, Any]]:
        normalized_images: List[Dict[str, Any]] = []
        if not image_list:
            return normalized_images

        if isinstance(image_list, dict):
            image_list = [image_list]

        if not isinstance(image_list, list):
            return normalized_images

        for image_item in image_list:
            if isinstance(image_item, str):
                image_url = image_item.strip()
                if image_url:
                    normalized_images.append({"url": image_url, "url_default": image_url})
                continue

            if not isinstance(image_item, dict):
                continue

            normalized_item = humps.decamelize(image_item)
            image_url = (
                normalized_item.get("url")
                or normalized_item.get("url_default")
                or normalized_item.get("origin_url")
                or normalized_item.get("image_url")
            )
            if not image_url:
                info_list = normalized_item.get("info_list")
                if isinstance(info_list, list):
                    for info_item in info_list:
                        if not isinstance(info_item, dict):
                            continue
                        image_url = (
                            info_item.get("url")
                            or info_item.get("url_default")
                            or info_item.get("origin_url")
                        )
                        if image_url:
                            break
            if not image_url:
                continue

            normalized_item["url"] = image_url
            normalized_item.setdefault("url_default", image_url)
            normalized_images.append(normalized_item)
        return normalized_images

    def _normalize_tag_list(self, tag_list: Any) -> List[Dict[str, Any]]:
        normalized_tags: List[Dict[str, Any]] = []
        if not tag_list:
            return normalized_tags

        if isinstance(tag_list, str):
            tag_list = [tag_list]
        elif isinstance(tag_list, dict):
            tag_list = [tag_list]

        if not isinstance(tag_list, list):
            return normalized_tags

        for tag_item in tag_list:
            if isinstance(tag_item, str):
                tag_name = tag_item.strip()
                if tag_name:
                    normalized_tags.append({"name": tag_name, "type": "topic"})
                continue
            if not isinstance(tag_item, dict):
                continue
            normalized_item = humps.decamelize(tag_item)
            tag_name = normalized_item.get("name") or normalized_item.get("title")
            if not tag_name:
                continue
            normalized_item["name"] = tag_name
            normalized_item.setdefault("type", "topic")
            normalized_tags.append(normalized_item)
        return normalized_tags

    def _finalize_note_detail(self, note_id: str, note_detail: Dict, *, note_url: str = "") -> Dict:
        normalized_note = humps.decamelize(note_detail)
        if "note_card" in normalized_note and isinstance(normalized_note["note_card"], dict):
            normalized_note = humps.decamelize(normalized_note["note_card"])

        normalized_note["note_id"] = normalized_note.get("note_id") or note_id
        normalized_note.setdefault("type", normalized_note.get("note_type") or "normal")

        desc = normalized_note.get("desc") or normalized_note.get("content") or normalized_note.get("body") or ""
        title = normalized_note.get("title") or ""
        if not title and desc:
            title = desc[:80]

        user_info = normalized_note.get("user") or normalized_note.get("author") or {}
        interact_info = normalized_note.get("interact_info") or normalized_note.get("stats") or {}

        normalized_note["title"] = title
        normalized_note["desc"] = desc
        normalized_note["user"] = self._normalize_user(user_info)
        normalized_note["interact_info"] = humps.decamelize(interact_info) if isinstance(interact_info, dict) else {}
        normalized_note["image_list"] = self._normalize_image_list(
            normalized_note.get("image_list") or normalized_note.get("images")
        )
        normalized_note["tag_list"] = self._normalize_tag_list(
            normalized_note.get("tag_list") or normalized_note.get("tags")
        )
        normalized_note["last_update_time"] = normalized_note.get("last_update_time", 0)
        normalized_note["ip_location"] = normalized_note.get("ip_location", "")
        if note_url:
            normalized_note["note_url"] = note_url
        return normalized_note

    def extract_note_detail_from_state_json(
        self,
        note_id: str,
        raw_json_text: str,
        *,
        note_url: str = "",
    ) -> Optional[Dict]:
        try:
            state_data = self._load_json_text(raw_json_text)
        except Exception:
            return None

        for candidate_root in (state_data, humps.decamelize(state_data)):
            note_detail = self._extract_note_from_known_paths(note_id, candidate_root)
            if note_detail:
                return self._finalize_note_detail(note_id, note_detail, note_url=note_url)

            note_candidate = self._find_note_candidate(candidate_root, note_id)
            if note_candidate:
                return self._finalize_note_detail(note_id, note_candidate, note_url=note_url)
        return None

    def extract_note_detail_from_ld_json(
        self,
        note_id: str,
        html: str,
        *,
        note_url: str = "",
    ) -> Optional[Dict]:
        if not html:
            return None

        for raw_ld_json in self.LD_JSON_PATTERN.findall(html):
            try:
                ld_json = self._load_json_text(raw_ld_json)
            except Exception:
                continue

            json_objects = ld_json if isinstance(ld_json, list) else [ld_json]
            for json_item in json_objects:
                if not isinstance(json_item, dict):
                    continue
                article_type = str(json_item.get("@type") or "").lower()
                if article_type and article_type not in ("article", "newsarticle", "socialmediaposting"):
                    continue

                title = json_item.get("headline") or json_item.get("name") or ""
                desc = json_item.get("description") or ""
                image_value = json_item.get("image") or []
                if isinstance(image_value, str):
                    image_value = [image_value]
                author_info = json_item.get("author") or {}
                if isinstance(author_info, list):
                    author_info = author_info[0] if author_info else {}
                note_detail = {
                    "note_id": note_id,
                    "title": title,
                    "desc": desc,
                    "user": {
                        "nickname": author_info.get("name") if isinstance(author_info, dict) else "",
                        "user_id": "",
                        "avatar": "",
                    },
                    "image_list": [{"url": image_url, "url_default": image_url} for image_url in image_value if image_url],
                    "tag_list": [],
                    "interact_info": {},
                    "note_url": note_url or json_item.get("url") or "",
                }
                finalized_note = self._finalize_note_detail(note_id, note_detail, note_url=note_url)
                if self.is_minimal_note_detail(finalized_note):
                    return finalized_note
        return None

    def build_note_detail_from_dom_snapshot(
        self,
        note_id: str,
        dom_snapshot: Dict[str, Any],
        *,
        note_url: str = "",
    ) -> Optional[Dict]:
        if not isinstance(dom_snapshot, dict):
            return None

        title = dom_snapshot.get("title") or dom_snapshot.get("page_title") or ""
        desc = dom_snapshot.get("desc") or dom_snapshot.get("body_text") or ""
        author_nickname = dom_snapshot.get("author_nickname") or ""
        author_user_id = dom_snapshot.get("author_user_id") or ""
        tags = dom_snapshot.get("tags") or []
        image_urls = dom_snapshot.get("image_urls") or []

        note_detail = {
            "note_id": note_id,
            "type": "normal",
            "title": title,
            "desc": desc,
            "user": {
                "user_id": author_user_id,
                "nickname": author_nickname,
                "avatar": "",
            },
            "image_list": [{"url": image_url, "url_default": image_url} for image_url in image_urls if image_url],
            "tag_list": [{"name": tag_name, "type": "topic"} for tag_name in tags if tag_name],
            "interact_info": {},
            "note_url": note_url,
            "time": dom_snapshot.get("publish_time") or "",
        }
        finalized_note = self._finalize_note_detail(note_id, note_detail, note_url=note_url)
        if self.is_minimal_note_detail(finalized_note):
            return finalized_note
        return None

    def fill_note_detail_from_dom_snapshot(
        self,
        note_detail: Dict,
        dom_snapshot: Dict[str, Any],
        *,
        note_url: str = "",
    ) -> Dict:
        finalized_note = self._finalize_note_detail(
            note_detail.get("note_id") or "",
            note_detail,
            note_url=note_url or note_detail.get("note_url", ""),
        )
        if not isinstance(dom_snapshot, dict):
            return finalized_note

        if not finalized_note.get("title"):
            finalized_note["title"] = dom_snapshot.get("title") or dom_snapshot.get("page_title") or ""
        if not finalized_note.get("desc"):
            finalized_note["desc"] = dom_snapshot.get("desc") or dom_snapshot.get("body_text") or ""
        if not finalized_note.get("image_list"):
            finalized_note["image_list"] = self._normalize_image_list(dom_snapshot.get("image_urls", []))
        if not finalized_note.get("tag_list"):
            finalized_note["tag_list"] = self._normalize_tag_list(dom_snapshot.get("tags", []))

        user_info = finalized_note.get("user") or {}
        if not user_info.get("nickname"):
            user_info["nickname"] = dom_snapshot.get("author_nickname") or ""
        if not user_info.get("user_id"):
            user_info["user_id"] = dom_snapshot.get("author_user_id") or ""
        finalized_note["user"] = user_info
        return finalized_note

    def is_minimal_note_detail(self, note_detail: Optional[Dict]) -> bool:
        if not isinstance(note_detail, dict):
            return False

        note_id = str(note_detail.get("note_id") or "").strip()
        title = str(note_detail.get("title") or "").strip()
        desc = str(note_detail.get("desc") or "").strip()
        user_info = note_detail.get("user") or {}
        image_list = note_detail.get("image_list") or []
        has_author = bool((user_info.get("nickname") if isinstance(user_info, dict) else "") or (user_info.get("user_id") if isinstance(user_info, dict) else ""))
        has_images = bool(image_list)
        has_text = bool(title or desc)
        return bool(note_id and has_text and (has_author or has_images))

    def extract_note_detail_from_html(self, note_id: str, html: str, *, note_url: str = "") -> Optional[Dict]:
        """Extract note details from HTML.

        Extraction order:
        1. Try known state scripts such as window.__INITIAL_STATE__
        2. Try application/ld+json blocks
        """
        for _, state_json_text in self.extract_state_json_candidates_from_html(html):
            note_detail = self.extract_note_detail_from_state_json(note_id, state_json_text, note_url=note_url)
            if note_detail:
                return note_detail

        ld_json_note = self.extract_note_detail_from_ld_json(note_id, html, note_url=note_url)
        if ld_json_note:
            return ld_json_note
        return None

    def extract_creator_info_from_html(self, html: str) -> Optional[Dict]:
        """Extract user information from HTML

        Args:
            html (str): HTML string

        Returns:
            Dict: User information dictionary
        """
        match = re.search(
            r"<script>window.__INITIAL_STATE__=(.+)<\/script>", html, re.M
        )
        if match is None:
            return None
        info = json.loads(match.group(1).replace(":undefined", ":null"), strict=False)
        if info is None:
            return None
        return info.get("user").get("userPageData")
