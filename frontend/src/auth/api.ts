export type UserRole = 'viewer' | 'analyst' | 'engineer' | 'admin'

export type AuthUser = {
  id: number
  username: string
  email: string
  role: UserRole
}

export type ProviderName = 'ollama' | 'gemini'
export type ViewMode = 'management' | 'technical'

export type AnalysisRequest = {
  snapshot_identifier: string
  idempotency_key: string
  original_query: string
  llm_provider: ProviderName
  embedding_provider: ProviderName
}

export type AnalysisResponse = {
  query_run_code?: string
  status: string
  response?: {
    response_text: string
    generation_mode: string
    provider?: string
    model?: string
    warnings?: string[]
    citations?: Array<{ reference_code: string; reference_kind: string }>
  }
  clarification?: { code: string; reasons: string[]; message: string }
  error?: { code: string; message: string }
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

export class AnalysisRequestError extends Error {
  readonly status: number
  readonly payload: AnalysisResponse

  constructor(status: number, payload: AnalysisResponse) {
    super(payload.error?.message || 'Analiz isteği tamamlanamadı.')
    this.status = status
    this.payload = payload
  }
}

export async function submitAnalysis(payload: AnalysisRequest) {
  await ensureCsrf()
  const response = await fetch(`${apiBase}/api/orchestration/queries/execute/`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfCookie() ?? '',
    },
    body: JSON.stringify(payload),
  })
  const body = (await response.json().catch(() => ({}))) as AnalysisResponse
  if (!response.ok) throw new AnalysisRequestError(response.status, body)
  return body
}
