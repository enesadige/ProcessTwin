import { useEffect, useState, type ReactNode } from 'react'

import { useAuth } from '../auth/AuthContext'
import { AnalysisRequestError, getAnalysisStatus, submitAnalysis, type AnalysisStatus, type AnalyticsSummary, type CausalSummary, type CompensationSummary, type CrossIncidentCorrelationSummary, type ImpactSummary, type ProviderName, type RuleSummary, type StructuredVerifiedResult, type ViewMode } from '../auth/api'
import './AIAnalysisPage.css'

const SNAPSHOT_IDENTIFIER =
  'multi-city-realism-v3-repair-r1-multi-city-realism-snapshot-v3-repair-r1'
const MAX_QUERY_LENGTH = 10000
const EXAMPLES = [
  'AGG-ANK-002 cihazındaki kesintiden kaç müşteri ve kaç abonelik gerçekten etkilendi?',
  'CE-MCR-0010 olayında ana bağlantı down ve yedek bağlantı active. Bu tam kesinti mi?',
  '6 Haziran 2026 tarihinde Konak ilçesinde kaç kesinti yaşandı?',
]

type Lifecycle = 'idle' | 'submitting' | 'success' | 'clarification' | 'failed'

function FactCard({ label, value, tone = '' }: { label: string; value: string | number; tone?: string }) {
  return <div className={`analysis-fact ${tone ? `analysis-fact--${tone}` : ''}`}><span>{label}</span><strong>{value}</strong></div>
}

function FactGroup({ title, children }: { title: string; children: ReactNode }) {
  return <section className="analysis-fact-group"><h3>{title}</h3><div className="analysis-fact-grid">{children}</div></section>
}

function correlationDuration(seconds: number) {
  if (seconds < 60) return `${seconds} saniye`
  const totalMinutes = Math.floor(seconds / 60)
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  if (hours && minutes) return `${hours} saat ${minutes} dakika`
  if (hours) return `${hours} saat`
  return `${totalMinutes} dakika`
}

function correlationStatus(status: string) {
  return ({ verified_relation: 'Doğrulandı', insufficient_evidence: 'Kanıt yetersiz', no_relation: 'İlişki bulunmadı' } as Record<string, string>)[status] ?? 'Doğrulanmış durum yok'
}

function topologyRelationship(correlation: CrossIncidentCorrelationSummary) {
  const relation = correlation.topology_relation ?? correlation.resource_relation
  return ({ same_resource: 'Aynı doğrulanmış kaynak', direct_parent_child: 'Doğrudan üst/alt bağlantı', same_bng_branch: 'Aynı upstream BNG dalı', shared_failure_domain: 'Aynı doğrulanmış arıza alanı' } as Record<string, string>)[relation ?? '']
}

function VerifiedResultCards({ result, technical }: { result: StructuredVerifiedResult; technical: boolean }) {
  const causal: CausalSummary | undefined = result.causal_summary
  const impact: ImpactSummary | undefined = result.impact_summary
  const compensation: CompensationSummary | undefined = result.compensation_summary
  const rule: RuleSummary | undefined = result.rule_summary
  const correlation: CrossIncidentCorrelationSummary | undefined = result.cross_incident_correlation_summary
  const analytics: AnalyticsSummary | undefined = result.analytics_summary
  const analyticsSummaries = result.analytics_summaries?.length ? result.analytics_summaries : (analytics ? [analytics] : [])
  const impactCards: ReactNode[] = []
  if (impact) {
    if (impact.outage_count !== undefined) impactCards.push(<FactCard key="outage-count" label="Kesinti sayısı" value={impact.outage_count} />)
    if (impact.potential !== undefined) impactCards.push(<FactCard key="potential" label="Potansiyel kapsam" value={impact.potential} />)
    if (impact.affected_subscription_count !== undefined) impactCards.push(<FactCard key="subscriptions" label="Etkilenen abonelik" value={impact.affected_subscription_count} />)
    if (impact.affected_customer_count !== undefined) impactCards.push(<FactCard key="customers" label="Etkilenen müşteri" value={impact.affected_customer_count} />)
    if (impact.verified_impacted !== undefined && impact.affected_subscription_count === undefined) impactCards.push(<FactCard key="verified" label="Doğrulanmış etki" value={impact.verified_impacted} />)
    if (impact.verified_no_impact !== undefined) impactCards.push(<FactCard key="no-impact" label="Doğrulanmış etkisiz" value={impact.verified_no_impact} />)
    if (impact.insufficient_evidence !== undefined) impactCards.push(<FactCard key="insufficient" label="Kanıtı yetersiz" value={impact.insufficient_evidence} tone={impact.insufficient_evidence > 0 ? 'warning' : ''} />)
    if (impact.failover_protected !== undefined) impactCards.push(<FactCard key="protected" label="Failover ile korunan" value={impact.failover_protected} />)
  }
  const outageCards: ReactNode[] = []
  if (causal) {
    if (causal.event_type) outageCards.push(<FactCard key="event-type" label="Olay sınıfı" value={causal.event_type} />)
    if (causal.full_outage !== undefined) outageCards.push(<FactCard key="full-outage" label="Tam hizmet kesintisi" value={causal.full_outage ? 'Evet' : 'Hayır'} />)
    if (causal.primary_status) outageCards.push(<FactCard key="primary" label="Ana bağlantı" value={causal.primary_status} />)
    if (causal.backup_status) outageCards.push(<FactCard key="backup" label="Yedek bağlantı" value={causal.backup_status} />)
    const resource = [causal.root_resource_type, causal.root_resource_reference].filter(Boolean).join(' ')
    if (resource) outageCards.push(<FactCard key="resource" label="Doğrulanmış kök kaynak" value={resource} />)
  }
  const rootCards: ReactNode[] = []
  if (causal) {
    if (causal.root_cause_summary) rootCards.push(<FactCard key="cause" label="Fiziksel kök neden" value={causal.root_cause_summary} />)
    if (causal.root_alarm_types?.length) rootCards.push(<FactCard key="root-alarm" label="Kök neden alarmı" value={causal.root_alarm_types.join(', ')} />)
    if (causal.symptom_alarm_types?.length) rootCards.push(<FactCard key="symptoms" label="Belirti alarmları" value={causal.symptom_alarm_types.join(', ')} />)
    if (causal.root_cause_reason_codes?.includes('root_cause_unverified')) rootCards.push(<FactCard key="unknown" label="RCA durumu" value="Doğrulanmadı; manuel inceleme" tone="warning" />)
  }
  const decisionCards: ReactNode[] = []
  if (compensation) {
    if (compensation.status) decisionCards.push(<FactCard key="status" label="Telafi sonucu" value={compensation.status} />)
    if (compensation.total_amount && compensation.currency) decisionCards.push(<FactCard key="amount" label="Toplam tutar" value={`${compensation.total_amount} ${compensation.currency}`} />)
    if (compensation.rule_versions && Object.keys(compensation.rule_versions).length) decisionCards.push(<FactCard key="comp-rules" label="Uygulanan RuleVersion" value={Object.keys(compensation.rule_versions).join(', ')} />)
    if (compensation.evidence_references?.length) decisionCards.push(<FactCard key="comp-evidence" label="DecisionEvidence" value={compensation.evidence_references.join(', ')} />)
  }
  if (rule) {
    if (rule.rule_versions?.length) decisionCards.push(<FactCard key="rules" label="Kural sürümü" value={rule.rule_versions.join(', ')} />)
    if (rule.evidence_references?.length) decisionCards.push(<FactCard key="evidence" label="Karar kanıtı" value={rule.evidence_references.join(', ')} />)
    if (!compensation?.status && rule.eligibility_status) decisionCards.push(<FactCard key="eligibility" label="Uygunluk" value={rule.eligibility_status} />)
  }
  const correlationCards: ReactNode[] = []
  if (correlation) {
    correlationCards.push(<FactCard key="correlation-status" label="Korelasyon" value={correlationStatus(correlation.correlation_status)} />)
    if (correlation.candidate_event_code) correlationCards.push(<FactCard key="compared-events" label="Karşılaştırılan olaylar" value={`${correlation.anchor_event_code} / ${correlation.candidate_event_code}`} />)
    if (correlation.time_difference_seconds !== undefined) correlationCards.push(<FactCard key="time-difference" label="Zaman farkı" value={correlationDuration(correlation.time_difference_seconds)} />)
    const topology = topologyRelationship(correlation)
    if (topology) correlationCards.push(<FactCard key="topology" label="Topoloji ilişkisi" value={topology} />)
    if (correlation.root_symptom_status) correlationCards.push(<FactCard key="root-symptom" label="Kök/belirti yönü" value={correlation.root_symptom_status === 'not_verified' ? 'Doğrulanmadı' : 'Doğrulandı'} />)
  }
  const analyticsCards: ReactNode[] = []
  if (analyticsSummaries.length) {
    analyticsSummaries.forEach((summary, summaryIndex) => summary.rows.forEach((row, index) => {
      const periods = row.period_values?.map((period) => {
        const evidence = period.included_event_count !== undefined && period.excluded_unknown_count !== undefined
          ? ` (dahil: ${period.included_event_count}, hariç: ${period.excluded_unknown_count})`
          : ''
        return `${period.label}: ${period.value}${evidence}`
      }).join(' | ')
      const change = row.absolute_change !== undefined ? `Fark: ${row.absolute_change}` : ''
      const rowEvidence = row.included_event_count !== undefined && row.excluded_unknown_count !== undefined
        ? ` (dahil: ${row.included_event_count}, hariç: ${row.excluded_unknown_count})`
        : ''
      const primaryValue = periods || `${row.value}${rowEvidence}`
      const rowLabel = row.label === 'Toplam' ? (summary.scope_label ?? 'Toplam') : row.label
      const prefix = row.label === 'Toplam' ? metricLabelsForTitle(summary.metric) : `${metricLabelsForTitle(summary.metric)}: ${index + 1}. ${rowLabel}`
      analyticsCards.push(<FactCard key={`analytics-${summaryIndex}-${index}-${row.label}`} label={prefix} value={[primaryValue, change].filter(Boolean).join(' | ')} />)
    }))
    analyticsSummaries.forEach((summary, index) => {
      if (summary.metric === 'affected_customers' || summary.metric === 'affected_subscriptions') {
        analyticsCards.push(<FactCard key={`analytics-included-${index}`} label={`${metricLabelsForTitle(summary.metric)} dahil`} value={summary.included_event_count} />)
        if (summary.excluded_unknown_count) analyticsCards.push(<FactCard key={`analytics-excluded-${index}`} label={`${metricLabelsForTitle(summary.metric)} bilinmeyen nedeniyle hariç`} value={summary.excluded_unknown_count} tone="warning" />)
      }
    })
  }
  return <div className="analysis-facts" aria-label="Doğrulanmış sonuç kartları">
    <div className="analysis-facts__heading"><div><p className="analysis-page__eyebrow">Doğrulanmış veri</p><h2>Operasyon özeti</h2></div><span>Kaynak: backend</span></div>
    {impactCards.length ? <FactGroup title="Müşteri etkisi">{impactCards}</FactGroup> : null}
    {outageCards.length ? <FactGroup title="Kesinti ve ağ">{outageCards}</FactGroup> : null}
    {technical && rootCards.length ? <FactGroup title="Kök neden">{rootCards}</FactGroup> : null}
    {decisionCards.length ? <FactGroup title="Telafi ve karar">{decisionCards}</FactGroup> : null}
    {correlationCards.length ? <FactGroup title="Korelasyon kanıtı">{correlationCards}</FactGroup> : null}
    {analyticsCards.length ? <FactGroup title={analyticsSummaries.length > 1 ? 'Operasyon analitiği' : analytics ? `${metricLabelsForTitle(analytics.metric)} analitiği` : 'Analitik'}>{analyticsCards}</FactGroup> : null}
    {technical && result.retrieval_sources?.length ? <FactGroup title="Kanıt referansları">{result.retrieval_sources.map((source) => <FactCard key={`${source.source_code}-${source.version ?? ''}-${source.section ?? ''}`} label={source.section ?? 'Kaynak'} value={`${source.source_code}${source.version !== undefined ? ` v${source.version}` : ''}`} />)}</FactGroup> : null}
    {!impactCards.length && !outageCards.length && !rootCards.length && !decisionCards.length && !correlationCards.length && !analyticsCards.length ? <p className="analysis-message">Bu sorgu için yapılandırılmış doğrulanmış alan bulunmuyor.</p> : null}
  </div>
}

function metricLabelsForTitle(metric: string) {
  return ({ affected_customers: 'Müşteri etkisi', affected_subscriptions: 'Abonelik etkisi', compensation_amount: 'Tazminat', full_outage_count: 'Tam kesinti', failed_failover_count: 'Failover', outage_count: 'Kesinti', event_count: 'Olay', alarm_count: 'Alarm' } as Record<string, string>)[metric] ?? 'Operasyon'
}

export function AIAnalysisPage() {
  const { user } = useAuth()
  const [query, setQuery] = useState('')
  const [llmProvider, setLlmProvider] = useState<ProviderName>('ollama')
  const [embeddingProvider, setEmbeddingProvider] = useState<ProviderName>('ollama')
  const [viewMode, setViewMode] = useState<ViewMode>('management')
  const [lifecycle, setLifecycle] = useState<Lifecycle>('idle')
  const [result, setResult] = useState<Awaited<ReturnType<typeof submitAnalysis>> | null>(null)
  const [error, setError] = useState('')
  const [runKey, setRunKey] = useState<string | null>(null)
  const [runStartedAt, setRunStartedAt] = useState<number | null>(null)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [runStatus, setRunStatus] = useState<AnalysisStatus | null>(null)

  useEffect(() => {
    if (!runKey) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const poll = async () => {
      try {
        const status = await getAnalysisStatus(runKey)
        if (!cancelled && status) setRunStatus(status)
      } catch {
        // The POST response remains authoritative if a transient poll fails.
      }
      if (!cancelled) timer = setTimeout(poll, 700)
    }
    void poll()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [runKey])

  useEffect(() => {
    if (!runStartedAt) return
    const timer = setInterval(() => setElapsedSeconds(Math.floor((Date.now() - runStartedAt) / 1000)), 250)
    return () => clearInterval(timer)
  }, [runStartedAt])

  async function submit() {
    const trimmed = query.trim()
    if (!trimmed || lifecycle === 'submitting') return
    setLifecycle('submitting')
    setError('')
    setResult(null)
    const idempotencyKey = crypto.randomUUID()
    setRunKey(idempotencyKey)
    setRunStartedAt(Date.now())
    setElapsedSeconds(0)
    setRunStatus(null)
    try {
      const response = await submitAnalysis({
        snapshot_identifier: SNAPSHOT_IDENTIFIER,
        idempotency_key: idempotencyKey,
        original_query: trimmed,
        llm_provider: llmProvider,
        embedding_provider: embeddingProvider,
      })
      setResult(response)
      setLifecycle(response.clarification ? 'clarification' : 'success')
    } catch (reason: unknown) {
      setLifecycle('failed')
      setError(reason instanceof AnalysisRequestError ? reason.message : 'Sunucuya ulaşılamadı.')
    }
    setRunKey(null)
    setRunStartedAt(null)
  }

  const currentPhase = runStatus?.phase === 'failed' ? 'tools_executing' : (runStatus?.phase ?? 'request_received')
  const phaseOrder = ['request_received', 'plan_prepared', 'tools_executing', 'completed']
  const phaseLabels: Record<string, string> = {
    request_received: 'Sorgu alındı',
    plan_prepared: 'Plan hazırlandı',
    tools_executing: 'Operasyon verileri işleniyor',
    completed: 'Tamamlandı',
  }
  const isUnsupported = result?.response?.response_text === 'Bu sorgu mevcut analiz kapsamı tarafından desteklenmiyor.'

  return (
    <section className="analysis-page" aria-labelledby="analysis-title">
      <div className="analysis-page__header">
        <div>
          <p className="analysis-page__eyebrow">Workspace / AI Analysis</p>
          <h1 id="analysis-title">Operasyon sorusu</h1>
          <p>Doğal dilde bir soru sorun; doğrulanmış operasyon kayıtları üzerinden yanıt alın.</p>
        </div>
        <span className="analysis-page__role">{user?.role} workspace</span>
      </div>

      <div className="analysis-grid">
        <form className="analysis-composer" onSubmit={(event) => { event.preventDefault(); void submit() }}>
          <div className="analysis-composer__topline"><h2>Sorgu oluştur</h2><span>{query.length}/{MAX_QUERY_LENGTH}</span></div>
          <label htmlFor="analysis-query">Doğal dil sorusu</label>
          <textarea
            id="analysis-query"
            value={query}
            maxLength={MAX_QUERY_LENGTH}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Örn. AGG-ANK-002 cihazındaki kesintide kaç müşteri etkilendi?"
            rows={8}
          />
          <div className="analysis-options">
            <label>LLM provider<select value={llmProvider} onChange={(event) => setLlmProvider(event.target.value as ProviderName)}><option value="ollama">Local Gemma</option><option value="gemini">Gemini</option><option value="nvidia">NVIDIA GLM-5.2</option><option value="groq">Groq GPT-OSS 120B</option></select></label>
            <label>Embedding provider<select value={embeddingProvider} onChange={(event) => setEmbeddingProvider(event.target.value as ProviderName)}><option value="ollama">Local Qwen</option><option value="gemini">Gemini Embedding</option></select></label>
            <fieldset><legend>Görünüm</legend><label><input type="radio" checked={viewMode === 'management'} onChange={() => setViewMode('management')} /> Yönetim</label><label><input type="radio" checked={viewMode === 'technical'} onChange={() => setViewMode('technical')} /> Teknik</label></fieldset>
          </div>
          <button className="analysis-submit" type="submit" disabled={!query.trim() || lifecycle === 'submitting'}>{lifecycle === 'submitting' ? 'Analiz çalışıyor...' : 'Analizi çalıştır'}</button>
          {lifecycle === 'failed' && <p className="analysis-message analysis-message--error" role="alert">{error}</p>}
        </form>

        <aside className="analysis-examples" aria-label="Örnek sorular">
          <p className="analysis-page__eyebrow">Başlangıç soruları</p>
          <h2>Gerçek kapsamdan örnekler</h2>
          <p>Bir örneği seçerek sorgu alanına taşıyın.</p>
          {EXAMPLES.map((example) => <button type="button" key={example} onClick={() => setQuery(example)}>{example}</button>)}
        </aside>
      </div>

      {(lifecycle === 'submitting' || runStatus) && <section className="analysis-progress" aria-live="polite" aria-label="Analiz işlem durumu">
        <div className="analysis-progress__header"><div><p className="analysis-page__eyebrow">Gerçek işlem durumu</p><h2>{lifecycle === 'submitting' ? (phaseLabels[currentPhase] ?? 'Sorgu çalışıyor') : lifecycle === 'success' ? 'Tamamlandı' : lifecycle === 'failed' ? 'İşlem başarısız' : 'İşlem sonucu'}</h2></div><span>{runStatus?.elapsed_ms ? Math.round(runStatus.elapsed_ms / 1000) : elapsedSeconds}s</span></div>
        <ol className="analysis-progress__steps">{phaseOrder.map((phase, index) => { const currentIndex = phaseOrder.indexOf(currentPhase); const state = lifecycle !== 'submitting' && phase === 'completed' ? 'complete' : index < currentIndex ? 'complete' : phase === currentPhase ? 'current' : 'pending'; return <li className={`analysis-progress__step analysis-progress__step--${state}`} key={phase}><span aria-hidden="true">{state === 'complete' ? '✓' : index + 1}</span>{phaseLabels[phase]}</li> })}</ol>
        {runStatus && runStatus.planned_tool_count > 0 && <p className="analysis-progress__tools">Servis durumu: {runStatus.succeeded_tool_count}/{runStatus.planned_tool_count} başarılı</p>}
        {runStatus?.failed_tool_count ? <p className="analysis-message analysis-message--error">İşlem güvenli şekilde başarısız oldu: {runStatus.error_code ?? 'tool_error'}</p> : null}
      </section>}

      {result?.response && <section className="analysis-result" aria-live="polite"><div className="analysis-result__meta"><span>QueryRun {result.query_run_code}</span><span>{result.response.provider} / {result.response.model}</span><span>{viewMode === 'technical' ? 'Teknik görünüm' : 'Yönetim görünümü'}</span></div><div className="analysis-result__answer"><p className="analysis-page__eyebrow">Analiz yanıtı</p><h2>Yanıt</h2><p>{result.response.response_text}</p></div>{result.response.structured_result ? <VerifiedResultCards result={result.response.structured_result} technical={viewMode === 'technical'} /> : null}{result.response.warnings?.length ? <p className="analysis-message">Uyarı: {result.response.warnings.join(', ')}</p> : null}</section>}
      {result?.clarification && <section className="analysis-result analysis-result--clarification" aria-live="polite"><h2>Ek bilgi gerekiyor</h2><p>{result.clarification.message}</p><button type="button" onClick={() => setLifecycle('idle')}>Soruyu düzenle</button></section>}
      {isUnsupported && <section className="analysis-result analysis-result--clarification" aria-live="polite"><button type="button" onClick={() => setLifecycle('idle')}>Soruyu düzenle</button></section>}
    </section>
  )
}
