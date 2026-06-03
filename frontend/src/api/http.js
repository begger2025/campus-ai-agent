/**
 * api/http.js — 统一 axios 实例 + 拦截器
 *
 * 所有 API 模块通过此文件获取 http 实例，确保：
 * 1. 请求自动注入 token
 * 2. 响应统一解包 { code, data, message }
 * 3. 401/403 自动处理
 * 4. 全局 dataSource 标记（供 DataSourceBadge 使用）
 */
import axios from 'axios'
import { getSession, logout } from '@/auth/session'

// ---------------------------------------------------------------------------
// 全局数据来源标记（供 DataSourceBadge 组件读取）
// 'real' | 'mock' | 'demo'
// ---------------------------------------------------------------------------
let _dataSource = 'mock'

export function getDataSource() {
  return _dataSource
}

export function setDataSource(source) {
  _dataSource = source
}

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

    // 标准 { code: 0, data: ..., message: "..." } 格式
    if (body && typeof body.code === 'number') {
      if (body.code === 0) {
        // 标记为真实接口数据
        _dataSource = 'real'
        return body.data !== undefined ? body.data : body
      }
      // 业务错误
      const err = new Error(body.message || `请求失败 (code=${body.code})`)
      err.code = body.code
      return Promise.reject(err)
    }

    // 非标准响应 — 视为真实接口
    _dataSource = 'real'
    return body
  },
  (error) => {
    if (error.response) {
      const { status } = error.response
      if (status === 401) {
        logout()
        window.location.href = '/login'
      }
      if (status === 403) {
        window.location.href = '/forbidden'
      }
    }
    return Promise.reject(error)
  },
)

export default http
