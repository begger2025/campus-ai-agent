/**
 * api/admin.js — 管理后台接口（全部需要 admin 角色 token）
 *
 * 后端契约见 backend/routers/admin.py 与 admin_events.py，
 * 列表接口统一返回 { items, total, page, page_size }。
 */
import http from './http'

// —— 概览 ——
export function fetchOverview() {
  return http.get('/admin/overview')
}

// —— 事件审核 ——
export function fetchAdminEvents(params = {}) {
  return http.get('/admin/events', { params })
}

export function fetchAdminEventDetail(eventId) {
  return http.get(`/admin/events/${eventId}`)
}

export function updateEventStatus(eventId, { status, review_comment = '' }) {
  return http.patch(`/admin/events/${eventId}/status`, { status, review_comment })
}

// 预审是同步 LLM 调用（最多 20 事件打包一问），中转站延迟波动大（实测 10~190s），
// 远超实例默认 8s——与 evidence.js 的 RUN_TIMEOUT_MS 同一处置：请求级放宽超时。
const PRESCREEN_TIMEOUT_MS = 120_000
// 批量审核最多 100 条逐条写库+双日志，远程 RDS 下也可能超 8s
const BATCH_TIMEOUT_MS = 60_000

// 批量审核：后端逐条走与单条相同的审计路径，返回逐条结果 {results, succeeded, failed}
export function batchUpdateEventStatus({ event_ids, status, review_comment = '' }) {
  return http.post(
    '/admin/events/batch-status',
    { event_ids, status, review_comment },
    { timeout: BATCH_TIMEOUT_MS },
  )
}

// LLM 预审建议：即算即显不落库；未配置模型时返回 {available: false}
export function prescreenEvents(eventIds) {
  return http.post(
    '/admin/events/prescreen',
    { event_ids: eventIds },
    { timeout: PRESCREEN_TIMEOUT_MS },
  )
}

export function fetchEventReviewLogs(eventId, params = {}) {
  return http.get(`/admin/events/${eventId}/review-logs`, { params })
}

// —— 人工事件修正（任何一项都会把事件上锁 curated：再生成管线对它只读） ——
export function renameEvent(eventId, title) {
  return http.patch(`/admin/events/${eventId}`, { title })
}

export function createEvent({ title, post_ids }) {
  return http.post('/admin/events', { title, post_ids })
}

export function deleteEvent(eventId) {
  return http.delete(`/admin/events/${eventId}`)
}

export function mergeEvents(targetId, sourceId) {
  return http.post(`/admin/events/${targetId}/merge`, { source_id: sourceId })
}

export function addEventPost(eventId, processedPostId) {
  return http.post(`/admin/events/${eventId}/posts`, { processed_post_id: processedPostId })
}

export function removeEventPost(eventId, processedPostId) {
  return http.delete(`/admin/events/${eventId}/posts/${processedPostId}`)
}

// —— 数据管理 ——
/**
 * 数据质量管控：把一条无关帖剔除出所有下游（或恢复回来）。
 *
 * postId 是 **processed_post_id**，不是 raw_post.id——剔除标记在 processed_posts 上
 * （下游查的都是那张表），两张表的主键不是同一个。列表接口每行都带 processed_post_id。
 */
export function excludeProcessedPost(postId, { excluded, reason = '' }) {
  return http.patch(`/admin/posts/${postId}/exclude`, { excluded, reason })
}

export function fetchRawPosts(params = {}) {
  return http.get('/admin/raw-posts', { params })
}

// —— 运维中心 ——
export function fetchCrawlTasks(params = {}) {
  return http.get('/admin/crawl-tasks', { params })
}

export function fetchFeedbackList(params = {}) {
  return http.get('/admin/feedback', { params })
}

export function updateFeedbackStatus(feedbackId, { status, handle_note = '' }) {
  return http.patch(`/admin/feedback/${feedbackId}/status`, { status, handle_note })
}

export function fetchSystemLogs(params = {}) {
  return http.get('/admin/system-logs', { params })
}

// —— 用户管理 ——
export function fetchUsers(params = {}) {
  return http.get('/admin/users', { params })
}

export function updateUserStatus(userId, status) {
  return http.patch(`/admin/users/${userId}/status`, { status })
}

export function fetchOperationLogs(params = {}) {
  return http.get('/admin/operation-logs', { params })
}

// —— 智能选题 ——
export function fetchKeywordSuggestions(params = {}) {
  return http.get('/admin/keyword-suggestions', { params })
}
