import { useEffect, useState } from 'react'

import { useAuth } from '../auth/AuthContext'
import { AnalysisRequestError, getAnalysisStatus, submitAnalysis, type AnalysisStatus, type ProviderName, type ViewMode } from '../auth/api'
import './AIAnalysisPage.css'

const SNAPSHOT_IDENTIFIER =
  'multi-city-realism-v2-causal-r1-multi-city-realism-snapshot-v1-multi-city-realism-v2-causal-r1'
const MAX_QUERY_LENGTH = 10000
const EXAMPLES = [
  'AGG-ANK-002 cihazındaki kesintiden kaç müşteri ve kaç abonelik gerçekten etkilendi?',
  'CE-MCR-0010 olayında ana bağlantı down ve yedek bağlantı active. Bu tam kesinti mi?',
  '6 Haziran 2026 tarihinde Konak ilçesinde kaç kesinti yaşandı?',
]

type Lifecycle = 'idle' | 'submitting' | 'success' | 'clarification' | 'failed'

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
            <label>LLM provider<select value={llmProvider} onChange={(event) => setLlmProvider(event.target.value as ProviderName)}><option value="ollama">Local Gemma</option><option value="gemini">Gemini</option></select></label>
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

      {result?.response && <section className="analysis-result" aria-live="polite"><div className="analysis-result__meta"><span>QueryRun {result.query_run_code}</span><span>{result.response.provider} / {result.response.model}</span><span>{viewMode === 'technical' ? 'Teknik görünüm' : 'Yönetim görünümü'}</span></div><h2>Yanıt</h2><p>{result.response.response_text}</p>{result.response.warnings?.length ? <p className="analysis-message">Uyarı: {result.response.warnings.join(', ')}</p> : null}</section>}
      {result?.clarification && <section className="analysis-result analysis-result--clarification" aria-live="polite"><h2>Ek bilgi gerekiyor</h2><p>{result.clarification.message}</p><button type="button" onClick={() => setLifecycle('idle')}>Soruyu düzenle</button></section>}
    </section>
  )
}
