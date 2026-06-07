from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "ok"
    data: T | None = None


class PostItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: str
    external_id: str | None = None
    source_table: str = ""
    source_raw_id: str = ""
    source_keyword: str = ""
    title: str
    content: str
    author: str
    publish_time: datetime | None
    url: str
    raw_url: str = ""
    like_count: int = 0
    collect_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    tags_json: str = ""
    images_json: str = ""
    raw_json: str = ""
    crawl_time: datetime | None
    status: str = "active"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PostListData(BaseModel):
    items: list[PostItem]
    total: int
    page: int
    page_size: int


class PingData(BaseModel):
    pong: bool = True
    timestamp: datetime
    database: str


def ok(data: Any = None, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data}
