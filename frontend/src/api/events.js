/**
 * api/events.js — 舆情事件相关接口
 * 对应后端 GET /events?status=published (待后端实现)
 * 当前使用 mock 数据降级
 */
import axios from 'axios'
import { mockPublishedEvents } from '@/mock/events'

const http = axios.create({
  baseURL: '/',
  timeout: 5000,
})

/**
 * 获取已发布的事件列表
 * @returns {Promise<Array>}
 */
export async function fetchPublishedEvents() {
  try {
    const resp = await http.get('/events', { params: { status: 'published' } })
    const { data } = resp
    if (data?.code === 0 && Array.isArray(data?.data)) {
      return data.data
    }
    if (Array.isArray(data)) {
      return data
    }
    throw new Error('接口返回格式异常')
  } catch {
    // 后端未就绪时降级到 mock 数据
    console.warn('[api/events] 后端不可用，使用 mock 数据')
    return [...mockPublishedEvents]
  }
}
