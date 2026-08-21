import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { AnalysisRequestError, getAnalysisStatus, getTopologySummary, submitAnalysis, type AnalysisStatus, type AnalyticsSummary, type CausalSummary, type CompensationSummary, type CrossIncidentCorrelationSummary, type ImpactSummary, type ProviderName, type RuleSummary, type StructuredVerifiedResult, type TopologyDevice, type TopologySummary } from '../auth/api'
import './AIAnalysisPage.css'

const SNAPSHOT_IDENTIFIER =
  'multi-city-realism-v3-repair-r1-multi-city-realism-snapshot-v3-repair-r1'
const MAX_QUERY_LENGTH = 10000
type Lifecycle = 'idle' | 'submitting' | 'success' | 'clarification' | 'failed'
type FailureKind = 'retryable' | 'access' | 'not-found' | 'other' | null
type TopologyState = 'idle' | 'loading' | 'ready' | 'unavailable'
type ProviderOption = { value: ProviderName; label: string }
type VerificationSectionId = 'alarm' | 'outage' | 'impact' | 'network' | 'topology' | 'compensation' | 'evidence' | 'analytics'
type VerificationSection = { id: VerificationSectionId; label: string; content: ReactNode | null }
type TopologyPanelId = 'upstream' | 'root' | 'downstream'

function ProviderPicker({ label, value, options, onChange }: { label: string; value: ProviderName; options: ProviderOption[]; onChange: (value: ProviderName) => void }) {
  const selected = options.find((option) => option.value === value) ?? options[0]

  return <details className="analysis-provider">
    <summary>
      <span>{label}</span>
      <strong>{selected.label}</strong>
    </summary>
    <div className="analysis-provider__menu" role="listbox" aria-label={`${label} sağlayıcısı`}>
      {options.map((option) => <button
        type="button"
        role="option"
        aria-selected={option.value === value}
        className={option.value === value ? 'analysis-provider__option analysis-provider__option--selected' : 'analysis-provider__option'}
        key={option.value}
        onClick={(event) => {
          onChange(option.value)
          event.currentTarget.closest('details')?.removeAttribute('open')
        }}
      >
        <span aria-hidden="true">{option.value === value ? '✓' : ''}</span>{option.label}
      </button>)}
    </div>
  </details>
}

function failureKind(status?: number, code?: string): Exclude<FailureKind, null> {
  if (status === 401 || status === 403 || code === 'authentication_required' || code === 'permission_denied') return 'access'
  if (status === 404 || code === 'not_found' || code === 'reference_not_found' || code === 'snapshot_not_found') return 'not-found'
  if ([408, 429, 502, 503, 504].includes(status ?? 0) || ['timeout', 'network_error', 'rate_limited', 'provider_unavailable', 'executor_transport_error', 'mcp_tool_failed'].includes(code ?? '')) return 'retryable'
  return 'other'
}

function displayStatus(value: string) {
  return ({
    calculated: 'Hesaplandı',
    eligible: 'Uygun',
    ineligible: 'Uygun değil',
    pending: 'Beklemede',
    manual_review: 'Manuel inceleme',
    draft: 'Taslak',
  } as Record<string, string>)[value] ?? value
}

function displayTopologyRelation(value?: string) {
  if (!value) return 'Doğrulanmış bağlantı'
  return ({
    aggregation_to_access: 'Aggregation → access',
    bng_to_aggregation: 'BNG → aggregation',
    alternate_access: 'Alternatif erişim',
    direct_parent_child: 'Doğrudan üst / alt bağlantı',
  } as Record<string, string>)[value] ?? value.replaceAll('_', ' ')
}

function topologyRelationClass(value?: string) {
  return value ? `topology-summary__link--${value.replaceAll('_', '-')}` : ''
}

function FactCard({ label, value, tone = '' }: { label: string; value: ReactNode; tone?: string }) {
  return <div className={`analysis-fact ${tone ? `analysis-fact--${tone}` : ''}`}><span className="analysis-fact__label">{label}</span><strong className="analysis-fact__value">{value}</strong></div>
}

function FactGroup({ title, children, tone = '' }: { title: string; children: ReactNode; tone?: string }) {
  return <section className={`analysis-fact-group ${tone ? `analysis-fact-group--${tone}` : ''}`}><h3><span aria-hidden="true" />{title}</h3><div className="analysis-fact-grid">{children}</div></section>
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

function formatRetrievalScore(score: number) {
  return new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 3 }).format(score)
}

function topologyRelationship(correlation: CrossIncidentCorrelationSummary) {
  const relation = correlation.topology_relation ?? correlation.resource_relation
  return ({ same_resource: 'Aynı doğrulanmış kaynak', direct_parent_child: 'Doğrudan üst/alt bağlantı', same_bng_branch: 'Aynı upstream BNG dalı', shared_failure_domain: 'Aynı doğrulanmış arıza alanı' } as Record<string, string>)[relation ?? '']
}

function TopologyDeviceList({ devices, emptyLabel }: { devices: TopologyDevice[]; emptyLabel: string }) {
  if (!devices.length) return <span className="topology-summary__empty">{emptyLabel}</span>
  return <div className="topology-summary__device-list">{devices.map((device) => <div className="topology-summary__device" key={device.code}><strong>{device.code}</strong><span>{device.device_type_label} · {device.location}</span></div>)}</div>
}

function TopologySummaryPanel({ summary }: { summary: TopologySummary }) {
  const scope = summary.impact_scope
  const primary = summary.connection_roles.primary ?? 0
  const backup = summary.connection_roles.backup ?? 0
  const linkRailRef = useRef<HTMLDivElement>(null)
  const [linkPage, setLinkPage] = useState(0)
  const [activePanel, setActivePanel] = useState<TopologyPanelId>('root')
  const linkPageCount = Math.min(5, Math.max(1, Math.ceil(summary.links.length / 3)))
  const moveLinkRail = (direction: -1 | 1) => {
    const nextPage = Math.min(linkPageCount - 1, Math.max(0, linkPage + direction))
    linkRailRef.current?.scrollTo({ left: linkRailRef.current.clientWidth * nextPage, behavior: 'smooth' })
    setLinkPage(nextPage)
  }
  return <section className="topology-summary" aria-label="Ağ topoloji özeti">
    <div className="topology-summary__heading"><h2>Topoloji özeti</h2></div>
    <div className="topology-summary__flow" aria-label="Topoloji akışı">
      <button type="button" aria-pressed={activePanel === 'upstream'} onClick={() => setActivePanel('upstream')} className={activePanel === 'upstream' ? 'topology-summary__lane topology-summary__lane--upstream topology-summary__panel--active' : 'topology-summary__lane topology-summary__lane--upstream'}><div className="topology-summary__panel-title"><p>Upstream<br />erişim</p></div><TopologyDeviceList devices={summary.upstream_devices} emptyLabel="Doğrulanmış upstream bağlantı yok" /></button>
      <button type="button" aria-pressed={activePanel === 'root'} onClick={() => setActivePanel('root')} className={activePanel === 'root' ? 'topology-summary__root topology-summary__panel--active' : 'topology-summary__root'}><span className="topology-summary__panel-icon topology-summary__panel-icon--root" aria-hidden="true" /><p>Seçili kök cihaz</p><strong>{summary.root_device.code}</strong><span>{summary.root_device.device_type_label} · {summary.root_device.location}</span></button>
      <button type="button" aria-pressed={activePanel === 'downstream'} onClick={() => setActivePanel('downstream')} className={activePanel === 'downstream' ? 'topology-summary__lane topology-summary__lane--downstream topology-summary__panel--active' : 'topology-summary__lane topology-summary__lane--downstream'}><div className="topology-summary__panel-title"><p>Downstream<br />erişim</p></div><TopologyDeviceList devices={summary.downstream_devices} emptyLabel="Doğrulanmış downstream bağlantı yok" /></button>
    </div>
    {summary.links.length ? <section className="topology-summary__routes" aria-label="Doğrulanmış bağlantılar"><div className="topology-summary__routes-header"><div><p>Bağlantı akışı</p><span>Doğrulanmış cihaz ilişkileri</span></div></div><div className="topology-summary__links" ref={linkRailRef} onScroll={(event) => { const width = event.currentTarget.clientWidth; if (width) setLinkPage(Math.min(linkPageCount - 1, Math.round(event.currentTarget.scrollLeft / width))) }}>{summary.links.map((link) => <article className={`topology-summary__link ${topologyRelationClass(link.link_layer)}`} key={link.code}><small>{displayTopologyRelation(link.link_layer)}</small><strong>{link.source_device_code} <b aria-hidden="true">→</b> {link.target_device_code}</strong></article>)}</div><div className="topology-summary__route-controls"><button type="button" onClick={() => moveLinkRail(-1)} disabled={linkPage === 0} aria-label="Önceki bağlantılar">‹</button><div aria-label={`Bağlantı sayfası ${linkPage + 1} / ${linkPageCount}`}>{Array.from({ length: linkPageCount }, (_, index) => <span className={index === linkPage ? 'topology-summary__route-dot topology-summary__route-dot--active' : 'topology-summary__route-dot'} key={index} />)}</div><button type="button" onClick={() => moveLinkRail(1)} disabled={linkPage >= linkPageCount - 1} aria-label="Sonraki bağlantılar">›</button></div></section> : null}
    {(scope || primary || backup) ? <div className="topology-summary__facts">
      {scope ? <><FactCard label="Potansiyel bağlantı kapsamı" value={scope.potential_connection_count} /><FactCard label="Doğrulanmış etki bağlantısı" value={scope.verified_connection_count} /><FactCard label="Doğrulanmış abonelik" value={scope.verified_subscription_count} /><FactCard label="Doğrulanmış müşteri" value={scope.verified_customer_count} /></> : null}
      {primary ? <FactCard label="Aktif primary bağlantı" value={primary} /> : null}
      {backup ? <FactCard label="Aktif backup bağlantı" value={backup} /> : null}
    </div> : null}
    <p className="topology-summary__note">Topoloji kapsamı, tek başına müşteri etkisi veya failover sonucu anlamına gelmez.</p>
  </section>
}

function VerifiedResultCards({ result, topologySummary, topologyState }: { result: StructuredVerifiedResult; topologySummary: TopologySummary | null; topologyState: TopologyState }) {
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
    if (compensation.status) decisionCards.push(<FactCard key="status" label="Telafi sonucu" value={displayStatus(compensation.status)} />)
    if (compensation.total_amount && compensation.currency) decisionCards.push(<FactCard key="amount" label="Toplam tutar" value={`${compensation.total_amount} ${compensation.currency}`} />)
  }
  if (rule) {
    if (!compensation?.status && rule.eligibility_status) decisionCards.push(<FactCard key="eligibility" label="Uygunluk" value={displayStatus(rule.eligibility_status)} />)
  }
  const provenanceCards: ReactNode[] = []
  const ruleCodes = [...new Set(rule?.rule_codes ?? [])]
  const ruleVersions = [...new Set([...(rule?.rule_versions ?? []), ...Object.keys(compensation?.rule_versions ?? {})])]
  const evidenceReferences = [...new Set([...(rule?.evidence_references ?? []), ...(compensation?.evidence_references ?? [])])]
  if (ruleCodes.length) provenanceCards.push(<FactCard key="rule-codes" label="Kural kodu" value={ruleCodes.join(', ')} />)
  if (ruleVersions.length) provenanceCards.push(<FactCard key="rule-versions" label="Seçilmiş RuleVersion" value={ruleVersions.join(', ')} />)
  evidenceReferences.forEach((reference) => {
    const evidenceLink = result.snapshot_identifier
      ? `/evidence?${new URLSearchParams({ evidence_hash: reference, snapshot_identifier: result.snapshot_identifier })}`
      : null
    const evidenceLabel = reference.length > 12 ? reference.slice(0, 12) : reference
    provenanceCards.push(
      <FactCard
        key={`decision-evidence-${reference}`}
        label="DecisionEvidence"
        value={evidenceLink ? <span className="analysis-evidence-link"><Link className="analysis-fact__link" to={evidenceLink}>Kanıtı görüntüle</Link><small>{evidenceLabel}</small></span> : evidenceLabel}
      />,
    )
  })
  result.retrieval_sources?.forEach((source) => {
    const reference = [
      `${source.source_code}${source.version !== undefined ? ` v${source.version}` : ''}`,
      source.section ? `Başlık: ${source.section}` : '',
      source.section_path ? `Bölüm: ${source.section_path}` : '',
      source.score !== undefined ? `Skor${source.score_source ? ` (${source.score_source})` : ''}: ${formatRetrievalScore(source.score)}` : '',
    ].filter(Boolean).join(' · ')
    provenanceCards.push(<FactCard key={`retrieval-${source.source_code}-${source.version ?? ''}-${source.section ?? ''}-${source.section_path ?? ''}`} label="RAG kaynağı" value={reference} />)
  })
  const correlationCards: ReactNode[] = []
  if (correlation) {
    correlationCards.push(<FactCard key="correlation-status" label="Korelasyon" value={correlationStatus(correlation.correlation_status)} />)
    if (correlation.candidate_event_code) correlationCards.push(<FactCard key="compared-events" label="Karşılaştırılan olaylar" value={`${correlation.anchor_event_code} / ${correlation.candidate_event_code}`} />)
    if (correlation.time_difference_seconds !== undefined) correlationCards.push(<FactCard key="time-difference" label="Zaman farkı" value={correlationDuration(correlation.time_difference_seconds)} />)
    const topology = topologyRelationship(correlation)
    if (topology) correlationCards.push(<FactCard key="topology" label="Topoloji ilişkisi" value={topology} />)
    if (correlation.root_symptom_status) correlationCards.push(<FactCard key="root-symptom" label="Kök/belirti yönü" value={correlation.root_symptom_status === 'not_verified' ? 'Doğrulanmadı' : 'Doğrulandı'} />)
  }
  const alarmAnalyticsCards: ReactNode[] = []
  const outageAnalyticsCards: ReactNode[] = []
  const otherAnalyticsCards: ReactNode[] = []
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
      const prefix = row.label === 'Toplam'
        ? (summary.scope_label
          ? `${summary.scope_label} — ${metricLabelsForTitle(summary.metric)}`
          : metricLabelsForTitle(summary.metric))
        : `${metricLabelsForTitle(summary.metric)}: ${index + 1}. ${rowLabel}`
      const card = <FactCard key={`analytics-${summaryIndex}-${index}-${row.label}`} label={prefix} value={[primaryValue, change].filter(Boolean).join(' | ')} />
      if (summary.metric === 'alarm_count') alarmAnalyticsCards.push(card)
      else if (summary.metric === 'outage_count' || summary.metric === 'full_outage_count') outageAnalyticsCards.push(card)
      else otherAnalyticsCards.push(card)
    }))
    analyticsSummaries.forEach((summary, index) => {
      if (summary.metric === 'affected_customers' || summary.metric === 'affected_subscriptions') {
        otherAnalyticsCards.push(<FactCard key={`analytics-included-${index}`} label={`${metricLabelsForTitle(summary.metric)} dahil`} value={summary.included_event_count} />)
        if (summary.excluded_unknown_count) otherAnalyticsCards.push(<FactCard key={`analytics-excluded-${index}`} label={`${metricLabelsForTitle(summary.metric)} bilinmeyen nedeniyle hariç`} value={summary.excluded_unknown_count} tone="warning" />)
      }
    })
  }
  const topologyContent = topologySummary
    ? <TopologySummaryPanel summary={topologySummary} />
    : topologyState === 'loading'
      ? <section className="topology-summary__state" aria-live="polite">Topoloji özeti yükleniyor.</section>
      : topologyState === 'unavailable'
        ? <section className="topology-summary__state" role="status">Topoloji özeti bu doğrulanmış kaynak için şu anda gösterilemiyor.</section>
        : null
  const sections: VerificationSection[] = [
    { id: 'alarm', label: 'Alarm', content: alarmAnalyticsCards.length ? <FactGroup title="Alarm analitiği" tone="analytics">{alarmAnalyticsCards}</FactGroup> : null },
    { id: 'outage', label: 'Kesinti', content: outageCards.length || outageAnalyticsCards.length ? <><FactGroup title="Kesinti" tone="network">{outageCards}</FactGroup>{outageAnalyticsCards.length ? <FactGroup title="Kesinti analitiği" tone="analytics">{outageAnalyticsCards}</FactGroup> : null}</> : null },
    { id: 'impact', label: 'Müşteri etkisi', content: impactCards.length ? <FactGroup title="Müşteri etkisi" tone="impact">{impactCards}</FactGroup> : null },
    { id: 'network', label: 'Ağ', content: rootCards.length || correlationCards.length ? <>{rootCards.length ? <FactGroup title="Kök neden" tone="root">{rootCards}</FactGroup> : null}{correlationCards.length ? <FactGroup title="Korelasyon kanıtı" tone="network">{correlationCards}</FactGroup> : null}</> : null },
    { id: 'topology', label: 'Topoloji', content: topologyContent },
    { id: 'compensation', label: 'Telafi', content: decisionCards.length ? <FactGroup title="Telafi ve karar" tone="decision">{decisionCards}</FactGroup> : null },
    { id: 'evidence', label: 'Kanıt', content: provenanceCards.length ? <FactGroup title="Kural ve kaynak kanıtları" tone="evidence">{provenanceCards}</FactGroup> : null },
    { id: 'analytics', label: 'Analitik', content: otherAnalyticsCards.length ? <FactGroup title="Operasyon analitiği" tone="analytics">{otherAnalyticsCards}</FactGroup> : null },
  ]
  const availableSections = sections.filter((section) => section.content)
  const sectionSignature = availableSections.map((section) => section.id).join(',')
  const [activeSection, setActiveSection] = useState<VerificationSectionId | null>(availableSections[0]?.id ?? null)
  useEffect(() => {
    if (!availableSections.some((section) => section.id === activeSection)) setActiveSection(availableSections[0]?.id ?? null)
  }, [activeSection, sectionSignature])
  const selectedSection = sections.find((section) => section.id === activeSection)
  return <div className="analysis-facts" aria-label="Doğrulanmış sonuç kartları">
    <div className="analysis-facts__heading"><p className="analysis-page__eyebrow">Doğrulanmış veri</p><span>Kaynak: backend</span></div>
    {availableSections.length ? <><div className="analysis-section-nav" role="tablist" aria-label="Doğrulanmış veri bölümleri">{sections.map((section) => {
      const available = Boolean(section.content)
      const active = activeSection === section.id
      return <button className={active ? 'analysis-section-nav__item analysis-section-nav__item--active' : 'analysis-section-nav__item'} type="button" role="tab" aria-selected={active} disabled={!available} key={section.id} onClick={() => setActiveSection(section.id)}><span className={`analysis-section-nav__icon analysis-section-nav__icon--${section.id}`} aria-hidden="true" />{section.label}</button>
    })}</div><div className="analysis-section-panel" role="tabpanel">{selectedSection?.content}</div></> : <p className="analysis-message">Bu yanıtta gösterilebilecek doğrulanmış alan bulunmuyor.</p>}
  </div>
}

function metricLabelsForTitle(metric: string) {
  return ({ affected_customers: 'Müşteri etkisi', affected_subscriptions: 'Abonelik etkisi', compensation_amount: 'Tazminat', full_outage_count: 'Tam kesinti', failed_failover_count: 'Failover', outage_count: 'Kesinti', event_count: 'Olay', alarm_count: 'Alarm' } as Record<string, string>)[metric] ?? 'Operasyon'
}

export function AIAnalysisPage() {
  const [query, setQuery] = useState('')
  const [llmProvider, setLlmProvider] = useState<ProviderName>('ollama')
  const [embeddingProvider, setEmbeddingProvider] = useState<ProviderName>('ollama')
  const [lifecycle, setLifecycle] = useState<Lifecycle>('idle')
  const [result, setResult] = useState<Awaited<ReturnType<typeof submitAnalysis>> | null>(null)
  const [error, setError] = useState('')
  const [failure, setFailure] = useState<FailureKind>(null)
  const [runKey, setRunKey] = useState<string | null>(null)
  const [runStartedAt, setRunStartedAt] = useState<number | null>(null)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [runStatus, setRunStatus] = useState<AnalysisStatus | null>(null)
  const [topologySummary, setTopologySummary] = useState<TopologySummary | null>(null)
  const [topologyState, setTopologyState] = useState<TopologyState>('idle')

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

  const causalSummary = result?.response?.structured_result?.causal_summary
  useEffect(() => {
    const deviceCode = causalSummary?.root_resource_type === 'device' ? causalSummary.root_resource_reference : undefined
    if (!deviceCode) {
      setTopologySummary(null)
      setTopologyState('idle')
      return
    }
    let cancelled = false
    setTopologyState('loading')
    void getTopologySummary({
      snapshotIdentifier: result?.response?.structured_result?.snapshot_identifier ?? SNAPSHOT_IDENTIFIER,
      deviceCode,
      causalEventCode: causalSummary?.causal_event_code,
    }).then((summary) => {
      if (!cancelled) {
        setTopologySummary(summary)
        setTopologyState('ready')
      }
    }).catch(() => {
      if (!cancelled) {
        setTopologySummary(null)
        setTopologyState('unavailable')
      }
    })
    return () => { cancelled = true }
  }, [causalSummary?.causal_event_code, causalSummary?.root_resource_reference, causalSummary?.root_resource_type, result?.response?.structured_result?.snapshot_identifier])

  async function submit() {
    const trimmed = query.trim()
    if (!trimmed || lifecycle === 'submitting') return
    setLifecycle('submitting')
    setError('')
    setFailure(null)
    setResult(null)
    setTopologySummary(null)
    setTopologyState('idle')
    const idempotencyKey = crypto.randomUUID()
    const startedAt = Date.now()
    setRunKey(idempotencyKey)
    setRunStartedAt(startedAt)
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
      // The execution response is terminal, but the last poll can still reflect an in-flight tool.
      // Read the persisted terminal status once before stopping polling so progress remains accurate.
      if (response.query_run_code) {
        try {
          const terminalStatus = await getAnalysisStatus(idempotencyKey)
          if (terminalStatus) setRunStatus(terminalStatus)
        } catch {
          // A completed response remains usable when this presentation-only refresh fails.
        }
      }
      setResult(response)
      setLifecycle(response.clarification ? 'clarification' : 'success')
    } catch (reason: unknown) {
      setLifecycle('failed')
      if (reason instanceof AnalysisRequestError) {
        setError(reason.message)
        setFailure(failureKind(reason.status, reason.code))
      } else {
        setError('Sunucuya ulaşılamadı.')
        setFailure('retryable')
      }
    }
    setElapsedSeconds((current) => Math.max(current, Math.ceil((Date.now() - startedAt) / 1000)))
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
        <h1 id="analysis-title">AI Analizi</h1>
      </div>

      <div className="analysis-grid">
        <div className="analysis-composer-stage">
          <form className="analysis-composer" onSubmit={(event) => { event.preventDefault(); void submit() }}>
            <h2 className="analysis-composer__sr-only">Sorgu oluştur</h2>
            <div className="analysis-composer__input">
              <label className="analysis-composer__sr-only" htmlFor="analysis-query">Doğal dil sorusu</label>
              <textarea
                id="analysis-query"
                value={query}
                maxLength={MAX_QUERY_LENGTH}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Operasyon verilerinde neyi incelemek istiyorsunuz?"
                rows={4}
              />
              <span className="analysis-composer__count">{query.length}/{MAX_QUERY_LENGTH}</span>
            </div>
            <div className="analysis-composer__footer">
              <div className="analysis-options">
                <ProviderPicker label="LLM" value={llmProvider} onChange={setLlmProvider} options={[{ value: 'ollama', label: 'Local Gemma' }, { value: 'gemini', label: 'Gemini' }, { value: 'nvidia', label: 'NVIDIA GLM-5.2' }, { value: 'groq', label: 'Groq GPT-OSS 120B' }]} />
                <ProviderPicker label="Embedding" value={embeddingProvider} onChange={setEmbeddingProvider} options={[{ value: 'ollama', label: 'Local Qwen' }, { value: 'gemini', label: 'Gemini Embedding' }]} />
              </div>
              <button className="analysis-submit" type="submit" disabled={!query.trim() || lifecycle === 'submitting'}>{lifecycle === 'submitting' ? 'Analiz çalışıyor...' : 'Analizi çalıştır'}</button>
            </div>
          </form>
        </div>
      </div>

      {(lifecycle === 'submitting' || runStatus) && <section className="analysis-progress" aria-live="polite" aria-label="Analiz işlem durumu">
        <div className="analysis-progress__header"><div><p className="analysis-page__eyebrow">Gerçek işlem durumu</p><h2>{lifecycle === 'submitting' ? (phaseLabels[currentPhase] ?? 'Sorgu çalışıyor') : lifecycle === 'success' ? 'Tamamlandı' : lifecycle === 'failed' ? 'İşlem başarısız' : 'İşlem sonucu'}</h2></div><span className="analysis-progress__duration">{Math.max(runStatus?.elapsed_ms ? Math.ceil(runStatus.elapsed_ms / 1000) : 0, elapsedSeconds)}s</span></div>
        <ol className="analysis-progress__steps">{phaseOrder.map((phase, index) => { const currentIndex = phaseOrder.indexOf(currentPhase); const state = lifecycle !== 'submitting' && phase === 'completed' ? 'complete' : index < currentIndex ? 'complete' : phase === currentPhase ? 'current' : 'pending'; return <li className={`analysis-progress__step analysis-progress__step--${state}`} key={phase}><span className="analysis-progress__step-marker" aria-hidden="true">{state === 'complete' ? '✓' : index + 1}</span><span className="analysis-progress__step-label">{phaseLabels[phase]}</span></li> })}</ol>
        {runStatus && runStatus.planned_tool_count > 0 && <p className="analysis-progress__tools"><span>MCP servis durumu</span><strong>{runStatus.succeeded_tool_count}/{runStatus.planned_tool_count} başarılı</strong></p>}
        {runStatus?.failed_tool_count ? <p className="analysis-message analysis-message--error">İşlem güvenli şekilde başarısız oldu: {runStatus.error_code ?? 'tool_error'}</p> : null}
      </section>}

      {lifecycle === 'failed' && <section className="analysis-state" role="alert" aria-live="assertive"><p className="analysis-page__eyebrow">İşlem durumu</p><h2>{failure === 'access' ? 'Erişim gerekiyor' : failure === 'not-found' ? 'Kayıt bulunamadı' : failure === 'retryable' ? 'İşlem geçici olarak tamamlanamadı' : 'Analiz isteği tamamlanamadı'}</h2><p>{error}</p>{failure === 'retryable' ? <button type="button" onClick={() => void submit()}>Tekrar dene</button> : null}{failure === 'not-found' ? <button type="button" onClick={() => setLifecycle('idle')}>Soruyu düzenle</button> : null}{failure === 'access' ? <Link to="/login">Oturuma git</Link> : null}</section>}

      {result?.response && !isUnsupported && <section className="analysis-result" aria-live="polite">
        <div className="analysis-result__meta"><span>QueryRun {result.query_run_code}</span></div>
        <div className="analysis-result__answer"><div><p className="analysis-page__eyebrow">Doğrulanmış yanıt</p><h2>Analiz sonucu</h2></div><p>{result.response.response_text}</p></div>
        {result.response.structured_result ? <VerifiedResultCards result={result.response.structured_result} topologySummary={topologySummary} topologyState={topologyState} /> : <p className="analysis-message">Bu yanıtta yapılandırılmış doğrulanmış alan bulunmuyor.</p>}
        {result.response.warnings?.length ? <p className="analysis-message">Uyarı: {result.response.warnings.join(', ')}</p> : null}
      </section>}
      {result?.clarification && <section className="analysis-result analysis-result--clarification" aria-live="polite"><p className="analysis-page__eyebrow">Ek seçim gerekiyor</p><h2>Doğru kaydı seçmemize yardımcı olun</h2><p>{result.clarification.message}</p><button type="button" onClick={() => setLifecycle('idle')}>Soruyu düzenle</button></section>}
      {isUnsupported && <section className="analysis-result analysis-result--unsupported" aria-live="polite"><p className="analysis-page__eyebrow">Analiz kapsamı</p><h2>Bu soru mevcut analiz kapsamı dışında</h2><p>Operasyon verileriyle doğrulanabilir bir kapsam bulunamadı.</p><button type="button" onClick={() => setLifecycle('idle')}>Soruyu düzenle</button></section>}
    </section>
  )
}
