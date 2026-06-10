import http from './http'

/**
 * 获取后台事件列表（管理员专用）
 * GET /api/admin/events
 */
export function fetchAdminEvents(params = {}) {
  return http.get('/admin/events', {
    params: {
      status: params.status || 'all',
      keyword: params.keyword || '',
      risk_level: params.risk_level || '',
      page: params.page || 1,
      page_size: params.page_size || 20,
    },
  })
}

/**
 * 获取后台事件详情（管理员专用）
 * GET /api/admin/events/{event_id}
 */
export function fetchAdminEventDetail(eventId) {
  return http.get(`/admin/events/${eventId}`)
}

/**
 * 修改事件审核状态（管理员专用）
 * PATCH /api/admin/events/{event_id}/status
 * @param {number} eventId - 整数 raw_id
 * @param {'draft'|'published'|'rejected'|'archived'} status
 * @param {string} reviewComment
 */
export function updateAdminEventStatus(eventId, status, reviewComment = '') {
  return http.patch(`/admin/events/${eventId}/status`, {
    status,
    review_comment: reviewComment,
  })
}

/**
 * 获取事件审核日志（管理员专用）
 * GET /api/admin/events/{event_id}/review-logs
 */
export function fetchEventReviewLogs(eventId, params = {}) {
  return http.get(`/admin/events/${eventId}/review-logs`, {
    params: {
      page: params.page || 1,
      page_size: params.page_size || 20,
    },
  })
}
