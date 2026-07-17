"""用户投稿的业务规则（参与感 V2）：投稿是线索，审核通过才进数据管线。

与评论的关键区别：评论是对已发布结论的讨论（后置管控），投稿是**第一方发布
的新内容主张**——有诽谤/虚假信息风险，必须**前置审核**。通过后写
raw_posts(platform='campus')，与爬取数据同等待遇走既有管线（process → 聚类
→ 检索），不发明任何新的事件生成路径。

图片安全三道闸：扩展名白名单 + 魔数嗅探（防改后缀）+ UUID 重命名落
uploads/submissions/（防路径穿越）；库里只存相对路径。大小上限 5MB。
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models import RawPost, UserSubmission
from backend.services.prompt_guard import sanitize_text


ROOT = Path(__file__).resolve().parent.parent.parent
UPLOADS_DIR = ROOT / "uploads" / "submissions"

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGES_PER_SUBMISSION = 3
MAX_TITLE_CHARS = 100
MAX_CONTENT_CHARS = 2000
SUBMIT_COOLDOWN_SECONDS = 60.0  # 投稿比评论重，冷却也更长

# 扩展名 -> 魔数前缀。嗅探防"把 exe 改名成 jpg"：内容说了算，后缀只是参考。
_MAGIC = {
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".webp": (b"RIFF",),  # RIFF....WEBP，下面再核第 8-12 字节
}
_SAFE_RELATIVE = re.compile(r"^uploads/submissions/[0-9]{6}/[a-f0-9]{32}\.(jpg|jpeg|png|webp)$")

_last_submit_at: dict[int, float] = {}
_rate_lock = threading.Lock()


class SubmissionError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def reset_submission_rate_limit() -> None:
    with _rate_lock:
        _last_submit_at.clear()


def _check_rate_limit(user_id: int) -> None:
    now = time.monotonic()
    with _rate_lock:
        last = _last_submit_at.get(user_id)
        if last is not None and now - last < SUBMIT_COOLDOWN_SECONDS:
            raise SubmissionError("投稿太频繁了，稍后再试", status_code=429)
        _last_submit_at[user_id] = now


def save_upload(filename: str, data: bytes) -> str:
    """校验并落盘一张图片；返回库里存的相对路径（uploads/submissions/YYYYMM/<uuid>.<ext>）。"""

    suffix = Path(filename or "").suffix.lower()
    if suffix not in _MAGIC:
        raise SubmissionError("仅支持 jpg / png / webp 图片")
    if len(data) > MAX_IMAGE_BYTES:
        raise SubmissionError("图片超过 5MB 上限")
    if not data or not any(data.startswith(magic) for magic in _MAGIC[suffix]):
        raise SubmissionError("文件内容与图片格式不符")  # 改后缀的非图片文件
    if suffix == ".webp" and data[8:12] != b"WEBP":
        raise SubmissionError("文件内容与图片格式不符")

    folder = UPLOADS_DIR / datetime.utcnow().strftime("%Y%m")
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{suffix}"  # UUID 重命名：原始文件名绝不落盘（防路径穿越/编码把戏）
    (folder / name).write_bytes(data)
    return f"uploads/submissions/{folder.name}/{name}"


def _validate_image_paths(paths: list[str]) -> list[str]:
    """投稿引用的图片路径必须是本系统上传产物（格式+落盘双重校验）。"""

    clean: list[str] = []
    for raw in paths or []:
        path = str(raw or "").strip().replace("\\", "/")
        if not _SAFE_RELATIVE.match(path):
            raise SubmissionError("非法的图片路径")
        if not (ROOT / path).is_file():
            raise SubmissionError("图片不存在，请重新上传")
        if path not in clean:
            clean.append(path)
    if len(clean) > MAX_IMAGES_PER_SUBMISSION:
        raise SubmissionError(f"每次投稿最多 {MAX_IMAGES_PER_SUBMISSION} 张图片")
    return clean


def create_submission(
    db: Session,
    *,
    user_id: int,
    username: str,
    title: str,
    content: str,
    images: list[str],
    suggested_event_id: int | None,
) -> UserSubmission:
    clean_title = sanitize_text((title or "").strip())
    clean_content = sanitize_text((content or "").strip())
    if not clean_title:
        raise SubmissionError("标题不能为空")
    if len(clean_title) > MAX_TITLE_CHARS:
        raise SubmissionError(f"标题最长 {MAX_TITLE_CHARS} 字")
    if not clean_content:
        raise SubmissionError("正文不能为空——图片是证据附件，LLM 分析吃的是文字描述")
    if len(clean_content) > MAX_CONTENT_CHARS:
        raise SubmissionError(f"正文最长 {MAX_CONTENT_CHARS} 字")
    image_paths = _validate_image_paths(images)
    _check_rate_limit(user_id)

    submission = UserSubmission(
        user_id=user_id,
        username=username or f"用户{user_id}",
        title=clean_title,
        content=clean_content,
        images_json=json.dumps(image_paths, ensure_ascii=False),
        suggested_event_id=suggested_event_id,
    )
    db.add(submission)
    db.flush()
    return submission


def review_submission(
    db: Session, submission: UserSubmission, *, approve: bool, comment: str, actor: str
) -> UserSubmission:
    """通过 → 写 raw_posts(platform='campus')；驳回必填理由。只审一次。"""

    if submission.status != "pending":
        raise SubmissionError("该投稿已审核过", status_code=409)
    comment = (comment or "").strip()
    if not approve and not comment:
        raise SubmissionError("驳回必须填写理由——投稿人有权知道为什么")

    if approve:
        raw = RawPost(
            platform="campus",  # 第三个数据入口：站内投稿，与爬取数据同等待遇
            external_id=f"sub:{submission.id}",  # (platform, external_id) 唯一约束 = 重复审批幂等挡板
            source_table="user_submissions",
            source_raw_id=str(submission.id),
            title=submission.title,
            content=submission.content,
            author=submission.username,
            publish_time=submission.created_at,  # 投稿时间就是发布时间（时效轴要用真实时间）
            images_json=submission.images_json or "",
            crawl_time=datetime.utcnow(),
        )
        db.add(raw)
        try:
            db.flush()
        except IntegrityError as exc:
            # 并发审批同一投稿：状态守卫在并发下拦不住，靠唯一约束兜底。
            # 裸抛 IntegrityError 会变 500，翻成 409 交给路由回滚（幂等，数据不重复）。
            raise SubmissionError("该投稿正在被处理或已审核过", status_code=409) from exc
        submission.raw_post_id = raw.id

    submission.status = "approved" if approve else "rejected"
    submission.review_comment = comment
    submission.reviewed_by = actor
    submission.reviewed_at = datetime.utcnow()
    return submission


def submission_item(submission: UserSubmission) -> dict:
    try:
        images = json.loads(submission.images_json or "[]")
    except ValueError:
        images = []
    return {
        "id": submission.id,
        "user_id": submission.user_id,
        "username": submission.username,
        "title": submission.title,
        "content": submission.content,
        "images": images,
        "suggested_event_id": submission.suggested_event_id,
        "status": submission.status,
        "review_comment": submission.review_comment,
        "reviewed_by": submission.reviewed_by,
        "raw_post_id": submission.raw_post_id,
        "created_at": submission.created_at.isoformat() if submission.created_at else "",
    }
