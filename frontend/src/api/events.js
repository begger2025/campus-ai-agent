import http from './http'

/**
 * 获取已发布事件列表（公开接口，无需 token）
 * GET /api/events?page=1&page_size=20
 * @returns {{ items: [], total: number, page: number, page_size: number }}
 */
export function fetchPublishedEvents(params = {}) {
  return http.get('/events', {
    params: {
      page: params.page || 1,
      page_size: params.page_size || 20,
    },
  })
}

/**
 * 获取已发布事件详情（公开接口，无需 token）
 * GET /api/events/{event_id}
 * @param {number} eventId - 整数 raw_id
 */
export function fetchPublicEventDetail(eventId) {
  return http.get(`/events/${eventId}`)
}
