import http from './http'

/**
 * 事件详情：GET /api/events/{id}（仅已发布事件）。
 * 兼容 "9" 和 "EVT-9" 两种 ID 写法（后端主键是数字，EVT- 前缀仅用于展示）。
 */
export function fetchEventDetail(eventId) {
  const numericId = String(eventId).replace(/^EVT-/i, '')
  return http.get(`/events/${numericId}`)
}

// 后端冷启动窗口：闲置后第一个请求要重建到远程 RDS 的连接，容易撞上 8s 超时。
// 网络层失败（没有任何响应）时静候片刻重试一次——重试是诚实的容错。
const RETRY_DELAY_MS = 1500

export async function fetchPublishedEvents() {
  // 加载失败就抛错让页面报错，**绝不降级到 mock 假数据**。此前这里 catch 一切
  // 错误后静默返回 8 条第一周的演示事件，叠加顶栏写死的「真实接口」徽标，
  // 用户第一屏看到的是一版煞有介事的假事件（静默错误答案，最坏的 bug 类型）。
  try {
    return normalizeEventsResponse(await requestPublishedEvents())
  } catch (error) {
    if (error.response) throw error // 后端明确拒绝（4xx/5xx），重试无意义
    await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS))
    return normalizeEventsResponse(await requestPublishedEvents())
  }
}

function requestPublishedEvents() {
  return http.get('/events', {
    params: { status: 'published', page: 1, page_size: 100 },
  })
}

function normalizeEventsResponse(data) {
  if (Array.isArray(data)) return data
  if (Array.isArray(data?.items)) return data.items
  throw new Error('事件接口返回格式异常')
}
