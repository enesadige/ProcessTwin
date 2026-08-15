import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import {
  ApiRequestError,
  getDecisionEvidence,
  getEvidenceRecordDetail,
  type DecisionEvidenceDetail,
  type EvidenceRecordDetail,
} from '../auth/api'
import './DecisionEvidencePage.css'

function DetailList({ title, values }: { title: string; values: unknown[] }) {
  if (!values.length) return null
  return <section className="evidence-detail__section"><h2>{title}</h2><ul>{values.map((value, index) => <li key={index}>{formatSafeValue(value)}</li>)}</ul></section>
}

function formatSafeValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'Belirtilmedi'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return value.map(formatSafeValue).join(', ')
  if (typeof value === 'object') return `${Object.keys(value).length} doğrulanmış alan`
  return 'Belirtilmedi'
}

function DetailPairs({ values }: { values: Record<string, unknown> }) {
  const entries = Object.entries(values).filter(([, value]) => value !== null && value !== undefined && value !== '')
  if (!entries.length) return null
  return <dl className="evidence-detail__pairs">{entries.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{formatSafeValue(value)}</dd></div>)}</dl>
}

function GeneralEvidenceDetailView({ detail }: { detail: EvidenceRecordDetail }) {
  return <>
    <section className="evidence-detail__summary">
      <div><span>Evidence code</span><strong>{detail.evidence_code}</strong></div>
      <div><span>QueryRun</span><strong>{detail.query_run.code}</strong></div>
      <div><span>Terminal durum</span><strong>{detail.query_run.terminal_status}</strong></div>
      <div><span>Snapshot</span><strong>{detail.snapshot.key}</strong></div>
      <div><span>Finalization</span><strong>{detail.finalized_at ?? 'Finalized'}</strong></div>
    </section>
    {Object.keys(detail.provenance).length ? <section className="evidence-detail__section"><h2>Çalışma provenance’i</h2><DetailPairs values={detail.provenance} /></section> : null}
    {detail.tool_timeline.length ? <section className="evidence-detail__section"><h2>Tool zaman çizelgesi</h2><ol className="evidence-detail__timeline">{detail.tool_timeline.map((tool) => <li key={tool.sequence}><div className="evidence-detail__timeline-header"><strong>{tool.sequence}. {tool.tool_name}</strong><span>{tool.status}</span></div><dl><dt>MCP/server</dt><dd>{tool.server}</dd><dt>Deneme</dt><dd>{tool.attempt_count ?? 'Belirtilmedi'}</dd><dt>Süre</dt><dd>{tool.duration_ms === null ? 'Belirtilmedi' : `${tool.duration_ms} ms`}</dd>{tool.result_summary ? <><dt>Güvenli sonuç özeti</dt><dd>{formatSafeValue(tool.result_summary)}</dd></> : null}{tool.error_code ? <><dt>Hata kodu</dt><dd>{tool.error_code}</dd></> : null}</dl></li>)}</ol></section> : null}
    {detail.calculations.length ? <section className="evidence-detail__section"><h2>Deterministic hesaplamalar</h2><div className="evidence-detail__record-list">{detail.calculations.map((calculation) => <article key={calculation.sequence}><h3>{calculation.sequence}. {calculation.calculation_code}</h3><h4>Girdiler</h4><DetailPairs values={calculation.inputs} /><h4>Çıktılar</h4><DetailPairs values={calculation.outputs} /></article>)}</div></section> : null}
    {detail.rule_references.length ? <section className="evidence-detail__section"><h2>Seçilmiş RuleVersion referansları</h2><ul>{detail.rule_references.map((rule) => <li key={`${rule.rule_code}-${rule.version}-${rule.reference_role}`}><strong>{rule.rule_code} v{rule.version}</strong> · {rule.reference_role}</li>)}</ul></section> : null}
    {detail.rag_references.length ? <section className="evidence-detail__section"><h2>RAG retrieval kaynakları</h2><p className="evidence-detail__hint">Bu kaynaklar retrieval/citation provenance’idir; operasyonel sayı veya karar hesabını üretmez.</p><ul>{detail.rag_references.map((source, index) => <li key={`${source.document_code}-${source.document_version}-${index}`}><strong>{source.document_code} v{source.document_version}</strong>{source.chunk_heading ? ` · ${source.chunk_heading}` : ''}{source.section_path.length ? ` · ${source.section_path.join(' / ')}` : ''}{source.retrieval_score === null ? '' : ` · skor ${source.retrieval_score}`}</li>)}</ul></section> : null}
    <DetailList title="Uyarılar" values={detail.warnings} />
  </>
}

export function DecisionEvidencePage() {
  const [searchParams] = useSearchParams()
  const evidenceHash = searchParams.get('evidence_hash')?.trim() ?? ''
  const evidenceCode = searchParams.get('evidence_code')?.trim() ?? ''
  const snapshotIdentifier = searchParams.get('snapshot_identifier')?.trim() ?? ''
  const [decisionDetail, setDecisionDetail] = useState<DecisionEvidenceDetail | null>(null)
  const [generalDetail, setGeneralDetail] = useState<EvidenceRecordDetail | null>(null)
  const [snapshotKey, setSnapshotKey] = useState('')
  const [state, setState] = useState<'loading' | 'ready' | 'missing' | 'access' | 'retryable'>('loading')
  const evidenceKind = evidenceHash && !evidenceCode ? 'compensation' : evidenceCode && !evidenceHash ? 'general' : null

  const load = useCallback(async () => {
    if (!evidenceKind || !snapshotIdentifier) {
      setState('missing')
      return
    }
    setState('loading')
    setDecisionDetail(null)
    setGeneralDetail(null)
    try {
      if (evidenceKind === 'compensation') {
        const { snapshot_key, decision_evidence } = await getDecisionEvidence({ snapshotIdentifier, evidenceHash })
        setSnapshotKey(snapshot_key)
        setDecisionDetail(decision_evidence)
      } else {
        const evidence = await getEvidenceRecordDetail({ snapshotIdentifier, evidenceCode })
        setSnapshotKey(evidence.snapshot.key)
        setGeneralDetail(evidence)
      }
      setState('ready')
    } catch (reason) {
      if (reason instanceof ApiRequestError && (reason.status === 401 || reason.status === 403)) setState('access')
      else if (reason instanceof ApiRequestError && reason.status === 404) setState('missing')
      else setState('retryable')
    }
  }, [evidenceCode, evidenceHash, evidenceKind, snapshotIdentifier])

  useEffect(() => {
    void load()
  }, [load])

  const title = evidenceKind === 'general' ? 'Execution Evidence' : 'Decision Evidence'
  if (state === 'loading') return <section className="evidence-detail"><p className="evidence-detail__eyebrow">Governance</p><h1>{title}</h1><p className="evidence-detail__message" aria-live="polite">Kanıt kaydı yükleniyor.</p></section>
  if (state === 'access') return <section className="evidence-detail"><p className="evidence-detail__eyebrow">Governance</p><h1>{title}</h1><p className="evidence-detail__message" role="alert">Bu kanıt kaydını görüntüleme yetkiniz yok.</p><Link to="/login">Oturuma git</Link></section>
  if (state === 'retryable') return <section className="evidence-detail"><p className="evidence-detail__eyebrow">Governance</p><h1>{title}</h1><p className="evidence-detail__message" role="alert">Kanıt kaydı geçici olarak yüklenemedi.</p><button type="button" onClick={() => void load()}>Tekrar dene</button><Link to="/ai-analysis">AI Analysis’e dön</Link></section>
  if (state === 'missing' || (!decisionDetail && !generalDetail)) return <section className="evidence-detail"><p className="evidence-detail__eyebrow">Governance</p><h1>{title}</h1><p className="evidence-detail__message" role="alert">Kanıt kaydı bulunamadı veya seçili snapshot’a ait değil.</p><Link to="/ai-analysis">AI Analysis’e dön</Link></section>

  const evaluation = decisionDetail?.compensation_evaluation
  const selectedRule = decisionDetail?.selected_rule_version
  return <section className="evidence-detail" aria-labelledby="decision-evidence-title">
    <header className="evidence-detail__header"><div><p className="evidence-detail__eyebrow">Snapshot-local governance kaydı</p><h1 id="decision-evidence-title">{title}</h1><p>{snapshotKey}</p></div><Link to="/ai-analysis">AI Analysis’e dön</Link></header>
    {generalDetail ? <GeneralEvidenceDetailView detail={generalDetail} /> : <>
      <section className="evidence-detail__summary">
        <div><span>Evidence hash</span><strong>{decisionDetail?.evidence_hash}</strong></div>
        <div><span>Karar</span><strong>{decisionDetail?.decision}</strong></div>
        <div><span>Durum</span><strong>{decisionDetail?.finalized ? 'Finalized' : 'Taslak'}</strong></div>
        {selectedRule?.rule_code ? <div><span>Seçilmiş RuleVersion</span><strong>{selectedRule.rule_code}{selectedRule.version !== undefined ? ` v${selectedRule.version}` : ''}</strong></div> : null}
        {evaluation ? <div><span>Değerlendirme / kesinti</span><strong>{evaluation.evaluation_code} / {evaluation.outage_code}</strong></div> : null}
        {decisionDetail?.final_amount ? <div><span>Tutar</span><strong>{decisionDetail.final_amount} {decisionDetail.currency}</strong></div> : null}
      </section>
      {evaluation ? <section className="evidence-detail__section"><h2>Bağlı değerlendirme</h2><dl><dt>Sonuç</dt><dd>{evaluation.result_type}</dd><dt>Durum</dt><dd>{evaluation.status}</dd></dl></section> : null}
      <DetailList title="Eşleşen koşullar" values={decisionDetail?.matched_conditions ?? []} />
      <DetailList title="Başarısız koşullar" values={decisionDetail?.failed_conditions ?? []} />
      <DetailList title="Hariç tutulan kurallar" values={decisionDetail?.excluded_rules ?? []} />
      <DetailList title="Uygulanan modifier’lar" values={decisionDetail?.applied_modifiers ?? []} />
      <DetailList title="Manuel inceleme nedenleri" values={decisionDetail?.manual_review_reasons ?? []} />
    </>}
  </section>
}
