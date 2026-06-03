# -*- coding: utf-8 -*-
import argparse
import json
import logging
import re
import sys
from datetime import datetime, time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from store.xhs.xhs_note_assets import normalize_local_image_meta, normalize_xhs_tag_list
from tools import utils


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build LLM-ready datasets from enhanced Xiaohongshu JSON files"
    )
    parser.add_argument("--input-dir", default="output/xhs_enhanced", help="Directory containing enhanced JSON files")
    parser.add_argument("--output-dir", default="output/llm_ready", help="Directory to write output JSONL files")
    parser.add_argument("--source-keyword", default="", help="Only keep records whose source_keyword matches this value")
    parser.add_argument("--start-date", default="", help="Filter publish time >= YYYY-MM-DD")
    parser.add_argument("--end-date", default="", help="Filter publish time <= YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of records to keep after filtering; 0 means no limit")
    parser.add_argument(
        "--mode",
        choices=("text", "multimodal", "all"),
        default="all",
        help="Which dataset outputs to generate",
    )
    parser.add_argument("--require-images", action="store_true", help="Only keep records with valid local images")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    return parser.parse_args()


def configure_logging(verbose: bool) -> None:
    if verbose:
        utils.logger.setLevel(logging.DEBUG)


def ensure_output_dir(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u3000", " ").replace("\t", " ")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
    lines = [line for line in lines if line]
    return "\n".join(lines).strip()


def clean_inline_text(value: Any) -> str:
    return re.sub(r"\s+", " ", clean_text(value)).strip()


def load_enhanced_json(file_path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as ex:
        utils.logger.warning(f"[build_llm_dataset] Failed to load json {file_path.as_posix()}: {ex}")
        return None


def normalize_author(record: Dict[str, Any]) -> Dict[str, str]:
    author_info = record.get("author") or record.get("user") or {}
    if not isinstance(author_info, dict):
        author_info = {}
    return {
        "author_user_id": str(author_info.get("user_id") or record.get("user_id") or "").strip(),
        "author_nickname": clean_inline_text(
            author_info.get("nickname") or record.get("nickname") or author_info.get("name") or ""
        ),
    }


def normalize_tags(record: Dict[str, Any]) -> List[str]:
    tag_source = record.get("tags")
    if tag_source is None:
        tag_source = record.get("tag_list")
    tags = normalize_xhs_tag_list(tag_source)
    return [clean_inline_text(tag) for tag in tags if clean_inline_text(tag)]


def parse_count_value(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)

    text = str(value).strip()
    if not text:
        return None

    normalized = (
        text.replace(",", "")
        .replace("，", "")
        .replace("次赞", "")
        .replace("点赞", "")
        .replace("收藏", "")
        .replace("评论", "")
        .replace("分享", "")
        .replace("阅读", "")
        .replace("浏览", "")
        .replace("播放", "")
        .strip()
    )
    normalized = normalized.rstrip("+").strip()
    if not normalized:
        return None

    unit_multiplier = {
        "亿": 100000000,
        "万": 10000,
        "千": 1000,
        "百": 100,
    }
    match = re.match(r"^(-?\d+(?:\.\d+)?)([亿万千百]?)$", normalized)
    if not match:
        return None

    number_part = float(match.group(1))
    unit = match.group(2)
    multiplier = unit_multiplier.get(unit, 1)
    return int(number_part * multiplier)


def _parse_datetime_text(text: str) -> Optional[datetime]:
    candidate = clean_inline_text(text)
    if not candidate:
        return None

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
        "%Y.%m.%d %H:%M:%S",
        "%Y.%m.%d %H:%M",
        "%Y.%m.%d",
    ):
        try:
            return datetime.strptime(candidate, fmt)
        except ValueError:
            continue

    iso_candidate = candidate.replace("T", " ").replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(iso_candidate, fmt)
        except ValueError:
            continue
    return None


def normalize_publish_time(record: Dict[str, Any]) -> Dict[str, Any]:
    raw_value = record.get("publish_time")
    if raw_value in (None, ""):
        raw_value = record.get("time")

    result = {
        "publish_time_raw": raw_value,
        "publish_time_iso": "",
        "publish_datetime": None,
    }
    if raw_value in (None, ""):
        return result

    if isinstance(raw_value, (int, float)):
        timestamp = float(raw_value)
        if timestamp > 9999999999:
            timestamp /= 1000
        dt = datetime.fromtimestamp(timestamp)
        result["publish_time_iso"] = dt.strftime("%Y-%m-%d %H:%M:%S")
        result["publish_datetime"] = dt
        return result

    raw_text = str(raw_value).strip()
    if raw_text.isdigit():
        timestamp = float(raw_text)
        if timestamp > 9999999999:
            timestamp /= 1000
        dt = datetime.fromtimestamp(timestamp)
        result["publish_time_iso"] = dt.strftime("%Y-%m-%d %H:%M:%S")
        result["publish_datetime"] = dt
        return result

    parsed_dt = _parse_datetime_text(raw_text)
    if parsed_dt is not None:
        result["publish_time_iso"] = parsed_dt.strftime("%Y-%m-%d %H:%M:%S")
        result["publish_datetime"] = parsed_dt
    return result


def normalize_images(record: Dict[str, Any], cwd: Path) -> Dict[str, Any]:
    image_source = record.get("images")
    if image_source is None:
        image_source = record.get("local_image_list")

    normalized_items = normalize_local_image_meta(image_source)
    image_items: List[Dict[str, Any]] = []
    image_local_paths: List[str] = []

    for idx, item in enumerate(normalized_items, start=1):
        raw_local_path = clean_inline_text(item.get("local_path", ""))
        if not raw_local_path:
            continue

        local_path = Path(raw_local_path)
        if not local_path.is_absolute():
            local_path = cwd / local_path
        if not local_path.exists():
            utils.logger.warning(
                f"[build_llm_dataset] Skip missing local image for note {record.get('note_id', '')}: "
                f"{raw_local_path}"
            )
            continue

        output_local_path = local_path.relative_to(cwd).as_posix() if local_path.is_relative_to(cwd) else local_path.as_posix()
        standardized_item = {
            "index": item.get("index") or idx,
            "local_path": output_local_path,
            "download_status": item.get("download_status", "unknown"),
            "original_url": clean_inline_text(item.get("original_url", "")),
            "final_url": clean_inline_text(item.get("final_url", "")),
        }
        image_items.append(standardized_item)
        image_local_paths.append(output_local_path)

    return {
        "image_count": len(image_local_paths),
        "image_local_paths": image_local_paths,
        "image_items": image_items,
        "has_images": bool(image_local_paths),
    }


def build_combined_text(base_record: Dict[str, Any]) -> str:
    lines: List[str] = []
    if base_record.get("title"):
        lines.append(f"标题：{base_record['title']}")
    if base_record.get("desc"):
        lines.append(f"正文：{base_record['desc']}")
    if base_record.get("tags"):
        lines.append(f"标签：{', '.join(base_record['tags'])}")
    if base_record.get("author_nickname") or base_record.get("author_user_id"):
        author_parts = [part for part in (base_record.get("author_nickname"), base_record.get("author_user_id")) if part]
        lines.append(f"作者：{' / '.join(author_parts)}")
    if base_record.get("publish_time_iso"):
        lines.append(f"发布时间：{base_record['publish_time_iso']}")

    stats_fragments: List[str] = []
    if base_record.get("liked_count_raw") not in ("", None):
        stats_fragments.append(f"点赞{base_record['liked_count_raw']}")
    if base_record.get("collected_count_raw") not in ("", None):
        stats_fragments.append(f"收藏{base_record['collected_count_raw']}")
    if base_record.get("comment_count_raw") not in ("", None):
        stats_fragments.append(f"评论{base_record['comment_count_raw']}")
    if base_record.get("share_count_raw") not in ("", None):
        stats_fragments.append(f"分享{base_record['share_count_raw']}")
    if stats_fragments:
        lines.append(f"互动数据：{'，'.join(stats_fragments)}")

    if base_record.get("note_url"):
        lines.append(f"原帖链接：{base_record['note_url']}")

    return "\n".join(lines).strip()


def _build_base_record(record: Dict[str, Any], source_file: Path, cwd: Path) -> Dict[str, Any]:
    author_info = normalize_author(record)
    tags = normalize_tags(record)
    publish_time_info = normalize_publish_time(record)
    image_info = normalize_images(record, cwd)

    stats_source = record.get("stats")
    if not isinstance(stats_source, dict):
        stats_source = record.get("interact_info")
    if not isinstance(stats_source, dict):
        stats_source = {}

    liked_raw = stats_source.get("liked_count", record.get("liked_count", ""))
    collected_raw = stats_source.get("collected_count", record.get("collected_count", ""))
    comment_raw = stats_source.get("comment_count", record.get("comment_count", ""))
    share_raw = stats_source.get("share_count", record.get("share_count", ""))

    base_record = {
        "note_id": str(record.get("note_id") or "").strip(),
        "source_keyword": clean_inline_text(record.get("source_keyword", "")),
        "title": clean_inline_text(record.get("title", "")),
        "desc": clean_text(record.get("desc", "")),
        "author_user_id": author_info["author_user_id"],
        "author_nickname": author_info["author_nickname"],
        "tags": tags,
        "publish_time_raw": publish_time_info["publish_time_raw"],
        "publish_time_iso": publish_time_info["publish_time_iso"],
        "publish_datetime": publish_time_info["publish_datetime"],
        "note_url": clean_inline_text(record.get("note_url", "")),
        "liked_count_raw": liked_raw,
        "liked_count_num": parse_count_value(liked_raw),
        "collected_count_raw": collected_raw,
        "collected_count_num": parse_count_value(collected_raw),
        "comment_count_raw": comment_raw,
        "comment_count_num": parse_count_value(comment_raw),
        "share_count_raw": share_raw,
        "share_count_num": parse_count_value(share_raw),
        "image_count": image_info["image_count"],
        "image_local_paths": image_info["image_local_paths"],
        "image_items": image_info["image_items"],
        "has_images": image_info["has_images"],
        "source_file": source_file.as_posix(),
    }
    base_record["combined_text"] = build_combined_text(base_record)
    return base_record


def build_text_record(record: Dict[str, Any], source_file: Path, cwd: Path) -> Dict[str, Any]:
    base_record = _build_base_record(record, source_file, cwd)
    return {
        "note_id": base_record["note_id"],
        "source_keyword": base_record["source_keyword"],
        "title": base_record["title"],
        "desc": base_record["desc"],
        "combined_text": base_record["combined_text"],
        "author_user_id": base_record["author_user_id"],
        "author_nickname": base_record["author_nickname"],
        "tags": base_record["tags"],
        "publish_time_raw": base_record["publish_time_raw"],
        "publish_time_iso": base_record["publish_time_iso"],
        "note_url": base_record["note_url"],
        "liked_count_raw": base_record["liked_count_raw"],
        "liked_count_num": base_record["liked_count_num"],
        "collected_count_raw": base_record["collected_count_raw"],
        "collected_count_num": base_record["collected_count_num"],
        "comment_count_raw": base_record["comment_count_raw"],
        "comment_count_num": base_record["comment_count_num"],
        "share_count_raw": base_record["share_count_raw"],
        "share_count_num": base_record["share_count_num"],
        "image_count": base_record["image_count"],
        "image_local_paths": base_record["image_local_paths"],
        "has_images": base_record["has_images"],
    }


def build_multimodal_record(text_record: Dict[str, Any], image_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    multimodal_prompt_lines = [
        "请结合以下小红书笔记的文本与图片进行分析。",
        "请重点关注主题、场景、情绪、关键信息、可提取事实以及适合结构化整理的要点。",
        "",
        text_record["combined_text"],
    ]
    return {
        "note_id": text_record["note_id"],
        "source_keyword": text_record["source_keyword"],
        "title": text_record["title"],
        "desc": text_record["desc"],
        "combined_text": text_record["combined_text"],
        "author_user_id": text_record["author_user_id"],
        "author_nickname": text_record["author_nickname"],
        "tags": text_record["tags"],
        "publish_time_iso": text_record["publish_time_iso"],
        "note_url": text_record["note_url"],
        "image_local_paths": text_record["image_local_paths"],
        "image_items": image_items,
        "image_count": text_record["image_count"],
        "has_images": text_record["has_images"],
        "openai_vision_ready": text_record["has_images"],
        "multimodal_user_prompt": "\n".join(multimodal_prompt_lines).strip(),
    }


def build_openai_preview_record(
    text_record: Dict[str, Any],
    *,
    mode: str,
    image_items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if mode == "text_only":
        messages_preview = [
            {
                "role": "system",
                "content": "你是一名内容分析助手。请基于给定的小红书笔记信息做总结、分类、情绪分析和要点提取。",
            },
            {
                "role": "user",
                "content": text_record["combined_text"],
            },
        ]
        return {
            "note_id": text_record["note_id"],
            "mode": "text_only",
            "model_suggestion": "gpt-5.4",
            "input_text": text_record["combined_text"],
            "image_local_paths": text_record["image_local_paths"],
            "messages_preview": messages_preview,
        }

    multimodal_content: List[Dict[str, Any]] = [
        {
            "type": "input_text",
            "text": build_multimodal_record(text_record, image_items)["multimodal_user_prompt"],
        }
    ]
    for path in text_record["image_local_paths"]:
        multimodal_content.append(
            {
                "type": "input_image",
                "image_path": path,
            }
        )

    messages_preview = [
        {
            "role": "system",
            "content": "你是一名图文内容分析助手。请综合文本与图片理解内容，并提炼结构化信息。",
        },
        {
            "role": "user",
            "content": multimodal_content,
        },
    ]
    return {
        "note_id": text_record["note_id"],
        "mode": "multimodal",
        "model_suggestion": "gpt-5.4",
        "input_text": text_record["combined_text"],
        "image_local_paths": text_record["image_local_paths"],
        "messages_preview": messages_preview,
    }


def _parse_date_boundary(date_text: str, *, end_of_day: bool) -> Optional[datetime]:
    if not date_text:
        return None
    parsed_date = datetime.strptime(date_text, "%Y-%m-%d").date()
    return datetime.combine(parsed_date, time.max if end_of_day else time.min)


def _passes_filters(
    text_record: Dict[str, Any],
    args: argparse.Namespace,
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
) -> bool:
    if args.source_keyword and text_record["source_keyword"] != clean_inline_text(args.source_keyword):
        return False

    if args.require_images and not text_record["has_images"]:
        return False

    publish_dt = text_record.get("publish_datetime")
    if (start_dt or end_dt) and publish_dt is None:
        utils.logger.warning(
            f"[build_llm_dataset] Record {text_record['note_id']} has no parseable publish time; "
            "date filter is skipped for this record"
        )
        return True

    if start_dt and publish_dt and publish_dt < start_dt:
        return False
    if end_dt and publish_dt and publish_dt > end_dt:
        return False
    return True


def iter_enhanced_json_files(input_dir: Path) -> Iterable[Path]:
    return sorted(path for path in input_dir.glob("*.json") if path.is_file())


def write_jsonl(file_path: Path, rows: List[Dict[str, Any]]) -> None:
    with file_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_datasets(args: argparse.Namespace) -> Dict[str, Any]:
    cwd = Path.cwd()
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    ensure_output_dir(output_dir)

    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir.as_posix()}")

    start_dt = _parse_date_boundary(args.start_date, end_of_day=False)
    end_dt = _parse_date_boundary(args.end_date, end_of_day=True)

    scanned_count = 0
    success_count = 0
    skipped_count = 0
    with_images_count = 0
    text_rows: List[Dict[str, Any]] = []
    multimodal_rows: List[Dict[str, Any]] = []
    preview_rows: List[Dict[str, Any]] = []

    for file_path in iter_enhanced_json_files(input_dir):
        scanned_count += 1
        record = load_enhanced_json(file_path)
        if not record:
            skipped_count += 1
            continue

        try:
            base_record = _build_base_record(record, file_path, cwd)
            if not _passes_filters(base_record, args, start_dt=start_dt, end_dt=end_dt):
                skipped_count += 1
                continue

            text_record = build_text_record(record, file_path, cwd)
            image_items = base_record["image_items"]
            if text_record["has_images"]:
                with_images_count += 1

            if args.mode in ("text", "all"):
                text_rows.append(text_record)
                preview_rows.append(
                    build_openai_preview_record(text_record, mode="text_only", image_items=image_items)
                )

            if args.mode in ("multimodal", "all"):
                multimodal_record = build_multimodal_record(text_record, image_items)
                multimodal_rows.append(multimodal_record)
                preview_rows.append(
                    build_openai_preview_record(text_record, mode="multimodal", image_items=image_items)
                )

            success_count += 1
            if args.limit > 0 and success_count >= args.limit:
                break
        except Exception as ex:
            skipped_count += 1
            utils.logger.warning(
                f"[build_llm_dataset] Failed to process record from {file_path.as_posix()}: {ex}"
            )

    written_files: List[str] = []
    if args.mode in ("text", "all"):
        text_output = output_dir / "xhs_notes_text.jsonl"
        write_jsonl(text_output, text_rows)
        written_files.append(text_output.as_posix())

    if args.mode in ("multimodal", "all"):
        multimodal_output = output_dir / "xhs_notes_multimodal.jsonl"
        write_jsonl(multimodal_output, multimodal_rows)
        written_files.append(multimodal_output.as_posix())

    preview_output = output_dir / "xhs_openai_requests_preview.jsonl"
    write_jsonl(preview_output, preview_rows)
    written_files.append(preview_output.as_posix())

    return {
        "scanned_count": scanned_count,
        "success_count": success_count,
        "skipped_count": skipped_count,
        "with_images_count": with_images_count,
        "written_files": written_files,
    }


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)
    stats = build_datasets(args)
    utils.logger.info(
        "[build_llm_dataset] Finished. "
        f"scanned={stats['scanned_count']}, "
        f"success={stats['success_count']}, "
        f"skipped={stats['skipped_count']}, "
        f"with_images={stats['with_images_count']}, "
        f"outputs={stats['written_files']}"
    )


if __name__ == "__main__":
    main()
