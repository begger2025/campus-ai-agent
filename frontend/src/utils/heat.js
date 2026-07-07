/**
 * 热度展示工具 —— 全站统一口径。
 *
 * 后端定义（backend/agent/public_opinion_core/adapter.py）：
 *   单帖热度 = 点赞×1.0 + 收藏×1.5 + 评论×3.0 + 转发×2.5
 *   事件热度 = 聚合帖子热度之和（无上界，仅作事件间相对比较）
 *
 * 分级采用固定对数阈值（基于"加权互动量"的量级含义），
 * 跨时期稳定，不随当前数据集漂移。
 */

export const HEAT_TOOLTIP =
  '热度 = 帖子互动量加权和（点赞×1 + 收藏×1.5 + 评论×3 + 转发×2.5），数值无上界，用于事件间相对比较'

/** 148562 → "14.9万"；4927 → "4927"；1.2e8 → "1.2亿" */
export function formatHeat(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  if (n >= 1e8) return trimZero((n / 1e8).toFixed(1)) + '亿'
  if (n >= 1e4) return trimZero((n / 1e4).toFixed(1)) + '万'
  return String(Math.round(n))
}

function trimZero(s) {
  return s.endsWith('.0') ? s.slice(0, -2) : s
}

/** 固定阈值分级：≥10万 爆 / ≥1万 高 / ≥1千 中 / 其余 一般 */
export function heatLevel(value) {
  const n = Number(value) || 0
  if (n >= 100000) return { key: 'burst', label: '爆' }
  if (n >= 10000) return { key: 'high', label: '高' }
  if (n >= 1000) return { key: 'mid', label: '中' }
  return { key: 'normal', label: '一般' }
}
