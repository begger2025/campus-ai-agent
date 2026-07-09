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

export function fetchEventReviewLogs(eventId, params = {}) {
  return http.get(`/admin/events/${eventId}/review-logs`, { params })
}

// —— 数据管理 ——
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
