export type UserRole = 'viewer' | 'analyst' | 'engineer' | 'admin'

export type AuthUser = {
  id: number
  username: string
  email: string
  role: UserRole
}

const apiBase = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

function csrfCookie() {
  return document.cookie
    .split('; ')
    .find((cookie) => cookie.startsWith('csrftoken='))
    ?.split('=')[1]
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    credentials: 'include',
    headers: { Accept: 'application/json', ...init.headers },
  })
  const body = (await response.json().catch(() => ({}))) as { detail?: string }
  if (!response.ok) {
    throw new Error(body.detail || 'The request could not be completed.')
  }
  return body as T
}

export async function ensureCsrf() {
  await request('/api/auth/csrf/')
}

export async function getCurrentUser() {
  const response = await request<{ user: AuthUser }>('/api/auth/me/')
  return response.user
}

export async function login(username: string, password: string) {
  await ensureCsrf()
  const response = await request<{ user: AuthUser }>('/api/auth/login/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfCookie() ?? '',
    },
    body: JSON.stringify({ username, password }),
  })
  return response.user
}

export async function logout() {
  await request('/api/auth/logout/', {
    method: 'POST',
    headers: { 'X-CSRFToken': csrfCookie() ?? '' },
  })
}
