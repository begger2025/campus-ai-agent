/**
 * api/comments.js — 事件评论区（参与感 V1）
 *
 * 读公开（与事件可见性口径一致），写需登录。后端契约见 backend/routers/comments.py。
 */
import http from './http'

export function fetchEventComments(eventId) {
  return http.get(`/events/${eventId}/comments`)
}

export function postEventComment(eventId, { content, parent_id = null }) {
  return http.post(`/events/${eventId}/comments`, { content, parent_id })
}

export function reportComment(commentId) {
  return http.post(`/comments/${commentId}/report`)
}
