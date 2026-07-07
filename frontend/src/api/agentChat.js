/**
 * api/agentChat.js — 舆情助手对话接口
 *
 * ReAct 多步推理可能耗时 1~2 分钟（推理模型多次调用），
 * 单独放宽超时，不影响全局 8s 设置。
 */
import http from './http'

export async function postAgentChat(message, { reset = false } = {}) {
  return http.post(
    '/agent/public/chat',
    { message, reset },
    { timeout: 180000 },
  )
}
