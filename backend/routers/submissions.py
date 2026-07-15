"""用户投稿端点（参与感 V2）：登录投稿 + 图片上传 + 管理员前置审核。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.admin_models import User
from backend.database import get_db
from backend.models import UserSubmission
from backend.schemas import ok
from backend.services.auth_service import get_current_user, require_admin
from backend.services.log_service import write_admin_operation
from backend.services.submission_service import (
    MAX_IMAGE_BYTES,
    SubmissionError,
    create_submission,
    review_submission,
    save_upload,
    submission_item,
)

router = APIRouter(tags=["submissions"])


def _require_login(current_user) -> User:
    if current_user is None:
        raise HTTPException(status_code=401, detail="login required")
    return current_user


@router.post("/submissions/uploads")
async def upload_submission_image(
    file: UploadFile,
    current_user: User = Depends(get_current_user),
):
    _require_login(current_user)
    data = await file.read(MAX_IMAGE_BYTES + 1)  # 多读 1 字节：恰好超限也要被抓到
    try:
        path = save_upload(file.filename or "", data)
    except SubmissionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return ok({"path": path})


class SubmissionBody(BaseModel):
    title: str
    content: str
    images: list[str] = []
    suggested_event_id: int | None = None


@router.post("/submissions")
def create_user_submission(
    payload: SubmissionBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = _require_login(current_user)
    try:
        submission = create_submission(
            db,
            user_id=int(user.id),
            username=str(user.username or ""),
            title=payload.title,
            content=payload.content,
            images=payload.images,
            suggested_event_id=payload.suggested_event_id,
        )
    except SubmissionError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    db.commit()
    db.refresh(submission)
    return ok(submission_item(submission))


@router.get("/submissions/mine")
def list_my_submissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = _require_login(current_user)
    rows = (
        db.query(UserSubmission)
        .filter(UserSubmission.user_id == int(user.id))
        .order_by(UserSubmission.id.desc())
        .limit(50)
        .all()
    )
    return ok({"items": [submission_item(row) for row in rows], "total": len(rows)})


@router.get("/admin/submissions")
def list_admin_submissions(
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
    status: str = Query("pending"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    query = db.query(UserSubmission)
    if status != "all":
        query = query.filter(UserSubmission.status == status)
    query = query.order_by(UserSubmission.id.asc())  # 先来先审
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return ok({"items": [submission_item(row) for row in rows], "total": total, "page": page})


class SubmissionReviewPatch(BaseModel):
    status: str  # approved / rejected
    review_comment: str = ""


@router.patch("/admin/submissions/{submission_id}")
def review_user_submission(
    submission_id: int,
    payload: SubmissionReviewPatch,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    if payload.status not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="invalid status")
    submission = db.query(UserSubmission).filter(UserSubmission.id == submission_id).first()
    if submission is None:
        raise HTTPException(status_code=404, detail="submission not found")

    actor = admin_user.username if isinstance(admin_user, User) else "admin"
    before = {"status": submission.status}
    try:
        review_submission(
            db, submission,
            approve=payload.status == "approved",
            comment=payload.review_comment,
            actor=actor,
        )
    except SubmissionError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    write_admin_operation(
        db,
        admin_user_id=str(admin_user.id) if isinstance(admin_user, User) else "admin",
        action=f"submission_{payload.status}",
        target_type="user_submission",
        target_id=str(submission.id),
        before=before,
        after={"status": submission.status, "raw_post_id": submission.raw_post_id},
    )
    db.commit()
    db.refresh(submission)
    return ok(submission_item(submission))
