const STORAGE_KEY = 'campus_ai_agent_session'

function readStoredSession() {
  if (typeof window === 'undefined') return null

  const raw = window.localStorage.getItem(STORAGE_KEY)
  if (!raw) return null

  try {
    return JSON.parse(raw)
  } catch {
    window.localStorage.removeItem(STORAGE_KEY)
    return null
  }
}

function writeStoredSession(session) {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
  window.dispatchEvent(new Event('auth:changed'))
}

export function getSession() {
  return readStoredSession()
}

export function getCurrentUser() {
  return getSession()?.user || null
}

export function getCurrentRole() {
  return getCurrentUser()?.role || 'guest'
}

export function isAuthenticated() {
  return Boolean(getSession()?.token)
}

export function hasRole(roles = []) {
  if (!roles.length) return true
  return roles.includes(getCurrentRole())
}

export function getDefaultPathForRole(role = getCurrentRole()) {
  // 管理员落「今日工作台」（今天要处理什么）；普通用户落首页仪表盘（先总览再深入）。
  // 工作台 /opinion 是深度研判工具，从事件列表点「研判」带着目标进入才合适。
  return role === 'admin' ? '/admin' : '/'
}

/**
 * 存储真实登录会话。
 * @param {{ token: string, user: { id, username, displayName, role } }} session
 */
export function setSession(session) {
  writeStoredSession(session)
  return session
}

export function logout() {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(STORAGE_KEY)
  window.dispatchEvent(new Event('auth:changed'))
}
