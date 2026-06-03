import re
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, Optional

from tools.time_util import get_current_timestamp


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _normalize_timestamp_ms(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        numeric = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None

    if numeric <= 0:
        return None
    if numeric >= 10**12:
        return numeric
    if numeric >= 10**9:
        return numeric * 1000
    return None


def _build_publish_fields(raw_text: str, publish_dt: Optional[datetime], source: str) -> Dict[str, Any]:
    result = {
        "publish_time_raw": raw_text or "",
        "publish_timestamp_ms": None,
        "publish_date": None,
        "publish_year": None,
        "publish_month": None,
        "publish_day": None,
        "publish_time_source": source,
    }
    if publish_dt is None:
        return result

    timestamp_ms = int(publish_dt.timestamp() * 1000)
    result.update(
        {
            "publish_timestamp_ms": timestamp_ms,
            "publish_date": publish_dt.strftime("%Y-%m-%d"),
            "publish_year": publish_dt.year,
            "publish_month": publish_dt.month,
            "publish_day": publish_dt.day,
        }
    )
    return result


def _parse_publish_time_text(raw_text: str, crawl_dt: datetime) -> Dict[str, Any]:
    normalized_text = _clean_text(raw_text)
    if not normalized_text:
        return _build_publish_fields("", None, "none")

    timestamp_ms = _normalize_timestamp_ms(normalized_text)
    if timestamp_ms is not None:
        publish_dt = datetime.fromtimestamp(timestamp_ms / 1000)
        return _build_publish_fields(normalized_text, publish_dt, "detail")

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ):
        try:
            publish_dt = datetime.strptime(normalized_text, fmt)
            return _build_publish_fields(normalized_text, publish_dt, "detail")
        except ValueError:
            continue

    month_day_match = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})", normalized_text)
    if month_day_match:
        month = int(month_day_match.group(1))
        day = int(month_day_match.group(2))
        year = crawl_dt.year
        try:
            publish_dt = datetime(year, month, day)
        except ValueError:
            return _build_publish_fields(normalized_text, None, "detail_raw_only")
        if publish_dt.date() > crawl_dt.date():
            publish_dt = datetime(year - 1, month, day)
        return _build_publish_fields(normalized_text, publish_dt, "detail")

    relative_text = normalized_text.replace(" ", "")
    if relative_text == "昨天":
        return _build_publish_fields(normalized_text, crawl_dt - timedelta(days=1), "detail")
    if relative_text == "前天":
        return _build_publish_fields(normalized_text, crawl_dt - timedelta(days=2), "detail")
    if relative_text in {"刚刚", "今天"}:
        return _build_publish_fields(normalized_text, crawl_dt, "detail")

    relative_patterns = (
        (r"(\d+)天前", "days"),
        (r"(\d+)小时前", "hours"),
        (r"(\d+)分钟前", "minutes"),
    )
    for pattern, unit in relative_patterns:
        match = re.fullmatch(pattern, relative_text)
        if not match:
            continue
        amount = int(match.group(1))
        if unit == "days":
            publish_dt = crawl_dt - timedelta(days=amount)
        elif unit == "hours":
            publish_dt = crawl_dt - timedelta(hours=amount)
        else:
            publish_dt = crawl_dt - timedelta(minutes=amount)
        return _build_publish_fields(normalized_text, publish_dt, "detail")

    return _build_publish_fields(normalized_text, None, "detail_raw_only")


def extract_xhs_search_publish_time_text(search_item: Dict[str, Any]) -> str:
    if not isinstance(search_item, dict):
        return ""

    candidates = search_item.get("corner_tag_info") or search_item.get("cornerTagInfo") or []
    if isinstance(candidates, dict):
        candidates = [candidates]

    if isinstance(candidates, list):
        for item in candidates:
            if not isinstance(item, dict):
                continue
            if _clean_text(item.get("type")) == "publish_time":
                return _clean_text(item.get("text"))

    return ""


def _iter_detail_publish_candidates(note_item: Dict[str, Any]) -> Iterable[Any]:
    candidate_keys = (
        "publish_timestamp_ms",
        "publish_time",
        "time",
        "create_time",
        "publish_time_raw",
    )
    for key in candidate_keys:
        value = note_item.get(key)
        if value not in (None, ""):
            yield value

    note_card = note_item.get("note_card")
    if isinstance(note_card, dict):
        for key in candidate_keys:
            value = note_card.get(key)
            if value not in (None, ""):
                yield value


def resolve_xhs_note_publish_time(note_item: Dict[str, Any], crawl_ts_ms: Optional[int] = None) -> Dict[str, Any]:
    crawl_ts_ms = _normalize_timestamp_ms(crawl_ts_ms) or int(get_current_timestamp())
    crawl_dt = datetime.fromtimestamp(crawl_ts_ms / 1000)

    first_detail_raw = ""
    for candidate in _iter_detail_publish_candidates(note_item):
        raw_text = _clean_text(candidate)
        if raw_text and not first_detail_raw:
            first_detail_raw = raw_text

        normalized = _parse_publish_time_text(raw_text or candidate, crawl_dt)
        if normalized.get("publish_timestamp_ms") is not None or normalized.get("publish_date"):
            normalized["publish_time_source"] = "detail"
            return normalized

    search_publish_time_raw = _clean_text(
        note_item.get("_search_publish_time_raw") or extract_xhs_search_publish_time_text(note_item)
    )
    if search_publish_time_raw:
        normalized = _parse_publish_time_text(search_publish_time_raw, crawl_dt)
        normalized["publish_time_source"] = (
            "search_result" if normalized.get("publish_timestamp_ms") is not None or normalized.get("publish_date")
            else "search_result_raw_only"
        )
        return normalized

    if first_detail_raw:
        return _build_publish_fields(first_detail_raw, None, "detail_raw_only")
    return _build_publish_fields("", None, "none")
