const STORAGE_KEY = 'campus_ai_agent_session'

const DEMO_ACCOUNTS = {
  admin: { username: 'admin', password: 'admin123', displayName: '管理员', role: 'admin' },
  user: { username: 'user', password: 'user123', displayName: '普通用户', role: 'user' },
}

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
  return role === 'admin' ? '/admin' : '/opinion'
}

export function mockLogin({ username, password, role }) {
  const normalizedRole = role === 'admin' ? 'admin' : 'user'
  const expected = DEMO_ACCOUNTS[normalizedRole]

  if (username !== expected.username || password !== expected.password) {
    throw new Error(`FE-01 临时账号：${expected.username} / ${expected.password}`)
  }

  const session = {
    token: `mock-${normalizedRole}-token`,
    user: {
      id: normalizedRole === 'admin' ? 1 : 2,
      username,
      displayName: expected.displayName,
      role: normalizedRole,
    },
  }

  writeStoredSession(session)
  return session
}

export function logout() {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(STORAGE_KEY)
  window.dispatchEvent(new Event('auth:changed'))
}
