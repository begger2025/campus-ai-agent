/**
 * api/agentChat.js — 舆情助手对话接口（流式）
 *
 * 为什么值得做流式（实测 gpt-5.4）：一份舆情简报要 3 次串行 LLM 调用
 * （路由 4.2s + 生成 19.4s + AI 审校 19.4s）≈ 43 秒。非流式下用户全程盯着
 * 一个空转圈；流式下 2.7 秒就开始读到正文。总耗时一样，感知差 8 倍。
 *
 * 非流式的 postAgentChat 已删（审计清扫）：注释声称"流式失败时的回退"，
 * 但回退从未接线、零调用——后端 POST /agent/public/chat 仍在，要接随时能接。
 */
import { getSession, logout } from '@/auth/session'

/**
 * 流式对话。onEvent(name, payload) 会被依次回调：
 *
 *   meta   { intent, keyword, route_source }   路由一出来就到，用户立刻知道在生成什么
 *   step   { thought, action, action_input }   ReAct 每走完一步（多步推理专有）
 *   delta  { text }                            正文增量，拼起来就是完整答案
 *   done   { events, citations, review, ... }  收尾元数据
 *   error  { message }                         流开始之后才发生的错误
 *
 * 返回 { promise, abort }：组件卸载时 abort，避免请求悬着。
 */
export function streamAgentChat(message, { reset = false, onEvent } = {}) {
  const controller = new AbortController()

  const run = async () => {
    const session = getSession()
    const response = await fetch('/api/agent/public/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(session?.token ? { Authorization: `Bearer ${session.token}` } : {}),
      },
      body: JSON.stringify({ message, reset }),
      signal: controller.signal,
    })

    // fetch 不走 axios 拦截器，401/403 的全局行为要自己复刻一遍。
    if (response.status === 401) {
      logout()
      window.location.href = '/login'
      throw new Error('登录已过期')
    }
    if (response.status === 403) {
      window.location.href = '/forbidden'
      throw new Error('没有权限')
    }
    if (!response.ok || !response.body) {
      throw new Error(`对话失败（HTTP ${response.status}）`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    // 网络分片和 SSE 事件边界毫无关系：一个 chunk 可能切在事件中间，也可能一次带来
    // 好几个事件。所以必须缓冲到看见空行（事件分隔符）才解析。
    let buffer = ''

    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      let split
      while ((split = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, split)
        buffer = buffer.slice(split + 2)
        const parsed = parseSseBlock(block)
        if (parsed) onEvent?.(parsed.event, parsed.data)
      }
    }
  }

  return { promise: run(), abort: () => controller.abort() }
}

function parseSseBlock(block) {
  let event = ''
  let data = ''
  for (const line of block.split('\n')) {
    if (line.startsWith('event: ')) event = line.slice(7)
    else if (line.startsWith('data: ')) data = line.slice(6)
  }
  if (!event) return null
  try {
    return { event, data: JSON.parse(data) }
  } catch {
    return null
  }
}
