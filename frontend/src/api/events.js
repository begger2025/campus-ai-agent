/**
 * api/events.js — 舆情事件相关接口
 * 对应后端 GET /api/events?status=published (待后端实现)
 * 当前使用 mock 数据降级
 */
import http from '@/api/http'
import { mockPublishedEvents } from '@/mock/events'

/**
 * 获取已发布的事件列表
 * @returns {Promise<Array>}
 */
export async function fetchPublishedEvents() {
  try {
    const data = await http.get('/events', { params: { status: 'published' } })
    if (Array.isArray(data)) {
      return data
    }
    if (Array.isArray(data?.items)) {
      return data.items
    }
    throw new Error('接口返回格式异常')
  } catch {
    console.warn('[api/events] 后端不可用，使用 mock 数据')
    return [...mockPublishedEvents]
  }
}
