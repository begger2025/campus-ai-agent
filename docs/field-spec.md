# 爬虫字段说明

与后端 `raw_posts` 表、`crawler/schema.py` 中 `CrawlPost` 一致。

## 字段列表

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | 是 | 平台内唯一 ID，建议 `{platform}_{原始id}` |
| `platform` | string | 是 | `weibo` / `tieba` |
| `title` | string | 是 | 标题或正文前 80 字 |
| `content` | string | 否 | 正文或摘要 |
| `author` | string | 否 | 作者昵称 |
| `publish_time` | string (ISO8601) | 否 | 发布时间，无法解析可为 `null` |
| `url` | string | 否 | 原文链接 |
| `crawl_time` | string (ISO8601) | 是 | 采集时间，脚本自动填充 |

## JSON 文件格式

```json
{
  "meta": {
    "crawl_time": "2026-05-16T12:00:00",
    "keyword": "校园",
    "total": 40,
    "sources": ["weibo", "tieba"]
  },
  "items": [
    {
      "id": "weibo_5123456789",
      "platform": "weibo",
      "title": "标题",
      "content": "正文",
      "author": "作者",
      "publish_time": "2026-05-16T08:00:00",
      "url": "https://m.weibo.cn/detail/5123456789",
      "crawl_time": "2026-05-16T12:00:00"
    }
  ]
}
```

## 平台 ID 规则

- 微博：`weibo_{mid}`
- 贴吧：`tieba_{tid}`
