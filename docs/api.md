# API 文档

基础地址：`http://127.0.0.1:9000`

统一响应格式：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

`code != 0` 表示错误（后续扩展）。

---

## GET /ping

健康探测，确认服务与数据库配置。

**响应 data 示例：**

```json
{
  "pong": true,
  "timestamp": "2026-05-16T12:00:00",
  "database": "data/campus.db"
}
```

---

## GET /posts

获取帖子列表（来自 `raw_posts` 表）。

**查询参数：**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| page | int | 1 | 页码 |
| page_size | int | 20 | 每页条数，最大 100 |

**响应 data 示例：**

```json
{
  "items": [
    {
      "id": 1,
      "platform": "weibo",
      "title": "学校调整课间休息时间引发讨论",
      "content": "...",
      "author": "校园观察",
      "publish_time": "2026-05-16T06:00:00",
      "url": "https://example.com/post/1",
      "crawl_time": "2026-05-16T12:00:00"
    }
  ],
  "total": 3
}
```

---

## GET /health

简单存活检查（无统一包装）。

```json
{"status": "ok"}
```
