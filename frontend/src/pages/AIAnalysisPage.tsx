import { useState } from 'react'

import { useAuth } from '../auth/AuthContext'
import { AnalysisRequestError, submitAnalysis, type ProviderName, type ViewMode } from '../auth/api'
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

  async function submit() {
    const trimmed = query.trim()
    if (!trimmed || lifecycle === 'submitting') return
    setLifecycle('submitting')
    setError('')
    setResult(null)
    try {
      const response = await submitAnalysis({
        snapshot_identifier: SNAPSHOT_IDENTIFIER,
        idempotency_key: crypto.randomUUID(),
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

      {result?.response && <section className="analysis-result" aria-live="polite"><div className="analysis-result__meta"><span>QueryRun {result.query_run_code}</span><span>{result.response.provider} / {result.response.model}</span><span>{viewMode === 'technical' ? 'Teknik görünüm' : 'Yönetim görünümü'}</span></div><h2>Yanıt</h2><p>{result.response.response_text}</p>{result.response.warnings?.length ? <p className="analysis-message">Uyarı: {result.response.warnings.join(', ')}</p> : null}</section>}
      {result?.clarification && <section className="analysis-result analysis-result--clarification" aria-live="polite"><h2>Ek bilgi gerekiyor</h2><p>{result.clarification.message}</p><button type="button" onClick={() => setLifecycle('idle')}>Soruyu düzenle</button></section>}
    </section>
  )
}
