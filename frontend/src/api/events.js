import http from './http'
import { mockPublishedEvents } from '@/mock/events'

/**
 * 事件详情：GET /api/events/{id}（仅已发布事件）。
 * 兼容 "9" 和 "EVT-9" 两种 ID 写法（后端主键是数字，EVT- 前缀仅用于展示）。
 * 详情页不做 mock 降级——加载失败要让用户看到错误，而不是看到假数据。
 */
export function fetchEventDetail(eventId) {
  const numericId = String(eventId).replace(/^EVT-/i, '')
  return http.get(`/events/${numericId}`)
}

export async function fetchPublishedEvents() {
  try {
    const data = await http.get('/events', {
      params: { status: 'published', page: 1, page_size: 100 },
    })

    if (Array.isArray(data)) {
      return data
    }
    if (Array.isArray(data?.items)) {
      return data.items
    }

    throw new Error('Invalid events API response')
  } catch {
    console.warn('[api/events] backend unavailable, using mock data')
    return [...mockPublishedEvents]
  }
}
