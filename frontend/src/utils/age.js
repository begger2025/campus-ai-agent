/**
 * 事件年龄的展示口径（诚实地告诉用户"这件事有多老"）。
 *
 * 后端 GET /api/events 现在带 `event_time`（事件代表时间 = 成员帖发布时间的中位数）和
 * `age_days`（相对请求时刻的年龄，读时现算）。排序已经按时效性衰减把陈旧事件压下去了，
 * 但**光压下去不够**：一个五年前的事件只要还在列表里，用户就有权一眼看出它是五年前的，
 * 而不是被默默当成"当前舆情"。
 *
 * 后端的 `updated_at` 是**这行数据什么时候被分析写库**，不是事件什么时候发生的——
 * 拿它当"发布时间"展示，正是让「中大学生诽谤被开除」（2021-06-18）看起来像今天新闻的原因。
 */

// 超过这个天数就打上"陈旧"标记（≈4 个半衰期，时效权重已跌到 6%）。
export const STALE_AGE_DAYS = 90

export function formatAge(ageDays) {
  if (ageDays === null || ageDays === undefined || Number.isNaN(Number(ageDays))) {
    return '时间未知'
  }
  const days = Number(ageDays)
  if (days < 0) return '刚刚'
  if (days < 1) return '今天'
  if (days < 30) return `${Math.round(days)} 天前`
  if (days < 365) return `${(days / 30.4).toFixed(0)} 个月前`
  return `${(days / 365.25).toFixed(1)} 年前`
}

export function isStale(ageDays) {
  return ageDays !== null && ageDays !== undefined && Number(ageDays) >= STALE_AGE_DAYS
}

/** 事件代表时间的可读写法（"2021-06-18"）；没有就返回空串。 */
export function formatEventTime(eventTime) {
  const text = String(eventTime || '').trim()
  if (!text) return ''
  return text.slice(0, 10)
}

/**
 * 事件代表时间，**日期 + 时分**（"2026-05-24 18:25"）。
 *
 * 直接切字符串，不过 `new Date()`：后端给的是带时区的 ISO 串，交给 Date 再格式化会被
 * 转成浏览器本地时区，同一条事件在不同人的电脑上显示不同的时间。这里要展示的是
 * **事件的代表时间**（成员帖发布时间的中位数），它已经是后端算好的一个事实，不该被
 * 时区再动一次手。
 *
 * 没有时间戳的老数据返回 "—"：**不知道什么时候发生 ≠ 今天发生**。事件列表原本用
 * `updated_at`（这行数据什么时候写进库的）当"发布时间"，而所有事件都是同一次流水线
 * 生成的——于是 10 个事件全都显示"今天"，其中包括一个 340 天前的（刘一阳去世）。
 */
export function formatEventDateTime(eventTime) {
  const text = String(eventTime || '').trim()
  if (!text) return '—'
  const date = text.slice(0, 10)
  const hm = text.slice(11, 16)
  return hm ? `${date} ${hm}` : date
}
