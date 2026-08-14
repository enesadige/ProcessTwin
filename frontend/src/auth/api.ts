export type UserRole = 'viewer' | 'analyst' | 'engineer' | 'admin'

export type AuthUser = {
  id: number
  username: string
  email: string
  role: UserRole
}

export type ProviderName = 'ollama' | 'gemini' | 'nvidia' | 'groq'
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
    structured_result?: StructuredVerifiedResult
  }
  clarification?: { code: string; reasons: string[]; message: string }
  error?: { code: string; message: string }
}

export type CausalSummary = {
  causal_event_code?: string
  outage_code?: string
  root_resource_type?: string
  root_resource_reference?: string
  root_cause_reason_codes?: string[]
  role_counts?: Record<string, number>
  propagation_summary?: string
  event_type?: string
  root_cause_summary?: string
  root_alarm_types?: string[]
  symptom_alarm_types?: string[]
  dying_gasp_classification?: string
  device_not_active_classification?: string
  primary_status?: string
  backup_status?: string
  full_outage?: boolean
}

export type ImpactSummary = {
  outage_count?: number
  potential?: number
  verified_impacted?: number
  verified_no_impact?: number
  insufficient_evidence?: number
  failover_protected?: number
  failover_path_diversity_counts?: Record<string, number>
  affected_subscription_count?: number
  affected_customer_count?: number
  reason_code_distribution?: Record<string, number>
  assessment_record_count?: number
  missing_evidence_categories?: string[]
}

export type RuleSummary = {
  rule_codes?: string[]
  rule_versions?: string[]
  eligibility_status?: string
  evidence_references?: string[]
  baseline?: string
  candidate?: string
  difference_summary?: string
}

export type CompensationSummary = {
  status?: string
  considered?: number
  eligible?: number
  ineligible_pending?: number
  total_amount?: string
  currency?: string
  rule_versions?: Record<string, number>
  evidence_references?: string[]
  scope?: string
}

export type RetrievalSource = {
  source_code: string
  version?: number
  section?: string
  section_path?: string
  source_kind?: string
  score?: number
  score_source?: string
}

export type CrossIncidentCorrelationSummary = {
  anchor_event_code: string
  candidate_event_code?: string
  correlation_status: string
  time_difference_seconds?: number
  topology_relation?: string
  resource_relation?: string
  root_symptom_status?: string
}

export type AnalyticsSummary = {
  metric: string
  aggregation: string
  group_by?: string
  ranking_direction: string
  limit?: number
  time_grain?: string
  comparison?: boolean
  filters?: Record<string, unknown>
  scope_label?: string
  rows: Array<{ label: string; value: string | number; event_count: number; trend_direction?: string; absolute_change?: string | number; signed_change?: string | number; period_values?: Array<{ label: string; value: string | number; event_count: number; included_event_count?: number; excluded_unknown_count?: number }>; included_event_count?: number; excluded_unknown_count?: number }>
  included_event_count: number
  excluded_unknown_count: number
  deduplication_grain: string
}

export type StructuredVerifiedResult = {
  schema_version: string
  snapshot_identifier: string
  causal_summary?: CausalSummary
  cross_incident_correlation_summary?: CrossIncidentCorrelationSummary
  analytics_summary?: AnalyticsSummary
  analytics_summaries?: AnalyticsSummary[]
  impact_summary?: ImpactSummary
  rule_summary?: RuleSummary
  compensation_summary?: CompensationSummary
  retrieval_sources?: RetrievalSource[]
}

export type DecisionEvidenceDetail = {
  evidence_hash: string
  decision: string
  finalized: boolean
  rule_set?: { code?: string; name?: string } | null
  selected_rule_version?: { rule_code?: string; version?: number } | null
  price_basis?: string
  selected_price?: string | null
  unrounded_amount?: string | null
  final_amount: string
  currency: string
  matched_conditions: unknown[]
  failed_conditions: unknown[]
  excluded_rules: unknown[]
  applied_modifiers: unknown[]
  manual_review_reasons: unknown[]
  compensation_evaluation?: {
    evaluation_code: string
    result_type: string
    status: string
    outage_code: string
  } | null
}

export type AnalysisStatus = {
  query_run_code: string
  status: 'pending' | 'planned' | 'executing' | 'completed' | 'failed'
  phase: 'request_received' | 'plan_prepared' | 'tools_executing' | 'completed' | 'failed'
  planned_tool_count: number
  executed_tool_count: number
  succeeded_tool_count: number
  failed_tool_count: number
  planned_tools: string[]
  executed_tools: string[]
  error_code: string | null
  started_at: string | null
  completed_at: string | null
  elapsed_ms: number
}

export type TopologyDevice = {
  code: string
  name: string
  device_type: string
  device_type_label: string
  location: string
}

export type TopologyLink = {
  code: string
  source_device_code: string
  target_device_code: string
  status: string
  capacity_mbps: number
  link_layer?: string | null
}

export type TopologySummary = {
  snapshot_key: string
  root_device: TopologyDevice
  upstream_devices: TopologyDevice[]
  downstream_devices: TopologyDevice[]
  downstream_total: number
  links: TopologyLink[]
  connection_roles: Record<string, number>
  impact_scope?: {
    potential_connection_count: number
    verified_connection_count: number
    verified_subscription_count: number
    verified_customer_count: number
  } | null
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

export async function getAnalysisStatus(idempotencyKey: string) {
  const response = await fetch(
    `${apiBase}/api/orchestration/queries/status/?idempotency_key=${encodeURIComponent(idempotencyKey)}`,
    { credentials: 'include', headers: { Accept: 'application/json' } },
  )
  const body = (await response.json().catch(() => ({}))) as AnalysisStatus | AnalysisResponse
  if (response.status === 404) return null
  if (!response.ok) throw new AnalysisRequestError(response.status, body as AnalysisResponse)
  return body as AnalysisStatus
}

export async function getTopologySummary({
  snapshotIdentifier,
  deviceCode,
  causalEventCode,
}: {
  snapshotIdentifier: string
  deviceCode: string
  causalEventCode?: string
}) {
  const params = new URLSearchParams({
    snapshot_identifier: snapshotIdentifier,
    device_code: deviceCode,
  })
  if (causalEventCode) params.set('causal_event_code', causalEventCode)
  const response = await request<{ data: TopologySummary }>(`/api/orchestration/topology-summary/?${params}`)
  return response.data
}

export async function getDecisionEvidence({
  snapshotIdentifier,
  evidenceHash,
}: {
  snapshotIdentifier: string
  evidenceHash: string
}) {
  const params = new URLSearchParams({
    snapshot_identifier: snapshotIdentifier,
    evidence_hash: evidenceHash,
  })
  const response = await request<{
    data: { snapshot_key: string; decision_evidence: DecisionEvidenceDetail }
  }>(`/api/orchestration/decision-evidence/?${params}`)
  return response.data
}
