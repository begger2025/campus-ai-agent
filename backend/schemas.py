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
    title: str
    content: str
    author: str
    publish_time: datetime | None
    url: str
    crawl_time: datetime | None


class PostListData(BaseModel):
    items: list[PostItem]
    total: int
    page: int = 1
    page_size: int = 20


class PingData(BaseModel):
    pong: bool = True
    timestamp: datetime
    database: str


def ok(data: Any = None, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data}
