/**
 * api/auth.js — 真实认证接口
 *
 * 登录成功后由调用方（LoginView）通过 session.setSession 存储 token 与用户信息。
 */
import http from './http'

/**
 * POST /api/auth/login
 * @returns {Promise<{access_token: string, token_type: string, user: object}>}
 */
export function login(username, password) {
  return http.post('/auth/login', { username, password })
}

/**
 * POST /api/auth/register — 公开注册（角色固定为 user），成功即返回可用 token
 */
export function register({ username, password, display_name = '' }) {
  return http.post('/auth/register', { username, password, display_name })
}

/** GET /api/auth/me — 校验当前 token 并返回用户信息 */
export function fetchMe() {
  return http.get('/auth/me')
}
