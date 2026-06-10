import http from './http'

/**
 * 登录
 * POST /api/auth/login
 * @returns {{ access_token, token_type, user: { id, username, role, display_name, status } }}
 */
export function login(username, password) {
  return http.post('/auth/login', { username, password })
}

/**
 * 获取当前登录用户信息
 * GET /api/auth/me
 */
export function fetchMe() {
  return http.get('/auth/me')
}
