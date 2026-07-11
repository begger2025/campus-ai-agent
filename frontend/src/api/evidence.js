/**
 * api/evidence.js — AI 联网检索证据采集与人工审核接口（全部需要 admin 角色 token）
 *
 * 后端契约见 backend/routers/admin_evidence.py，
 * 列表接口统一返回 { items, total, page, page_size }。
 */
import http from './http'

// 采集一次 run 会并发调用多家联网检索大模型，远超默认 8s 超时，
// 因此单独放宽该请求的超时时间（axios 请求级配置覆盖实例配置）。
const RUN_TIMEOUT_MS = 180_000

// —— provider 可用性 ——
// 返回 { providers: [{ provider_id, enabled }], enabled_provider_ids }
// 只含 id 与开关，后端不会下发任何 key / base_url。
export function listProviders() {
  return http.get('/admin/evidence/providers')
}

// —— 采集任务 ——
export function createEvidenceRun({ topic, queries, provider_ids = undefined }) {
  return http.post(
    '/admin/evidence/runs',
    { topic, queries, provider_ids },
    { timeout: RUN_TIMEOUT_MS },
  )
}

export function fetchEvidenceRuns(params = {}) {
  return http.get('/admin/evidence/runs', { params })
}

export function fetchEvidenceRunDetail(runId) {
  return http.get(`/admin/evidence/runs/${runId}`)
}

// —— 证据条目 ——
export function fetchEvidenceItems(params = {}) {
  return http.get('/admin/evidence/items', { params })
}

export function reviewEvidenceItem(itemId, { status, note = null }) {
  return http.patch(`/admin/evidence/items/${itemId}/review`, { status, note })
}

// 核验：不传 status 时后端执行「抓取核验」——真的 GET 证据链接，
// 用页面正文判定 verified / needs_review / rejected（编造的链接会在这一步被驳回）。
// 抓取要等真实网络往返，比普通请求慢，单独放宽超时。
const VERIFY_TIMEOUT_MS = 30_000

export function verifyEvidenceItem(itemId, { method = 'fetch_url', status = undefined, reasons = undefined }) {
  return http.post(
    `/admin/evidence/items/${itemId}/verify`,
    { method, status, reasons },
    { timeout: VERIFY_TIMEOUT_MS },
  )
}

// —— 交付入库 ——
export function deliverEvidenceRun(runId) {
  return http.post(`/admin/evidence/runs/${runId}/deliver`, {}, { timeout: RUN_TIMEOUT_MS })
}
