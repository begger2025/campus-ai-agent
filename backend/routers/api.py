from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.database import DATABASE_URL, get_db
from backend.models import RawPost
from backend.schemas import PingData, PostItem, PostListData, ok

router = APIRouter(tags=["api"])


@router.get("/ping")
def ping():
    return ok(
        PingData(
            pong=True,
            timestamp=datetime.utcnow(),
            database=DATABASE_URL.split("///")[-1],
        ).model_dump()
    )


@router.get("/posts")
def list_posts(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    query = db.query(RawPost).order_by(RawPost.publish_time.desc())
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    items = [PostItem.model_validate(row).model_dump() for row in rows]
    return ok(PostListData(items=items, total=total).model_dump())
