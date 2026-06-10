import http from './http'

/**
 * 获取用户反馈列表（管理员专用）
 * GET /api/admin/feedback
 */
export function fetchAdminFeedback(params = {}) {
  return http.get('/admin/feedback', {
    params: {
      page: params.page || 1,
      page_size: params.page_size || 20,
      status: params.status || '',
    },
  })
}

/**
 * 更新反馈处理状态（管理员专用）
 * PATCH /api/admin/feedback/{feedback_id}/status
 * @param {'handling'|'resolved'|'ignored'} status
 */
export function updateFeedbackStatus(feedbackId, status, handleNote = '') {
  return http.patch(`/admin/feedback/${feedbackId}/status`, {
    status,
    handle_note: handleNote,
  })
}

/**
 * 获取爬虫/同步任务列表（管理员专用）
 * GET /api/admin/crawl-tasks
 */
export function fetchCrawlTasks(params = {}) {
  return http.get('/admin/crawl-tasks', {
    params: {
      page: params.page || 1,
      page_size: params.page_size || 20,
      status: params.status || '',
      platform: params.platform || '',
      task_type: params.task_type || '',
    },
  })
}

/**
 * 获取系统日志（管理员专用）
 * GET /api/admin/system-logs
 */
export function fetchSystemLogs(params = {}) {
  return http.get('/admin/system-logs', {
    params: {
      page: params.page || 1,
      page_size: params.page_size || 20,
      level: params.level || '',
      module: params.module || '',
    },
  })
}

/**
 * 获取管理员操作日志（管理员专用）
 * GET /api/admin/operation-logs
 */
export function fetchOperationLogs(params = {}) {
  return http.get('/admin/operation-logs', {
    params: {
      page: params.page || 1,
      page_size: params.page_size || 20,
      action: params.action || '',
      target_type: params.target_type || '',
    },
  })
}
