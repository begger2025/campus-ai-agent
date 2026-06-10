import http from './http'

/**
 * 触发公共舆情 Agent 分析（管理员专用）
 * POST /api/agent/public/analyze
 * @param {{ keyword, limit, platforms, start_time, end_time, persist, created_by }} payload
 * @returns {{ status, input_count, event_count, warnings, events, payload_counts, run_log_id }}
 */
export function runPublicOpinionAnalysis(payload = {}) {
  return http.post('/agent/public/analyze', {
    keyword: payload.keyword || '',
    limit: payload.limit || 50,
    platforms: payload.platforms || [],
    start_time: payload.start_time || '',
    end_time: payload.end_time || '',
    persist: payload.persist ?? true,
    created_by: payload.created_by || 'frontend',
  })
}
