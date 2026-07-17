/**
 * api/http.js — 统一 axios 实例 + 拦截器
 *
 * 所有 API 模块通过此文件获取 http 实例，确保：
 * 1. 请求自动注入 token
 * 2. 响应统一解包 { code, data, message }
 * 3. 401/403 自动处理
 * 4. 全局后端连接状态（供 MainLayout 顶栏徽标使用）
 */
import { ref } from 'vue'
import axios from 'axios'
import { getSession, logout } from '@/auth/session'

// ---------------------------------------------------------------------------
// 后端连接状态（响应式，MainLayout 顶栏徽标直接绑定）
// 'pending'：本次会话还没有任何请求返回；'real'：后端有响应（哪怕是业务错误，
// 说明连接是通的）；'down'：请求发出去但没有任何响应（后端没启动/超时）。
// 此前这里是个非响应式字符串，顶栏「真实接口」徽标则是写死的静态文本——
// 前端 mock 兜底 + 假徽标曾组合出「假数据配真徽标」的双重误导（用户实测截图）。
// ---------------------------------------------------------------------------
export const backendState = ref('pending')

// ---------------------------------------------------------------------------
// axios 实例
// ---------------------------------------------------------------------------
const http = axios.create({
  baseURL: '/api',
  timeout: 8000,
  headers: { 'Content-Type': 'application/json' },
})

// —— 请求拦截器：注入 token ——
http.interceptors.request.use(
  (config) => {
    const session = getSession()
    if (session?.token) {
      config.headers.Authorization = `Bearer ${session.token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

// —— 响应拦截器：解包 + 错误处理 ——
http.interceptors.response.use(
  (response) => {
    const body = response.data

    backendState.value = 'real'

    // 标准 { code: 0, data: ..., message: "..." } 格式
    if (body && typeof body.code === 'number') {
      if (body.code === 0) {
        return body.data !== undefined ? body.data : body
      }
      // 业务错误
      const err = new Error(body.message || `请求失败 (code=${body.code})`)
      err.code = body.code
      return Promise.reject(err)
    }

    // 非标准响应 — 原样返回
    return body
  },
  (error) => {
    // 有响应体的错误（4xx/5xx）说明后端是通的；完全无响应才是「未连接」。
    // 超时（ECONNABORTED）单独对待：慢调用（同步 LLM/大批量）超过请求时限时
    // 后端多半还活着、还在处理——据此把顶栏打成「后端未连接」是误报
    // （真宕机是秒失败的 ERR_NETWORK，不是等满时限的超时）。
    const isTimeout = error.code === 'ECONNABORTED'
    if (error.response) {
      backendState.value = 'real'
    } else if (!isTimeout) {
      backendState.value = 'down'
    }
    // 登录请求本身的 401/403 是"账号密码错误/被禁用"，要把错误交还登录页展示，
    // 而不是触发全局登出跳转（否则错误提示被页面刷新吞掉）。
    const isLoginRequest = (error.config?.url || '').includes('/auth/login')
    if (error.response) {
      const { status, data } = error.response
      if (status === 401 && !isLoginRequest) {
        logout()
        window.location.href = '/login'
      }
      if (status === 403 && !isLoginRequest) {
        window.location.href = '/forbidden'
      }
      const detail = data?.detail || data?.message
      if (typeof detail === 'string' && detail) error.message = detail
    } else if (error.request) {
      error.message = isTimeout
        ? '请求超时：后端可能仍在处理（AI 调用较慢），请稍后重试'
        : '无法连接服务器，请确认后端已启动'
    }
    return Promise.reject(error)
  },
)

export default http
