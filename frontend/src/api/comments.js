/**
 * api/comments.js — 事件评论区（参与感 V1）
 *
 * 读公开（与事件可见性口径一致），写需登录。后端契约见 backend/routers/comments.py。
 */
import http from './http'

// 后端路径参数是纯数字主键；页面路由却是 "EVT-80" 这种展示 ID。
// 不剥前缀的话 FastAPI 解析 int 直接 422（实测：评论读写双双失败，
// 读取失败还被静默吞掉，空评论区其实是加载失败）。与 fetchEventDetail 同口径。
function numericEventId(eventId) {
  return String(eventId).replace(/^EVT-/i, '')
}

export function fetchEventComments(eventId) {
  return http.get(`/events/${numericEventId(eventId)}/comments`)
}

export function postEventComment(eventId, { content, parent_id = null }) {
  return http.post(`/events/${numericEventId(eventId)}/comments`, { content, parent_id })
}

export function reportComment(commentId) {
  return http.post(`/comments/${commentId}/report`)
}
