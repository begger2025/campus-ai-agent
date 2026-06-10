import http from './http'

/**
 * 提交用户反馈（公开接口，无需 token）
 * POST /api/feedback
 */
export function submitFeedback(payload = {}) {
  return http.post('/feedback', {
    feedback_type: payload.feedback_type || 'suggestion',
    content: payload.content,
    contact: payload.contact || '',
    user_id: payload.user_id || 'anonymous',
    target_type: payload.target_type || 'public_event',
    target_id: String(payload.target_id || ''),
  })
}
