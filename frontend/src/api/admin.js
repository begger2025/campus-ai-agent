import http from './http'

/**
 * 获取后台概览 KPI（管理员专用）
 * GET /api/admin/overview
 */
export function fetchAdminOverview() {
  return http.get('/admin/overview')
}

/**
 * 获取原始采集数据列表（管理员专用）
 * GET /api/admin/raw-posts
 */
export function fetchAdminRawPosts(params = {}) {
  return http.get('/admin/raw-posts', {
    params: {
      page: params.page || 1,
      page_size: params.page_size || 20,
      platform: params.platform || '',
      keyword: params.keyword || '',
      start_date: params.start_date || '',
      end_date: params.end_date || '',
    },
  })
}
