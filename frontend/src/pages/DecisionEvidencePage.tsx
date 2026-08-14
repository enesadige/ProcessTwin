import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { ApiRequestError, getDecisionEvidence, type DecisionEvidenceDetail } from '../auth/api'
import './DecisionEvidencePage.css'

function DetailList({ title, values }: { title: string; values: unknown[] }) {
  if (!values.length) return null
  return <section className="evidence-detail__section"><h2>{title}</h2><ul>{values.map((value, index) => <li key={index}>{typeof value === 'string' ? value : JSON.stringify(value)}</li>)}</ul></section>
}

export function DecisionEvidencePage() {
  const [searchParams] = useSearchParams()
  const evidenceHash = searchParams.get('evidence_hash')?.trim() ?? ''
  const snapshotIdentifier = searchParams.get('snapshot_identifier')?.trim() ?? ''
  const [detail, setDetail] = useState<DecisionEvidenceDetail | null>(null)
  const [snapshotKey, setSnapshotKey] = useState('')
  const [state, setState] = useState<'loading' | 'ready' | 'missing' | 'access' | 'retryable'>('loading')

  const load = useCallback(async () => {
    if (!evidenceHash || !snapshotIdentifier) {
      setState('missing')
      return
    }
    setState('loading')
    try {
      const { snapshot_key, decision_evidence } = await getDecisionEvidence({ snapshotIdentifier, evidenceHash })
      setSnapshotKey(snapshot_key)
      setDetail(decision_evidence)
      setState('ready')
    } catch (reason) {
      if (reason instanceof ApiRequestError && (reason.status === 401 || reason.status === 403)) setState('access')
      else if (reason instanceof ApiRequestError && reason.status === 404) setState('missing')
      else setState('retryable')
    }
  }, [evidenceHash, snapshotIdentifier])

  useEffect(() => {
    void load()
  }, [load])

  if (state === 'loading') return <section className="evidence-detail"><p className="evidence-detail__eyebrow">Governance</p><h1>Decision Evidence</h1><p className="evidence-detail__message">Kanıt kaydı yükleniyor.</p></section>
  if (state === 'access') return <section className="evidence-detail"><p className="evidence-detail__eyebrow">Governance</p><h1>Decision Evidence</h1><p className="evidence-detail__message" role="alert">Bu kanıt kaydını görüntüleme yetkiniz yok.</p><Link to="/login">Oturuma git</Link></section>
  if (state === 'retryable') return <section className="evidence-detail"><p className="evidence-detail__eyebrow">Governance</p><h1>Decision Evidence</h1><p className="evidence-detail__message" role="alert">Kanıt kaydı geçici olarak yüklenemedi.</p><button type="button" onClick={() => void load()}>Tekrar dene</button><Link to="/ai-analysis">AI Analysis’e dön</Link></section>
  if (state === 'missing' || !detail) return <section className="evidence-detail"><p className="evidence-detail__eyebrow">Governance</p><h1>Decision Evidence</h1><p className="evidence-detail__message">Kanıt kaydı bulunamadı veya seçili snapshot’a ait değil.</p><Link to="/ai-analysis">AI Analysis’e dön</Link></section>

  const evaluation = detail.compensation_evaluation
  const selectedRule = detail.selected_rule_version
  return <section className="evidence-detail" aria-labelledby="decision-evidence-title">
    <header className="evidence-detail__header"><div><p className="evidence-detail__eyebrow">Snapshot-local governance kaydı</p><h1 id="decision-evidence-title">Decision Evidence</h1><p>{snapshotKey}</p></div><Link to="/ai-analysis">AI Analysis’e dön</Link></header>
    <section className="evidence-detail__summary">
      <div><span>Evidence hash</span><strong>{detail.evidence_hash}</strong></div>
      <div><span>Karar</span><strong>{detail.decision}</strong></div>
      <div><span>Durum</span><strong>{detail.finalized ? 'Finalized' : 'Taslak'}</strong></div>
      {selectedRule?.rule_code ? <div><span>Seçilmiş RuleVersion</span><strong>{selectedRule.rule_code}{selectedRule.version !== undefined ? ` v${selectedRule.version}` : ''}</strong></div> : null}
      {evaluation ? <div><span>Değerlendirme / kesinti</span><strong>{evaluation.evaluation_code} / {evaluation.outage_code}</strong></div> : null}
      {detail.final_amount ? <div><span>Tutar</span><strong>{detail.final_amount} {detail.currency}</strong></div> : null}
    </section>
    {evaluation ? <section className="evidence-detail__section"><h2>Bağlı değerlendirme</h2><dl><dt>Sonuç</dt><dd>{evaluation.result_type}</dd><dt>Durum</dt><dd>{evaluation.status}</dd></dl></section> : null}
    <DetailList title="Eşleşen koşullar" values={detail.matched_conditions} />
    <DetailList title="Başarısız koşullar" values={detail.failed_conditions} />
    <DetailList title="Hariç tutulan kurallar" values={detail.excluded_rules} />
    <DetailList title="Uygulanan modifier’lar" values={detail.applied_modifiers} />
    <DetailList title="Manuel inceleme nedenleri" values={detail.manual_review_reasons} />
  </section>
}
