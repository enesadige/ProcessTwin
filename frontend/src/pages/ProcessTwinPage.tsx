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
  type SimulationAnchorType,
  type SimulationEvent,
  type SimulationResult,
  type SimulationRun,
  type SimulationRunStatus,
  type TopologySummary,
} from '../auth/api'
import './ProcessTwinPage.css'

const SNAPSHOT_IDENTIFIER = 'multi-city-realism-v3-repair-r1-multi-city-realism-snapshot-v3-repair-r1'
const SPEEDS = [1, 10, 60] as const
const TERMINAL_STATUSES = new Set<SimulationRunStatus>(['completed', 'failed', 'stopped'])

type WorkspaceState = 'idle' | 'running' | 'ready' | 'error'
type FailureKind = 'access' | 'not-found' | 'validation' | 'lifecycle' | 'retryable' | 'other'

type ScenarioForm = {
  snapshotIdentifier: string
  anchorType: SimulationAnchorType
  anchorCode: string
  virtualStart: string
  deterministicSeed: string
  speed: 1 | 10 | 60
  baselineDuration: string
  baselineSlaTarget: string
  candidateDuration: string
  candidateSlaTarget: string
}

const initialForm: ScenarioForm = {
  snapshotIdentifier: SNAPSHOT_IDENTIFIER,
  anchorType: 'network_device',
  anchorCode: 'BNG-İZM-002',
  virtualStart: '2026-07-01T00:00:00+00:00',
  deterministicSeed: 'processtwin-ui-seed',
  speed: 10,
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
  if (typeof value === 'string') return value
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
  } as Record<string, string>)[key] ?? key.replaceAll('_', ' ')
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
    <div className="processtwin-section-heading"><div><p className="processtwin-eyebrow">Simulation projection</p><h3 id="projection-title">Simülasyon tahmini / Projected</h3></div><span className="processtwin-source-tag">Hypothetical</span></div>
    <p className="processtwin-note">Bu değerler source snapshot ve açık simulation varsayımlarından üretilmiştir; geçmiş doğrulanmış etki veya production fact değildir.</p>
    <div className="processtwin-fact-grid">
      <FactCard label="Potansiyel abonelik kapsamı" value={formatValue(projection.potential_subscription_scope)} />
      <FactCard label="Potansiyel müşteri kapsamı" value={formatValue(projection.potential_customer_scope)} />
      <FactCard label="Projected etkilenen abonelik" value={formatValue(projection.projected_affected_subscriptions)} />
      <FactCard label="Projected etkilenen müşteri" value={formatValue(projection.projected_affected_customers)} />
      <FactCard label="Projected korunan / no-impact" value={formatValue(projection.projected_protected_no_impact_subscriptions)} />
      <FactCard label="Projected unknown" value={formatValue(projection.projected_unknown_subscriptions)} muted={projection.projected_unknown_subscriptions === null || projection.projected_unknown_subscriptions === undefined} />
    </div>
    <ResultPairs values={{ basis: projection.basis, connection_basis: projection.connection_basis, failover_classification: projection.failover_classification, ...projection.assumptions }} />
  </section>
}

function HistoricalPanel({ result }: { result: SimulationResult }) {
  const evidence = result.historical_evidence
  const hasEvidence = Object.keys(evidence).length > 0 && evidence.basis !== 'not_used_for_device_anchor'
  return <section className="processtwin-result-section" aria-labelledby="historical-title">
    <div className="processtwin-section-heading"><div><p className="processtwin-eyebrow">Persisted source evidence</p><h3 id="historical-title">Geçmiş doğrulanmış kanıt</h3></div><span className="processtwin-source-tag">Historical</span></div>
    {hasEvidence ? <ResultPairs values={evidence} /> : <p className="processtwin-empty">Bu hypothetical anchor için ayrı bir historical verified impact sonucu kullanılmadı. Bu, sıfır historical impact anlamına gelmez.</p>}
  </section>
}

function ResultPanel({ title, run, result }: { title: string; run: SimulationRun | null; result: SimulationResult | null }) {
  if (!run || !result) return null
  const rule = result.rule_selection
  const compensation = result.compensation
  return <section className="processtwin-result" aria-labelledby={`${run.comparison_role}-result-title`}>
    <header className="processtwin-result__header"><div><p className="processtwin-eyebrow">{run.comparison_role === 'baseline' ? 'Canonical baseline' : 'Explicit candidate override'}</p><h2 id={`${run.comparison_role}-result-title`}>{title}</h2><p>{result.event.anchor_type} · {result.event.anchor_code} · {result.event.failure_type}</p></div><span className={`processtwin-run-status processtwin-run-status--${run.status}`}>{run.status}</span></header>
    <div className="processtwin-fact-grid">
      <FactCard label="Virtual başlangıç" value={formatValue(result.event.started_at ?? run.virtual_clock)} />
      <FactCard label="Süre" value={result.event.duration_seconds === null || result.event.duration_seconds === undefined ? 'Belirtilmedi' : `${formatValue(result.event.duration_seconds)} sn`} />
      <FactCard label="Kesinti sınıfı" value={formatValue(result.event.outage_classification)} />
      <FactCard label="Hız" value={`${run.speed_multiplier}x`} />
    </div>
    <ProjectionPanel result={result} />
    <HistoricalPanel result={result} />
    <section className="processtwin-result-section"><div className="processtwin-section-heading"><div><p className="processtwin-eyebrow">Temporal rule and simulated compensation</p><h3>Rule ve telafi sonucu</h3></div></div><div className="processtwin-fact-grid"><FactCard label="Seçilmiş RuleVersion" value={rule ? formatValue(rule) : 'Seçilmiş RuleVersion yok'} muted={!rule} /><FactCard label="Telafi durumu" value={formatValue(compensation.status)} /><FactCard label="Uygunluk" value={formatValue(compensation.eligibility)} /><FactCard label="Simulated tutar" value={`${formatValue(compensation.amount)} ${compensation.currency ?? ''}`.trim()} /><FactCard label="Uygun abonelik" value={formatValue(compensation.eligible_subscription_count)} /><FactCard label="Manuel inceleme" value={formatValue(compensation.manual_review_reason)} muted={Boolean(compensation.manual_review_reason)} /></div></section>
    <section className="processtwin-result-section"><div className="processtwin-section-heading"><div><p className="processtwin-eyebrow">Operational result</p><h3>SLA ve operasyon sonucu</h3></div></div><ResultPairs values={result.operational} /></section>
  </section>
}

function ComparisonPanel({ result }: { result: SimulationResult | null }) {
  if (!result?.comparison) return null
  return <section className="processtwin-comparison" aria-labelledby="comparison-title"><div className="processtwin-section-heading"><div><p className="processtwin-eyebrow">Canonical comparison</p><h2 id="comparison-title">Baseline / candidate delta</h2></div></div><ResultPairs values={result.comparison} /></section>
}

function Timeline({ events, hasMore, onLoadMore, loading }: { events: SimulationEvent[]; hasMore: boolean; onLoadMore: () => void; loading: boolean }) {
  return <section className="processtwin-timeline" aria-labelledby="timeline-title"><div className="processtwin-section-heading"><div><p className="processtwin-eyebrow">Persisted event trace</p><h2 id="timeline-title">Simulation event timeline</h2></div><span className="processtwin-source-tag">Cursor read</span></div><p className="processtwin-note">Bu gerçek zamanlı stream değildir. Timeline, tamamlanmış run’ın persisted simulation-local event kayıtlarından cursor ile okunur.</p>{events.length ? <ol>{events.map((event) => <li key={event.sequence}><span className="processtwin-timeline__sequence">{event.sequence}</span><div><strong>{event.event_type}</strong><p>{event.virtual_occurred_at}</p><small>{event.event_code}</small></div></li>)}</ol> : <p className="processtwin-empty">Bu cursor sayfasında event yok.</p>}{hasMore ? <button type="button" className="processtwin-secondary-button" onClick={onLoadMore} disabled={loading}>{loading ? 'Eventler yükleniyor' : 'Daha fazla event yükle'}</button> : null}</section>
}

function TopologyContext({ summary, state }: { summary: TopologySummary | null; state: 'idle' | 'loading' | 'ready' | 'unavailable' }) {
  if (state === 'idle') return null
  if (state === 'loading') return <section className="processtwin-topology" aria-live="polite">Cihaz topoloji bağlamı yükleniyor.</section>
  if (state === 'unavailable') return <section className="processtwin-topology">Cihaz topoloji bağlamı şu anda gösterilemiyor. Bu durum simulation sonucunu değiştirmez.</section>
  if (!summary) return null
  return <section className="processtwin-topology"><div className="processtwin-section-heading"><div><p className="processtwin-eyebrow">Read-only context</p><h2>Topology summary</h2></div></div><div className="processtwin-topology__grid"><div><span>Seçili cihaz</span><strong>{summary.root_device.code}</strong><p>{summary.root_device.device_type_label} · {summary.root_device.location}</p></div><div><span>Upstream</span><strong>{summary.upstream_devices.length}</strong><p>{summary.upstream_devices.map((device) => device.code).join(', ') || 'Doğrulanmış upstream yok'}</p></div><div><span>Downstream erişim</span><strong>{summary.downstream_total}</strong><p>{summary.downstream_devices.map((device) => device.code).join(', ') || 'Doğrulanmış downstream yok'}</p></div></div><p className="processtwin-note">Bu özet yalnız read-only topology bağlamıdır; projected impact veya failover sonucu üretmez.</p></section>
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
    if (form.anchorType !== 'network_device') return
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
        anchor_type: form.anchorType,
        anchor_code: form.anchorCode.trim(),
        failure_type: `${form.anchorType}_failure`,
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
        speed: form.speed,
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

  return <section className="processtwin-page">
    <header className="processtwin-page__header"><div><p className="processtwin-eyebrow">Hypothetical operations workspace</p><h1>ProcessTwin</h1><p>Snapshot-local source world üzerinde baseline ve explicit candidate koşullarını karşılaştırın.</p></div><span className="processtwin-source-tag">Simulation-local</span></header>

    <form className="processtwin-form" onSubmit={execute}>
      <div className="processtwin-section-heading"><div><p className="processtwin-eyebrow">Scenario input</p><h2>Baseline ve candidate koşulları</h2></div>{scenarioCode ? <span className="processtwin-form__code">Scenario {scenarioCode}</span> : null}</div>
      <div className="processtwin-form__grid">
        <label className="processtwin-field processtwin-field--wide"><span>Exact source snapshot</span><input value={form.snapshotIdentifier} onChange={(event) => update('snapshotIdentifier', event.target.value)} required /></label>
        <label className="processtwin-field"><span>Anchor türü</span><select value={form.anchorType} onChange={(event) => update('anchorType', event.target.value as SimulationAnchorType)}><option value="network_device">Network device</option><option value="network_link">Network link</option><option value="line_connection">Line connection</option></select></label>
        <label className="processtwin-field"><span>Exact anchor code</span><input value={form.anchorCode} onChange={(event) => update('anchorCode', event.target.value)} required /></label>
        <label className="processtwin-field"><span>Virtual başlangıç</span><input value={form.virtualStart} onChange={(event) => update('virtualStart', event.target.value)} placeholder="2026-07-01T00:00:00+00:00" required /></label>
        <label className="processtwin-field"><span>Deterministic seed</span><input value={form.deterministicSeed} onChange={(event) => update('deterministicSeed', event.target.value)} required /></label>
        <fieldset className="processtwin-speed"><legend>Hız</legend>{SPEEDS.map((speed) => <label key={speed}><input type="radio" name="speed" checked={form.speed === speed} onChange={() => update('speed', speed)} />{speed}x</label>)}</fieldset>
      </div>
      <div className="processtwin-parameter-grid">
        <section><h3>Baseline parametreleri</h3><label className="processtwin-field"><span>Süre (saniye)</span><input type="number" min="1" value={form.baselineDuration} onChange={(event) => update('baselineDuration', event.target.value)} required /></label><label className="processtwin-field"><span>SLA hedefi (saniye)</span><input type="number" min="1" value={form.baselineSlaTarget} onChange={(event) => update('baselineSlaTarget', event.target.value)} required /></label></section>
        <section><h3>Explicit candidate override</h3><label className="processtwin-field"><span>Süre override (opsiyonel)</span><input type="number" min="1" value={form.candidateDuration} onChange={(event) => update('candidateDuration', event.target.value)} /></label><label className="processtwin-field"><span>SLA hedefi override (opsiyonel)</span><input type="number" min="1" value={form.candidateSlaTarget} onChange={(event) => update('candidateSlaTarget', event.target.value)} /></label><p>Candidate yalnız bu açık override alanlarıyla baseline’dan ayrılır.</p></section>
      </div>
      <div className="processtwin-form__actions"><button className="processtwin-primary-button" type="submit" disabled={workspaceState === 'running'}>{workspaceState === 'running' ? 'Simulation isteği çalışıyor' : 'Baseline ve candidate çalıştır'}</button><p>Start endpoint’i senkrondur; ekranda sahte canlı progress veya clock üretilmez.</p></div>
    </form>

    {workspaceState === 'error' ? <section className="processtwin-state processtwin-state--error" role="alert"><h2>{failureTitle(errorKind)}</h2><p>{error}</p><button type="button" className="processtwin-secondary-button" onClick={() => setWorkspaceState('idle')}>Scenario girdisini düzenle</button></section> : null}
    {workspaceState === 'running' ? <section className="processtwin-state" aria-live="polite"><h2>Simulation isteği işleniyor</h2><p>Backend senkron canonical sonucu hazırlıyor. Tamamlanınca persisted result ve timeline okunacak.</p></section> : null}

    {candidateRun || baselineRun ? <section className="processtwin-run-controls"><div><p className="processtwin-eyebrow">Persisted run status</p><h2>Run kontrolleri</h2><p>Baseline: {baselineRun?.status ?? 'Belirtilmedi'} · Candidate: {candidateRun?.status ?? 'Belirtilmedi'} · Candidate virtual clock: {candidateRun?.virtual_clock ?? 'Belirtilmedi'}</p></div><div className="processtwin-run-controls__actions"><button type="button" className="processtwin-secondary-button" onClick={() => void refreshStatus()} disabled={!candidateRun || workspaceState === 'running'}>Durumu yenile</button><button type="button" className="processtwin-secondary-button" onClick={() => void lifecycleAction('pause')} disabled={!canPause}>Pause</button><button type="button" className="processtwin-secondary-button" onClick={() => void lifecycleAction('resume')} disabled={!canResume}>Resume</button><button type="button" className="processtwin-secondary-button" onClick={() => void lifecycleAction('stop')} disabled={!canStop}>Stop</button><button type="button" className="processtwin-primary-button" onClick={() => void replay()} disabled={!candidateRun || !candidateTerminal || workspaceState === 'running'}>Replay</button></div></section> : null}

    <TopologyContext summary={topologySummary} state={topologyState} />
    <div className="processtwin-results"><ResultPanel title="Baseline sonucu" run={baselineRun} result={baselineResult} /><ResultPanel title="Candidate sonucu" run={candidateRun} result={candidateResult} /></div>
    <ComparisonPanel result={candidateResult} />
    {candidateRun ? <Timeline events={events} hasMore={hasMoreEvents} loading={timelineLoading} onLoadMore={() => { if (nextCursor !== null) void readTimeline(candidateRun.run_code, nextCursor, true) }} /> : null}
  </section>
}
