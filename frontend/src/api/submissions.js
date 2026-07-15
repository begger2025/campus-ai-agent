/**
 * api/submissions.js — 用户投稿（参与感 V2）
 *
 * 投稿是线索：前置审核，通过后进数据管线（raw_posts platform=campus）。
 * 后端契约见 backend/routers/submissions.py。
 */
import http from './http'

export function uploadSubmissionImage(file) {
  const form = new FormData()
  form.append('file', file)
  return http.post('/submissions/uploads', form)
}

export function createSubmission({ title, content, images = [], suggested_event_id = null }) {
  return http.post('/submissions', { title, content, images, suggested_event_id })
}

export function fetchMySubmissions() {
  return http.get('/submissions/mine')
}

export function fetchAdminSubmissions(params = {}) {
  return http.get('/admin/submissions', { params })
}

export function reviewSubmission(id, { status, review_comment = '' }) {
  return http.patch(`/admin/submissions/${id}`, { status, review_comment })
}
