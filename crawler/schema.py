"""爬虫输出字段定义，与后端 raw_posts 及 docs/field-spec.md 一致。"""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class CrawlPost(BaseModel):
    id: str = Field(..., description="平台内唯一 ID，如 weibo_5123456789")
    platform: str = Field(..., description="平台标识：weibo / tieba")
    title: str = ""
    content: str = ""
    author: str = ""
    publish_time: datetime | None = None
    url: str = ""
    crawl_time: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

    def to_dict(self) -> dict[str, Any]:
        d = self.model_dump()
        for key in ("publish_time", "crawl_time"):
            if d[key] is not None:
                d[key] = d[key].isoformat()
        return d
