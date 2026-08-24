import { useMemo, useState, type FormEvent, type ReactNode } from 'react'

import {
  ApiRequestError,
  createBaselineSimulationRun,
  createCandidateSimulationRun,
  createSimulationScenario,
  getSimulationRunEvents,
  getSimulationRunResult,
  getSimulationRunStatus,
  getTopologySummary,
  replaySimulationRun,
  simulationLifecycleAction,
  startSimulationRun,
  validateSimulationScenario,
  type SimulationEvent,
  type SimulationResult,
  type SimulationRun,
  type SimulationRunStatus,
  type TopologySummary,
} from '../auth/api'
import './ProcessTwinPage.css'

const SNAPSHOT_IDENTIFIER = 'multi-city-realism-v3-repair-r1-multi-city-realism-snapshot-v3-repair-r1'
const FIXED_ANCHOR_TYPE = 'network_device' as const
const FIXED_SIMULATION_SPEED = 10 as const
const TERMINAL_STATUSES = new Set<SimulationRunStatus>(['completed', 'failed', 'stopped'])

type WorkspaceState = 'idle' | 'running' | 'ready' | 'error'
type FailureKind = 'access' | 'not-found' | 'validation' | 'lifecycle' | 'retryable' | 'other'
type ResultNavigationKey = 'controls' | 'topology' | 'baseline' | 'candidate' | 'comparison' | 'timeline'

type ScenarioForm = {
  snapshotIdentifier: string
  anchorCode: string
  virtualStart: string
  deterministicSeed: string
  baselineDuration: string
  baselineSlaTarget: string
  candidateDuration: string
  candidateSlaTarget: string
}

const initialForm: ScenarioForm = {
  snapshotIdentifier: SNAPSHOT_IDENTIFIER,
  anchorCode: 'BNG-İZM-002',
  virtualStart: '2026-07-01T00:00:00+00:00',
  deterministicSeed: 'processtwin-ui-seed',
  baselineDuration: '600',
  baselineSlaTarget: '300',
  candidateDuration: '',
  candidateSlaTarget: '900',
}

function failureKind(reason: unknown): FailureKind {
  if (!(reason instanceof ApiRequestError)) return 'retryable'
  if (reason.status === 401 || reason.status === 403) return 'access'
  if (reason.status === 404 || reason.code === 'not_found') return 'not-found'
  if (['invalid_anchor', 'unsupported_anchor_type', 'invalid_override', 'invalid_speed', 'validation_error', 'cross_snapshot_reference'].includes(reason.code ?? '')) return 'validation'
  if (['invalid_lifecycle_transition', 'duplicate_start', 'result_not_ready'].includes(reason.code ?? '')) return 'lifecycle'
  if ([408, 429, 502, 503, 504].includes(reason.status)) return 'retryable'
  return 'other'
}

function failureTitle(kind: FailureKind) {
  return {
    access: 'Erişim gerekiyor',
    'not-found': 'Simulation kaydı bulunamadı',
    validation: 'Scenario girdisi doğrulanamadı',
    lifecycle: 'Run durumu bu işlemi kabul etmiyor',
    retryable: 'İşlem geçici olarak tamamlanamadı',
    other: 'ProcessTwin isteği tamamlanamadı',
  }[kind]
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'Belirtilmedi'
  if (typeof value === 'boolean') return value ? 'Evet' : 'Hayır'
  if (typeof value === 'number') return new Intl.NumberFormat('tr-TR').format(value)
  if (typeof value === 'string') return ({
    completed: 'Tamamlandı',
    baseline: 'Referans',
    candidate: 'Aday',
    network_device: 'Ağ cihazı',
    network_link: 'Ağ bağlantısı',
    line_connection: 'Hat bağlantısı',
    network_device_failure: 'Ağ cihazı arızası',
    simulation_projection: 'Simülasyon tahmini',
    hypothetical: 'Varsayımsal',
    historical: 'Geçmiş',
    manual_review: 'Manuel inceleme',
    unknown: 'Bilinmiyor',
    no_single_rule_version: 'Tek bir RuleVersion belirlenemedi',
    eligible: 'Uygun',
    ineligible: 'Uygun değil',
    pending: 'Beklemede',
    calculated: 'Hesaplandı',
  } as Record<string, string>)[value] ?? value
  if (Array.isArray(value)) return value.length ? value.map(formatValue).join(', ') : 'Belirtilmedi'
  if (typeof value === 'object') {
    const record = value as Record<string, unknown>
    if ('baseline' in record && 'candidate' in record) {
      const suffix = record.changed === true ? ' (değişti)' : record.changed === false ? ' (değişmedi)' : ''
      return `${formatValue(record.baseline)} → ${formatValue(record.candidate)}${suffix}`
    }
    const code = record.rule_code ?? record.code
    const version = record.version
    if (typeof code === 'string') return version === null || version === undefined ? code : `${code} v${String(version)}`
    return `${Object.keys(record).length} doğrulanmış alan`
  }
  return 'Belirtilmedi'
}

function labelFor(key: string) {
  return ({
    basis: 'Temel',
    connection_basis: 'Bağlantı temeli',
    source_event_code: 'Kaynak olay',
    outage_classification: 'Kesinti sınıfı',
    duration_seconds: 'Süre',
    sla_target_seconds: 'SLA hedefi',
    sla_breached: 'SLA ihlali',
    operation_priority: 'Operasyon önceliği',
    status: 'Durum',
    eligibility: 'Uygunluk',
    amount: 'Tutar',
    currency: 'Para birimi',
    manual_review_reason: 'Manuel inceleme nedeni',
    potential_subscription_scope: 'Potansiyel abonelik kapsamı',
    potential_customer_scope: 'Potansiyel müşteri kapsamı',
    projected_affected_subscriptions: 'Tahmini etkilenen abonelik',
    projected_affected_customers: 'Tahmini etkilenen müşteri',
    projected_protected_no_impact_subscriptions: 'Tahmini korunan / etkisiz',
    projected_unknown_subscriptions: 'Tahmini bilinmeyen',
    projected_affected_customer_delta: 'Etkilenen müşteri farkı',
    projected_affected_customers_delta: 'Etkilenen müşteri farkı',
    projected_affected_subscription_delta: 'Etkilenen abonelik farkı',
    projected_affected_subscriptions_delta: 'Etkilenen abonelik farkı',
    projected_unknown_delta: 'Bilinmeyen farkı',
    projected_unknown_subscriptions_delta: 'Bilinmeyen farkı',
    projected_protected_no_impact_delta: 'Korunan / etkisiz farkı',
    projected_protected_no_impact_subscriptions_delta: 'Korunan / etkisiz farkı',
    compensation_amount_delta: 'Telafi tutarı farkı',
    duration_seconds_delta: 'Süre farkı',
    sla_target_seconds_delta: 'SLA hedefi farkı',
    comparison_role: 'Karşılaştırma rolü',
    run: 'Çalıştırma kodu',
    evidence_code: 'Kanıt kodu',
    evidence_hash: 'Kanıt parmak izi',
    virtual_clock: 'Sanal saat',
    scenario: 'Senaryo kodu',
    snapshot: 'Snapshot',
    finalized: 'Kesinleşti',
    selected_rule_version: 'Seçilmiş RuleVersion',
    failover_classification: 'Failover sınıflandırması',
    failure_mode: 'Arıza modu',
    protection_policy: 'Koruma politikası',
  } as Record<string, string>)[key] ?? key.replaceAll('_', ' ')
}

function simulationStatusLabel(status: SimulationRunStatus | undefined) {
  return ({
    draft: 'Taslak',
    ready: 'Hazır',
    running: 'Çalışıyor',
    paused: 'Duraklatıldı',
    completed: 'Tamamlandı',
    failed: 'Başarısız',
    stopped: 'Durduruldu',
  } as Record<SimulationRunStatus, string>)[status ?? 'ready']
}

function FactCard({ label, value, muted = false }: { label: string; value: ReactNode; muted?: boolean }) {
  return <article className={`processtwin-fact${muted ? ' processtwin-fact--muted' : ''}`}><span>{label}</span><strong>{value}</strong></article>
}

function ResultPairs({ values }: { values: Record<string, unknown> }) {
  const entries = Object.entries(values).filter(([, value]) => value !== null && value !== undefined && value !== '')
  if (!entries.length) return <p className="processtwin-empty">Bu bölüm için persisted bilgi yok.</p>
  return <dl className="processtwin-pairs">{entries.map(([key, value]) => <div key={key}><dt>{labelFor(key)}</dt><dd>{formatValue(value)}</dd></div>)}</dl>
}

function ProjectionPanel({ result }: { result: SimulationResult }) {
  const projection = result.projection
  return <section className="processtwin-result-section processtwin-result-section--projection" aria-labelledby="projection-title">
    <div className="processtwin-section-heading"><div><p className="processtwin-eyebrow">Simülasyon tahmini</p><h3 id="projection-title">Tahmini etki kapsamı</h3></div></div>
    <p className="processtwin-note">Bu değerler simülasyon koşullarından üretilmiştir; geçmiş doğrulanmış etki veya üretim gerçeği değildir.</p>
    <div className="processtwin-fact-grid">
      <FactCard label="Potansiyel abonelik kapsamı" value={formatValue(projection.potential_subscription_scope)} />
      <FactCard label="Potansiyel müşteri kapsamı" value={formatValue(projection.potential_customer_scope)} />
      <FactCard label="Tahmini etkilenen abonelik" value={formatValue(projection.projected_affected_subscriptions)} />
      <FactCard label="Tahmini etkilenen müşteri" value={formatValue(projection.projected_affected_customers)} />
      <FactCard label="Tahmini korunan / etkisiz" value={formatValue(projection.projected_protected_no_impact_subscriptions)} />
      <FactCard label="Tahmini bilinmeyen" value={formatValue(projection.projected_unknown_subscriptions)} muted={projection.projected_unknown_subscriptions === null || projection.projected_unknown_subscriptions === undefined} />
    </div>
    <details className="processtwin-technical-details"><summary>Teknik tahmin ayrıntıları</summary><ResultPairs values={{ basis: projection.basis, connection_basis: projection.connection_basis, failover_classification: projection.failover_classification, ...projection.assumptions }} /></details>
  </section>
}

function HistoricalPanel({ result, showNotice }: { result: SimulationResult; showNotice: boolean }) {
  const evidence = result.historical_evidence
  const hasEvidence = Object.keys(evidence).length > 0 && evidence.basis !== 'not_used_for_device_anchor'
  if (!hasEvidence) return null
  return <section className="processtwin-result-section" aria-labelledby="historical-title">
    <div className="processtwin-section-heading"><div><h3 id="historical-title">Geçmiş doğrulanmış kanıt</h3></div><span className="processtwin-source-tag">Geçmiş</span></div>
    {showNotice ? <p className="processtwin-note">Simülasyon tahmini, geçmiş doğrulanmış müşteri etkisi değildir.</p> : null}
    <details className="processtwin-technical-details"><summary>Kanıt ayrıntıları</summary><ResultPairs values={evidence} /></details>
  </section>
}

function ResultPanel({ title, run, result }: { title: string; run: SimulationRun | null; result: SimulationResult | null }) {
  if (!run || !result) return null
  const rule = result.rule_selection
  const compensation = result.compensation
  return <section className={`processtwin-result processtwin-result--${run.comparison_role}`} aria-labelledby={`${run.comparison_role}-result-title`}>
    <header className="processtwin-result__header"><div><h2 id={`${run.comparison_role}-result-title`}>{title}</h2><p>{formatValue(result.event.anchor_type)} · {result.event.anchor_code} · {formatValue(result.event.failure_type)}</p></div></header>
    <ProjectionPanel result={result} />
    <HistoricalPanel result={result} showNotice={run.comparison_role === 'baseline'} />
    <section className="processtwin-result-section processtwin-result-section--compensation"><div className="processtwin-section-heading"><div><h3>Kural ve telafi sonucu</h3></div></div><div className="processtwin-fact-grid"><FactCard label="Seçilmiş RuleVersion" value={rule ? formatValue(rule) : 'Seçilmiş RuleVersion yok'} muted={!rule} /><FactCard label="Telafi durumu" value={formatValue(compensation.status)} /><FactCard label="Uygunluk" value={formatValue(compensation.eligibility)} /><FactCard label="Simüle edilen tutar" value={`${formatValue(compensation.amount)} ${compensation.currency ?? ''}`.trim()} /><FactCard label="Uygun abonelik" value={formatValue(compensation.eligible_subscription_count)} /><FactCard label="Manuel inceleme nedeni" value={formatValue(compensation.manual_review_reason)} muted={Boolean(compensation.manual_review_reason)} /></div></section>
    <section className="processtwin-result-section processtwin-result-section--operational"><div className="processtwin-section-heading"><div><h3>SLA ve operasyon sonucu</h3></div></div><ResultPairs values={result.operational} /></section>
  </section>
}

function ComparisonPanel({ result }: { result: SimulationResult | null }) {
  if (!result?.comparison) return null
  const fieldOrder = [
    'projected_affected_customer_delta',
    'projected_affected_subscription_delta',
    'projected_unknown_delta',
    'projected_protected_no_impact_delta',
    'compensation_amount_delta',
    'duration_seconds_delta',
    'sla_target_seconds_delta',
    'sla_breached',
  ]
  const comparisonValues = Object.fromEntries(fieldOrder
    .filter((key) => result.comparison?.[key] !== null && result.comparison?.[key] !== undefined && result.comparison?.[key] !== '')
    .map((key) => [key, result.comparison?.[key]]))
  return <section className="processtwin-comparison" aria-labelledby="comparison-title"><div className="processtwin-section-heading"><div><p className="processtwin-eyebrow">Senaryo karşılaştırması</p><h2 id="comparison-title">Referans / aday farkı</h2></div></div><ResultPairs values={comparisonValues} /></section>
}

function simulationEventLabel(eventType: string) {
  return ({ runtime_started: 'Simülasyon başladı', bng_failure: 'BNG arızası', alarm: 'Alarm oluştu', incident: 'Olay oluştu', outage: 'Kesinti oluştu', customer_impact: 'Müşteri etkisi hesaplandı', compensation_evaluation: 'Telafi değerlendirildi', simulation_result: 'Simülasyon sonucu oluşturuldu', runtime_completed: 'Simülasyon tamamlandı' } as Record<string, string>)[eventType] ?? eventType.replaceAll('_', ' ')
}

function Timeline({ events, hasMore, onLoadMore, loading }: { events: SimulationEvent[]; hasMore: boolean; onLoadMore: () => void; loading: boolean }) {
  return <section className="processtwin-timeline" aria-labelledby="timeline-title"><div className="processtwin-section-heading"><div><p className="processtwin-eyebrow">Simülasyon olay akışı</p><h2 id="timeline-title">Simülasyon zaman çizelgesi</h2></div></div>{events.length ? <ol>{events.map((event) => <li key={event.sequence}><span className="processtwin-timeline__sequence">{event.sequence}</span><div><strong>{simulationEventLabel(event.event_type)}</strong><small>{event.event_code}</small></div></li>)}</ol> : <p className="processtwin-empty">Bu cursor sayfasında event yok.</p>}{hasMore ? <button type="button" className="processtwin-secondary-button" onClick={onLoadMore} disabled={loading}>{loading ? 'Eventler yükleniyor' : 'Daha fazla event yükle'}</button> : null}</section>
}

function ProcessTwinTopologyDeviceList({ devices, emptyLabel }: { devices: TopologySummary['upstream_devices']; emptyLabel: string }) {
  if (!devices.length) return <span className="processtwin-topology__empty">{emptyLabel}</span>
  return <div className="processtwin-topology__device-list">{devices.map((device) => <div className="processtwin-topology__device" key={device.code}><strong>{device.code}</strong><span>{device.device_type_label} · {device.location}</span></div>)}</div>
}

function TopologyContext({ summary, state }: { summary: TopologySummary | null; state: 'idle' | 'loading' | 'ready' | 'unavailable' }) {
  const [activePanel, setActivePanel] = useState<'upstream' | 'root' | 'downstream'>('root')
  if (state === 'idle') return null
  if (state === 'loading') return <section className="processtwin-topology" aria-live="polite">Cihaz topoloji bağlamı yükleniyor.</section>
  if (state === 'unavailable') return <section className="processtwin-topology">Cihaz topoloji bağlamı şu anda gösterilemiyor. Bu durum simulation sonucunu değiştirmez.</section>
  if (!summary) return null
  return <section className="processtwin-topology"><div className="processtwin-section-heading"><div><h2>Topoloji özeti</h2></div></div><div className="processtwin-topology__flow" aria-label="Topoloji akışı"><button type="button" aria-pressed={activePanel === 'upstream'} onClick={() => setActivePanel('upstream')} className={activePanel === 'upstream' ? 'processtwin-topology__lane processtwin-topology__lane--upstream processtwin-topology__panel--active' : 'processtwin-topology__lane processtwin-topology__lane--upstream'}><div className="processtwin-topology__panel-title"><p>Üst akış<br />erişim</p></div><ProcessTwinTopologyDeviceList devices={summary.upstream_devices} emptyLabel="Doğrulanmış üst akış yok" /></button><button type="button" aria-pressed={activePanel === 'root'} onClick={() => setActivePanel('root')} className={activePanel === 'root' ? 'processtwin-topology__root processtwin-topology__panel--active' : 'processtwin-topology__root'}><span className="processtwin-topology__panel-icon processtwin-topology__panel-icon--root" aria-hidden="true" /><p>Seçili kök cihaz</p><strong>{summary.root_device.code}</strong><span>{summary.root_device.device_type_label} · {summary.root_device.location}</span></button><button type="button" aria-pressed={activePanel === 'downstream'} onClick={() => setActivePanel('downstream')} className={activePanel === 'downstream' ? 'processtwin-topology__lane processtwin-topology__lane--downstream processtwin-topology__panel--active' : 'processtwin-topology__lane processtwin-topology__lane--downstream'}><div className="processtwin-topology__panel-title"><p>Alt akış<br />erişim</p></div><ProcessTwinTopologyDeviceList devices={summary.downstream_devices} emptyLabel="Doğrulanmış alt akış yok" /></button></div></section>
}

export function ProcessTwinPage() {
  const [form, setForm] = useState<ScenarioForm>(initialForm)
  const [workspaceState, setWorkspaceState] = useState<WorkspaceState>('idle')
  const [error, setError] = useState('')
  const [errorKind, setErrorKind] = useState<FailureKind>('other')
  const [scenarioCode, setScenarioCode] = useState<string | null>(null)
  const [baselineRun, setBaselineRun] = useState<SimulationRun | null>(null)
  const [candidateRun, setCandidateRun] = useState<SimulationRun | null>(null)
  const [baselineResult, setBaselineResult] = useState<SimulationResult | null>(null)
  const [candidateResult, setCandidateResult] = useState<SimulationResult | null>(null)
  const [events, setEvents] = useState<SimulationEvent[]>([])
  const [nextCursor, setNextCursor] = useState<number | null>(null)
  const [hasMoreEvents, setHasMoreEvents] = useState(false)
  const [timelineLoading, setTimelineLoading] = useState(false)
  const [topologySummary, setTopologySummary] = useState<TopologySummary | null>(null)
  const [topologyState, setTopologyState] = useState<'idle' | 'loading' | 'ready' | 'unavailable'>('idle')
  const [activeResultSection, setActiveResultSection] = useState<ResultNavigationKey>('controls')

  const candidateOverrides = useMemo(() => {
    const overrides: Record<string, unknown> = {}
    if (form.candidateDuration.trim()) overrides.duration_seconds = Number(form.candidateDuration)
    if (form.candidateSlaTarget.trim()) overrides.sla_target_seconds = Number(form.candidateSlaTarget)
    return overrides
  }, [form.candidateDuration, form.candidateSlaTarget])

  const update = <Key extends keyof ScenarioForm>(key: Key, value: ScenarioForm[Key]) => setForm((current) => ({ ...current, [key]: value }))

  const resetRunState = () => {
    setError('')
    setScenarioCode(null)
    setBaselineRun(null)
    setCandidateRun(null)
    setBaselineResult(null)
    setCandidateResult(null)
    setEvents([])
    setNextCursor(null)
    setHasMoreEvents(false)
    setTopologySummary(null)
    setTopologyState('idle')
    setActiveResultSection('controls')
  }

  const readTimeline = async (runCode: string, cursor?: number | null, append = false) => {
    setTimelineLoading(true)
    try {
      const page = await getSimulationRunEvents({ runCode, cursor, limit: 25 })
      setEvents((current) => append ? [...current, ...page.events.filter((event) => !current.some((item) => item.sequence === event.sequence))] : page.events)
      setNextCursor(page.next_cursor)
      setHasMoreEvents(page.has_more)
    } finally {
      setTimelineLoading(false)
    }
  }

  const loadDeviceTopology = async () => {
    setTopologyState('loading')
    try {
      const summary = await getTopologySummary({ snapshotIdentifier: form.snapshotIdentifier.trim(), deviceCode: form.anchorCode.trim() })
      setTopologySummary(summary)
      setTopologyState('ready')
    } catch {
      setTopologySummary(null)
      setTopologyState('unavailable')
    }
  }

  const execute = async (event: FormEvent) => {
    event.preventDefault()
    resetRunState()
    setWorkspaceState('running')
    try {
      if (!Object.keys(candidateOverrides).length) throw new Error('Candidate için en az bir açık override girilmelidir.')
      const scenarioPrefix = `PT-UI-${crypto.randomUUID().replaceAll('-', '').slice(0, 12).toUpperCase()}`
      const defaults = {
        duration_seconds: Number(form.baselineDuration),
        sla_target_seconds: Number(form.baselineSlaTarget),
        outage_classification: 'full_outage',
      }
      const scenarioInput = {
        source_snapshot_identifier: form.snapshotIdentifier.trim(),
        anchor_type: FIXED_ANCHOR_TYPE,
        anchor_code: form.anchorCode.trim(),
        failure_type: `${FIXED_ANCHOR_TYPE}_failure`,
        default_parameters: defaults,
      }
      await validateSimulationScenario(scenarioInput)
      await createSimulationScenario({ ...scenarioInput, scenario_code: scenarioPrefix, name: `ProcessTwin ${form.anchorCode.trim()} scenario` })
      setScenarioCode(scenarioPrefix)
      const baseline = await createBaselineSimulationRun({
        source_snapshot_identifier: form.snapshotIdentifier.trim(),
        scenario_code: scenarioPrefix,
        deterministic_seed: form.deterministicSeed.trim(),
        virtual_start: form.virtualStart.trim(),
        speed: FIXED_SIMULATION_SPEED,
      })
      setBaselineRun(baseline)
      const candidate = await createCandidateSimulationRun({
        source_snapshot_identifier: form.snapshotIdentifier.trim(),
        baseline_run_code: baseline.run_code,
        candidate_overrides: candidateOverrides,
      })
      setCandidateRun(candidate)
      const startedBaseline = await startSimulationRun(baseline.run_code)
      setBaselineRun(startedBaseline.run)
      setBaselineResult(startedBaseline.result)
      const startedCandidate = await startSimulationRun(candidate.run_code)
      setCandidateRun(startedCandidate.run)
      setCandidateResult(await getSimulationRunResult(startedCandidate.run.run_code))
      await readTimeline(startedCandidate.run.run_code)
      void loadDeviceTopology()
      setWorkspaceState('ready')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Simulation isteği tamamlanamadı.')
      setErrorKind(failureKind(reason))
      setWorkspaceState('error')
    }
  }

  const refreshStatus = async () => {
    if (!candidateRun) return
    try {
      setCandidateRun(await getSimulationRunStatus(candidateRun.run_code))
      if (baselineRun) setBaselineRun(await getSimulationRunStatus(baselineRun.run_code))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Run durumu alınamadı.')
      setErrorKind(failureKind(reason))
      setWorkspaceState('error')
    }
  }

  const lifecycleAction = async (action: 'pause' | 'resume' | 'stop') => {
    if (!candidateRun) return
    try {
      setCandidateRun(await simulationLifecycleAction(candidateRun.run_code, action))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Lifecycle işlemi tamamlanamadı.')
      setErrorKind(failureKind(reason))
      setWorkspaceState('error')
    }
  }

  const replay = async () => {
    if (!candidateRun) return
    setWorkspaceState('running')
    setError('')
    try {
      const candidateReplay = await replaySimulationRun(candidateRun.run_code)
      if (!candidateReplay.baseline_run_code) throw new Error('Candidate replay için bağlı baseline replay kaydı bulunamadı.')
      const replayBaseline = await startSimulationRun(candidateReplay.baseline_run_code)
      const replayCandidate = await startSimulationRun(candidateReplay.run_code)
      setBaselineRun(replayBaseline.run)
      setBaselineResult(replayBaseline.result)
      setCandidateRun(replayCandidate.run)
      setCandidateResult(await getSimulationRunResult(replayCandidate.run.run_code))
      await readTimeline(replayCandidate.run.run_code)
      setWorkspaceState('ready')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Replay tamamlanamadı.')
      setErrorKind(failureKind(reason))
      setWorkspaceState('error')
    }
  }

  const candidateTerminal = candidateRun ? TERMINAL_STATUSES.has(candidateRun.status) : true
  const canPause = candidateRun?.status === 'running'
  const canResume = candidateRun?.status === 'paused'
  const canStop = candidateRun?.status === 'ready' || candidateRun?.status === 'running' || candidateRun?.status === 'paused'
  const resultNavigation = [
    { key: 'controls' as const, label: 'Çalıştırma kontrolleri', available: Boolean(candidateRun || baselineRun) },
    { key: 'topology' as const, label: 'Topoloji özeti', available: topologyState !== 'idle' },
    { key: 'baseline' as const, label: 'Referans senaryo', available: Boolean(baselineResult) },
    { key: 'candidate' as const, label: 'Aday senaryo', available: Boolean(candidateResult) },
    { key: 'comparison' as const, label: 'Senaryo karşılaştırması', available: Boolean(candidateResult?.comparison) },
    { key: 'timeline' as const, label: 'Simülasyon olay akışı', available: Boolean(candidateRun) },
  ].filter((item) => item.available)

  return <section className="processtwin-page">
    <header className="processtwin-page__header"><div><h1>Süreç Simülasyonu</h1></div></header>

    <form className="processtwin-form" onSubmit={execute}>
      <div className="processtwin-section-heading"><div><p className="processtwin-eyebrow">Senaryo girdisi</p><h2>Senaryo koşulları</h2></div>{scenarioCode ? <span className="processtwin-form__code">Scenario {scenarioCode}</span> : null}</div>
      <div className="processtwin-form__grid">
        <label className="processtwin-field"><span>Sanal başlangıç zamanı</span><input value={form.virtualStart} onChange={(event) => update('virtualStart', event.target.value)} placeholder="2026-07-01T00:00:00+00:00" required /></label>
        <label className="processtwin-field"><span>Hedef kodu</span><input value={form.anchorCode} onChange={(event) => update('anchorCode', event.target.value)} required /></label>
      </div>
      <div className="processtwin-parameter-grid">
        <section><h3>Referans senaryo (Baseline)</h3><label className="processtwin-field"><span>Süre</span><input type="number" min="1" value={form.baselineDuration} onChange={(event) => update('baselineDuration', event.target.value)} required /></label><label className="processtwin-field"><span>SLA hedefi</span><input type="number" min="1" value={form.baselineSlaTarget} onChange={(event) => update('baselineSlaTarget', event.target.value)} required /></label></section>
        <section><h3>Aday senaryo</h3><label className="processtwin-field"><span>Süre değişikliği (isteğe bağlı)</span><input type="number" min="1" value={form.candidateDuration} onChange={(event) => update('candidateDuration', event.target.value)} /></label><label className="processtwin-field"><span>SLA hedefi değişikliği (isteğe bağlı)</span><input type="number" min="1" value={form.candidateSlaTarget} onChange={(event) => update('candidateSlaTarget', event.target.value)} /></label><p>Aday senaryo yalnız burada belirtilen değişikliklerle referans senaryodan ayrılır.</p></section>
      </div>
      <div className="processtwin-form__actions"><button className="analysis-submit" type="submit" disabled={workspaceState === 'running'}>{workspaceState === 'running' ? 'Simülasyon çalışıyor...' : 'Senaryoları karşılaştır'}</button></div>
    </form>

    {workspaceState === 'error' ? <section className="processtwin-state processtwin-state--error" role="alert"><h2>{failureTitle(errorKind)}</h2><p>{error}</p><button type="button" className="processtwin-secondary-button" onClick={() => setWorkspaceState('idle')}>Scenario girdisini düzenle</button></section> : null}
    {workspaceState === 'running' ? <section className="processtwin-state" aria-live="polite"><h2>Simulation isteği işleniyor</h2><p>Backend senkron canonical sonucu hazırlıyor. Tamamlanınca persisted result ve timeline okunacak.</p></section> : null}

    {resultNavigation.length ? <nav className="processtwin-section-nav" aria-label="Simülasyon sonuç bölümleri">{resultNavigation.map((item) => <button type="button" key={item.key} className={activeResultSection === item.key ? 'processtwin-section-nav__item processtwin-section-nav__item--active' : 'processtwin-section-nav__item'} onClick={() => setActiveResultSection(item.key)}>{item.label}</button>)}</nav> : null}
    {activeResultSection === 'controls' && (candidateRun || baselineRun) ? <section className="processtwin-run-controls"><div><h2>Çalıştırma kontrolleri</h2><p>Referans: {simulationStatusLabel(baselineRun?.status)} · Aday: {simulationStatusLabel(candidateRun?.status)} · Aday sanal saati: {candidateRun?.virtual_clock ?? 'Belirtilmedi'}</p></div><div className="processtwin-run-controls__actions"><button type="button" className="processtwin-secondary-button" onClick={() => void refreshStatus()} disabled={!candidateRun || workspaceState === 'running'}>Durumu yenile</button><button type="button" className="processtwin-secondary-button" onClick={() => void lifecycleAction('pause')} disabled={!canPause}>Duraklat</button><button type="button" className="processtwin-secondary-button" onClick={() => void lifecycleAction('resume')} disabled={!canResume}>Devam et</button><button type="button" className="processtwin-secondary-button" onClick={() => void lifecycleAction('stop')} disabled={!canStop}>Durdur</button><button type="button" className="processtwin-primary-button" onClick={() => void replay()} disabled={!candidateRun || !candidateTerminal || workspaceState === 'running'}>Yeniden çalıştır</button></div></section> : null}
    {activeResultSection === 'topology' ? <TopologyContext summary={topologySummary} state={topologyState} /> : null}
    {activeResultSection === 'baseline' ? <ResultPanel title="Referans senaryo" run={baselineRun} result={baselineResult} /> : null}
    {activeResultSection === 'candidate' ? <ResultPanel title="Aday senaryo" run={candidateRun} result={candidateResult} /> : null}
    {activeResultSection === 'comparison' ? <ComparisonPanel result={candidateResult} /> : null}
    {activeResultSection === 'timeline' && candidateRun ? <Timeline events={events} hasMore={hasMoreEvents} loading={timelineLoading} onLoadMore={() => { if (nextCursor !== null) void readTimeline(candidateRun.run_code, nextCursor, true) }} /> : null}
  </section>
}
