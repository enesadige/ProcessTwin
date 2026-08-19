import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import {
  ApiRequestError,
  getDecisionEvidence,
  getEvidenceRecordDetail,
  getEvidenceRecordList,
  type DecisionEvidenceDetail,
  type EvidenceRecordDetail,
  type EvidenceRecordListItem,
} from '../auth/api'
import './DecisionEvidencePage.css'

function DetailList({ title, values }: { title: string; values: unknown[] }) {
  if (!values.length) return null
  return <section className="evidence-detail__section"><h2>{title}</h2><ul>{values.map((value, index) => <li key={index}>{formatSafeValue(value)}</li>)}</ul></section>
}

const DISPLAY_LABELS: Record<string, string> = {
  snapshot_id: 'Snapshot ID', snapshot_key: 'Snapshot anahtarı', query_run_code: 'QueryRun', terminal_status: 'Son durum',
  resolved_llm_model: 'LLM modeli', resolved_llm_provider: 'LLM sağlayıcısı', resolved_embedding_model: 'Embedding modeli',
  resolved_embedding_provider: 'Embedding sağlayıcısı', structured_query_parser: 'Sorgu ayrıştırıcısı',
  structured_query_parser_version: 'Ayrıştırıcı sürümü', result_fingerprint: 'Sonuç parmak izi',
  analytics_summary: 'Analitik özeti', analytics_summaries: 'Analitik özetleri', metric: 'Metrik', filters: 'Filtreler',
  group_by: 'Gruplama', aggregation: 'Hesaplama', rows: 'Sonuç satırları', included_event_count: 'Dahil edilen olay',
  excluded_unknown_count: 'Bilinmeyen olduğu için dışlanan', potential_subscriptions: 'Potansiyel abonelik',
  affected_subscriptions: 'Etkilenen abonelik', affected_customers: 'Etkilenen müşteri', event_count: 'Olay sayısı',
  alarm_count: 'Alarm sayısı', outage_count: 'Kesinti sayısı', full_outage_count: 'Tam kesinti sayısı',
  compensation_amount: 'Telafi tutarı', failed_failover_count: 'Başarısız failover sayısı', city: 'Şehir', count: 'Sayı',
  label: 'Etiket', value: 'Değer', time_grain: 'Zaman düzeyi', time_bucket: 'Zaman dönemi',
  from_time: 'Başlangıç zamanı', to_time: 'Bitiş zamanı', comparison: 'Karşılaştırma', ranking_direction: 'Sıralama yönü',
  trend_direction: 'Eğilim', signed_change: 'Net değişim', absolute_change: 'Mutlak fark',
  deterministic: 'Hesaplama türü', schema_version: 'Şema sürümü', tool_version: 'Araç sürümü', snapshot_identifier: 'Snapshot',
  reason_codes: 'Gerekçe kodları', root_cause_score: 'Kök neden skoru', root_cause_confidence: 'Kök neden güveni',
  causal_event_code: 'Nedensel olay kodu', root_resource_type: 'Kök kaynak türü', root_resource_reference: 'Kök kaynak referansı',
  root_cause_reason_codes: 'Kök neden gerekçe kodları', assessment_record_count: 'Değerlendirme kaydı',
  missing_evidence_categories: 'Eksik kanıt kategorileri', failover_path_diversity_counts: 'Failover yol çeşitliliği',
  root_alarm_types: 'Kök neden alarm türleri', symptom_alarm_types: 'Belirti alarm türleri', event_class: 'Olay sınıfı',
  impact_summary: 'Etki özeti', compensation_summary: 'Telafi özeti', total_amount: 'Toplam tutar', currency: 'Para birimi',
  correlation_status: 'Korelasyon durumu', anchor_event_code: 'Başlangıç olay kodu', candidate_event_code: 'Aday olay kodu',
  time_difference_seconds: 'Zaman farkı', requested_window_seconds: 'İstenen zaman aralığı', within_window: 'Zaman aralığında',
  topology_relation: 'Topoloji ilişkisi', resource_relation: 'Kaynak ilişkisi', event_relation: 'Olay ilişkisi',
  root_symptom_status: 'Kök neden / belirti durumu', evidence_dimensions: 'Kanıt boyutları', role_counts: 'Rol sayıları',
  propagation_summary: 'Yayılım özeti', event_type: 'Olay türü', root_cause_summary: 'Kök neden özeti',
  dying_gasp_classification: 'Dying Gasp sınıflandırması', device_not_active_classification: 'Cihaz etkinlik sınıflandırması',
  primary_status: 'Birincil bağlantı durumu', backup_status: 'Yedek bağlantı durumu', full_outage: 'Tam hizmet kesintisi',
  potential: 'Potansiyel kapsam', verified_impacted: 'Doğrulanmış etki', verified_no_impact: 'Doğrulanmış etkisiz',
  insufficient_evidence: 'Kanıt yetersiz', failover_protected: 'Failover ile korunan', impact_reason_codes: 'Etki gerekçe kodları',
  reason_code_distribution: 'Gerekçe kodu dağılımı', calculation_code: 'Hesaplama türü', inputs: 'Girdiler', outputs: 'Çıktılar',
  affected_customer_count: 'Etkilenen müşteri', affected_subscription_count: 'Etkilenen abonelik',
  potential_scope: 'Potansiyel kapsam', verified_impact: 'Doğrulanmış etki', protected_by_failover: 'Failover ile korunan',
  verified_unaffected: 'Doğrulanmış etkisiz', evidence_insufficient: 'Kanıt yetersiz',
}

const DISPLAY_VALUES: Record<string, string> = {
  completed: 'Tamamlandı', failed: 'Başarısız', pending: 'Beklemede', running: 'Çalışıyor', succeeded: 'Başarılı',
  SUCCEEDED: 'Başarılı', deterministic: 'Deterministik', potential_subscriptions: 'Potansiyel abonelik',
  affected_subscriptions: 'Etkilenen abonelik', affected_customers: 'Etkilenen müşteri', event_count: 'Olay sayısı',
  alarm_count: 'Alarm sayısı', outage_count: 'Kesinti sayısı', full_outage_count: 'Tam kesinti sayısı',
  compensation_amount: 'Telafi tutarı', failed_failover_count: 'Başarısız failover sayısı', city: 'Şehir', count: 'Sayı',
  failure_domain: 'Arıza alanı', same_resource: 'Aynı kaynak', temporal_propagation: 'Zamansal yayılım',
  shared_failure_domain: 'Ortak arıza alanı', root_cause_unverified: 'Kök neden doğrulanmadı', evidence_gap: 'Kanıt eksikliği',
  shared_upstream: 'Ortak üst bağlantı', shared_risk: 'Paylaşılan risk', failover_protected: 'Failover ile korunan',
  customer_impact_assessment: 'Müşteri etki değerlendirmesi', device: 'Cihaz', subscription_connection: 'Abonelik bağlantısı',
  increased: 'Arttı', decreased: 'Azaldı', increase: 'Arttı', decrease: 'Azaldı', unchanged: 'Değişmedi',
  verified_relation: 'Doğrulanmış ilişki', no_relation: 'İlişki bulunamadı', insufficient_evidence: 'Kanıt yetersiz',
  primary_active: 'Birincil aktif', backup_active: 'Yedek aktif', active: 'Aktif', inactive: 'Aktif değil',
  calculated: 'Hesaplandı', eligible: 'Uygun', ineligible: 'Uygun değil', manual_review: 'Manuel inceleme',
  draft: 'Taslak', finalized: 'Kesinleşti', selected: 'Seçili', referenced: 'Referans',
}

const TOOL_LABELS: Record<string, string> = {
  analyze_operational_analytics: 'Operasyon analitiği', correlate_alarms: 'Alarm korelasyonu',
  rank_root_cause_candidates: 'Kök neden adaylarını sıralama', get_outage: 'Kesinti kaydını getir',
  get_outage_details: 'Kesinti ayrıntılarını getir', evaluate_outage: 'Telafi değerlendirmesi',
  aggregate_location_impact: 'Konum bazlı etki özeti', get_device_details: 'Cihaz ayrıntılarını getir',
  get_device_topology: 'Cihaz topolojisini getir', search_alarms: 'Alarmları ara', search_outages: 'Kesintileri ara',
  calculate_customer_impact: 'Müşteri etkisini hesapla', correlate_causal_events: 'Nedensel olay korelasyonu',
  get_longest_outage: 'En uzun kesintileri getir', evaluate_refund_eligibility: 'Telafi uygunluğunu değerlendir',
  calculate_refund_amount: 'Telafi tutarını hesapla', evaluate_compensation_options: 'Telafi seçeneklerini değerlendir',
  check_campaign_eligibility: 'Kampanya uygunluğunu kontrol et', rank_compensation_options: 'Telafi seçeneklerini sırala',
  get_compensation_evidence: 'Telafi kanıtını getir', get_customer_profile: 'Müşteri profilini getir',
  get_customer_subscription: 'Müşteri aboneliğini getir', get_customer_payment_status: 'Ödeme durumunu getir',
  get_customer_outage_history: 'Kesinti geçmişini getir', get_customer_compensation_history: 'Telafi geçmişini getir',
  list_customers_by_device: 'Cihaza bağlı müşterileri listele', list_customers_by_location: 'Konuma göre müşterileri listele',
  search_rules: 'Kuralları ara', get_rule: 'Kuralı getir', get_rules_effective_at: 'Geçerli kuralları getir',
  get_rule_version_history: 'Kural sürüm geçmişini getir', find_related_rules: 'İlişkili kuralları bul',
  detect_rule_conflicts: 'Kural çakışmalarını tespit et', get_rule_evidence: 'Kural kanıtını getir',
  search_rule_documents: 'Kural belgelerini ara',
}

const SERVER_LABELS: Record<string, string> = {
  network: 'Network MCP', compensation: 'Compensation MCP', customer: 'Customer MCP', rules: 'Rules MCP', simulation: 'Simulation MCP',
}

function formatDisplayLabel(key: string): string {
  return DISPLAY_LABELS[key] ?? key.replaceAll('_', ' ')
}

function formatToolName(toolName: string): string {
  return TOOL_LABELS[toolName] ?? toolName.replaceAll('_', ' ')
}

function formatServerName(server: string): string {
  return SERVER_LABELS[server] ?? server.replaceAll('_', ' ')
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return 'Belirtilmedi'
  const timestamp = new Date(value)
  if (Number.isNaN(timestamp.getTime())) return value
  return new Intl.DateTimeFormat('tr-TR', { dateStyle: 'medium', timeStyle: 'short' }).format(timestamp)
}

function isTimestamp(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}T/.test(value) && !Number.isNaN(new Date(value).getTime())
}

function hasPresentationValue(value: unknown): boolean {
  if (value === null || value === undefined || value === '') return false
  if (Array.isArray(value)) return value.some(hasPresentationValue)
  if (typeof value === 'object') return Object.values(value).some(hasPresentationValue)
  return true
}

function formatSafeValue(value: unknown, fieldKey?: string): string {
  if (value === null || value === undefined || value === '') return 'Belirtilmedi'
  if (typeof value === 'string') return isTimestamp(value) ? formatTimestamp(value) : DISPLAY_VALUES[value] ?? value
  if (typeof value === 'boolean') return fieldKey === 'deterministic' ? (value ? 'Deterministik' : 'Deterministik değil') : (value ? 'Evet' : 'Hayır')
  if (typeof value === 'number') return String(value)
  if (Array.isArray(value)) return value.map((item) => formatSafeValue(item)).join(', ')
  if (typeof value === 'object') return `${Object.keys(value).length} doğrulanmış alan`
  return 'Belirtilmedi'
}

function formatTerminalStatus(status: string): string {
  return DISPLAY_VALUES[status] ?? ({ planned: 'Planlandı', executing: 'İşleniyor' }[status] ?? status)
}

function DisplayValue({ value, fieldKey }: { value: unknown; fieldKey?: string }): ReactNode {
  if (Array.isArray(value)) {
    const items = value.filter(hasPresentationValue)
    if (!items.length) return null
    return <ul className="evidence-detail__value-list">{items.map((item, index) => <li key={index}><DisplayValue value={item} /></li>)}</ul>
  }
  if (value && typeof value === 'object') {
    const entries = Object.entries(value).filter(([, nestedValue]) => hasPresentationValue(nestedValue))
    if (!entries.length) return null
    return <dl className="evidence-detail__nested-pairs">{entries.map(([key, nestedValue]) => <div key={key}><dt>{formatDisplayLabel(key)}</dt><dd><DisplayValue value={nestedValue} fieldKey={key} /></dd></div>)}</dl>
  }
  const formatted = formatSafeValue(value, fieldKey)
  return typeof value === 'string' && isTimestamp(value) ? <time dateTime={value} title={value}>{formatted}</time> : formatted
}

function DetailPairs({ values }: { values: Record<string, unknown> }) {
  const entries = Object.entries(values).filter(([, value]) => hasPresentationValue(value))
  if (!entries.length) return null
  return <dl className="evidence-detail__pairs">{entries.map(([key, value]) => <div key={key}><dt>{formatDisplayLabel(key)}</dt><dd><DisplayValue value={value} fieldKey={key} /></dd></div>)}</dl>
}

function ProvenanceCard({
  title,
  image,
  fields,
  isActive,
  onActivate,
}: {
  title: string
  image: string
  fields: Array<[string, unknown]>
  isActive: boolean
  onActivate: () => void
}) {
  return <article
    className={isActive ? 'evidence-provenance__card evidence-provenance__card--active' : 'evidence-provenance__card'}
    role="button"
    tabIndex={0}
    aria-pressed={isActive}
    onClick={onActivate}
    onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onActivate() } }}
  >
    <img src={image} alt="" className="evidence-provenance__image" />
    <div className="evidence-provenance__content">
      <h3>{title}</h3>
      <dl>{fields.map(([key, value]) => <div key={key}><dt>{formatDisplayLabel(key)}</dt><dd><DisplayValue value={value} fieldKey={key} /></dd></div>)}</dl>
    </div>
  </article>
}

function ToolResultSummary({ value }: { value: unknown }) {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return <DetailPairs values={value as Record<string, unknown>} />
  }
  return <div className="evidence-detail__tool-summary-value"><DisplayValue value={value} /></div>
}

function stablePayload(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stablePayload).join(',')}]`
  if (value && typeof value === 'object') return `{${Object.entries(value).sort(([left], [right]) => left.localeCompare(right)).map(([key, nested]) => `${key}:${stablePayload(nested)}`).join(',')}}`
  return JSON.stringify(value)
}

function dedupeAnalyticsCalculations(calculations: EvidenceRecordDetail['calculations']): EvidenceRecordDetail['calculations'] {
  const seenAnalytics = new Set<string>()
  return calculations.filter((calculation) => {
    if (!calculation.calculation_code.startsWith('analytics_')) return true
    const fingerprint = stablePayload({ inputs: calculation.inputs, outputs: calculation.outputs })
    if (seenAnalytics.has(fingerprint)) return false
    seenAnalytics.add(fingerprint)
    return true
  })
}

function GeneralEvidenceDetailView({ detail }: { detail: EvidenceRecordDetail }) {
  const calculations = dedupeAnalyticsCalculations(detail.calculations)
  const provenance = detail.provenance
  const [activeProvenance, setActiveProvenance] = useState<'llm' | 'embedding' | 'parser'>('llm')
  const [activeDetailSection, setActiveDetailSection] = useState<'provenance' | 'timeline' | 'calculations'>('provenance')
  const detailSections = [
    { id: 'provenance' as const, label: 'Çalışma izlenebilirliği', available: Object.keys(provenance).length > 0, icon: 'provenance' },
    { id: 'timeline' as const, label: 'İşlem adımları', available: detail.tool_timeline.length > 0, icon: 'timeline' },
    { id: 'calculations' as const, label: 'Deterministik hesaplamalar', available: calculations.length > 0, icon: 'calculations' },
  ]
  const selectedDetailSection = detailSections.some((section) => section.id === activeDetailSection && section.available)
    ? activeDetailSection
    : detailSections.find((section) => section.available)?.id
  return <>
    <section className="evidence-detail__summary">
      <div><span>Kanıt kodu</span><strong>{detail.evidence_code}</strong></div>
      <div><span>QueryRun</span><strong>{detail.query_run.code}</strong></div>
      <div><span>Son durum</span><strong>{formatTerminalStatus(detail.query_run.terminal_status)}</strong></div>
      <div><span>Kesinleşme</span><strong>{detail.finalized_at ? <time dateTime={detail.finalized_at} title={detail.finalized_at}>{formatTimestamp(detail.finalized_at)}</time> : 'Belirtilmedi'}</strong></div>
    </section>
    {detailSections.some((section) => section.available) ? <nav className="evidence-detail__navigator" aria-label="Kanıt ayrıntıları bölümleri">{detailSections.map((section) => <button type="button" key={section.id} className={selectedDetailSection === section.id ? 'is-active' : ''} disabled={!section.available} aria-pressed={selectedDetailSection === section.id} onClick={() => setActiveDetailSection(section.id)}><span className={`evidence-detail__navigator-icon evidence-detail__navigator-icon--${section.icon}`} aria-hidden="true" /><span>{section.label}</span></button>)}</nav> : null}
    {selectedDetailSection === 'provenance' && Object.keys(provenance).length ? <section className="evidence-detail__section evidence-detail__primary-panel evidence-provenance"><h2>Çalışma izlenebilirliği</h2><div className="evidence-provenance__grid">
      <ProvenanceCard title="LLM" image="/evidence-llm.png" fields={[
        ['resolved_llm_provider', provenance.resolved_llm_provider],
        ['resolved_llm_model', provenance.resolved_llm_model],
      ]} isActive={activeProvenance === 'llm'} onActivate={() => setActiveProvenance('llm')} />
      <ProvenanceCard title="Embedding" image="/evidence-embedding.png" fields={[
        ['resolved_embedding_provider', provenance.resolved_embedding_provider],
        ['resolved_embedding_model', provenance.resolved_embedding_model],
      ]} isActive={activeProvenance === 'embedding'} onActivate={() => setActiveProvenance('embedding')} />
      <ProvenanceCard title="Sorgu ayrıştırıcısı" image="/evidence-parser.png" fields={[
        ['structured_query_parser', provenance.structured_query_parser],
        ['structured_query_parser_version', provenance.structured_query_parser_version],
      ]} isActive={activeProvenance === 'parser'} onActivate={() => setActiveProvenance('parser')} />
    </div></section> : null}
    {selectedDetailSection === 'timeline' && detail.tool_timeline.length ? <section className="evidence-detail__section evidence-detail__primary-panel"><h2>İşlem adımları</h2><ol className="evidence-detail__timeline">{detail.tool_timeline.map((tool) => <li key={tool.sequence}>
      <div className="evidence-detail__timeline-header"><strong>{tool.sequence}. İşlem: {formatToolName(tool.tool_name)}</strong></div>
      <div className="evidence-detail__tool-meta"><p><span>MCP sunucusu:</span> {formatServerName(tool.server)}</p><p><span>Araç:</span> {formatToolName(tool.tool_name)} <code>({tool.tool_name})</code></p></div>
      <div className="evidence-detail__tool-statuses"><div><span>Durum</span><strong>{formatTerminalStatus(tool.status)}</strong></div><div><span>Deneme</span><strong>{tool.attempt_count ?? 'Belirtilmedi'}</strong></div><div><span>Süre</span><strong>{tool.duration_ms === null ? 'Belirtilmedi' : `${tool.duration_ms} ms`}</strong></div></div>
      {tool.result_summary ? <section className="evidence-detail__tool-summary"><h3>Doğrulanmış sonuç özeti</h3><ToolResultSummary value={tool.result_summary} /></section> : null}
      {tool.error_code ? <p className="evidence-detail__tool-error"><span>Hata kodu:</span> {tool.error_code}</p> : null}
    </li>)}</ol></section> : null}
    {selectedDetailSection === 'calculations' && calculations.length ? <section className="evidence-detail__section evidence-detail__primary-panel evidence-detail__calculations"><h2>Deterministik hesaplamalar</h2><div className="evidence-detail__calculation-list">{calculations.map((calculation) => <article className="evidence-detail__calculation-card" key={calculation.sequence}><h3>{calculation.sequence}. {formatDisplayLabel(calculation.calculation_code)}</h3>{hasPresentationValue(calculation.inputs) ? <section className="evidence-detail__calculation-inputs"><h4>Girdiler</h4><DetailPairs values={calculation.inputs} /></section> : null}{hasPresentationValue(calculation.outputs) ? <section className="evidence-detail__calculation-outputs"><h4>Çıktılar</h4><DetailPairs values={calculation.outputs} /></section> : null}</article>)}</div></section> : null}
    {detail.rule_references.length ? <section className="evidence-detail__section"><h2>Seçilmiş RuleVersion referansları</h2><ul>{detail.rule_references.map((rule) => <li key={`${rule.rule_code}-${rule.version}-${rule.reference_role}`}><strong>{rule.rule_code} v{rule.version}</strong> · {formatSafeValue(rule.reference_role)}</li>)}</ul></section> : null}
    {detail.rag_references.length ? <section className="evidence-detail__section"><h2>RAG erişim kaynakları</h2><p className="evidence-detail__hint">Bu kaynaklar erişim ve alıntı izlenebilirliği içindir; operasyonel sayı veya karar hesabını üretmez.</p><ul>{detail.rag_references.map((source, index) => <li key={`${source.document_code}-${source.document_version}-${index}`}><strong>{source.document_code} v{source.document_version}</strong>{source.chunk_heading ? ` · ${source.chunk_heading}` : ''}{source.section_path.length ? ` · ${source.section_path.join(' / ')}` : ''}{source.retrieval_score === null ? '' : ` · skor ${source.retrieval_score}`}</li>)}</ul></section> : null}
    <DetailList title="Uyarılar" values={detail.warnings} />
  </>
}

function GeneralEvidenceListView({ records }: { records: EvidenceRecordListItem[] }) {
  const [draftFilters, setDraftFilters] = useState({ query: '', finalizedOn: '', status: '' })
  const [activeFilters, setActiveFilters] = useState({ query: '', finalizedOn: '', status: '' })
  const availableStatuses = [...new Set(records.map((record) => record.query_run.terminal_status))].sort()
  const filteredRecords = records.filter((record) => {
    const query = activeFilters.query.trim().toLowerCase()
    const matchesQuery = !query || record.evidence_code.toLowerCase().includes(query)
    const matchesDate = !activeFilters.finalizedOn || record.finalized_at?.startsWith(activeFilters.finalizedOn)
    const matchesStatus = !activeFilters.status || record.query_run.terminal_status === activeFilters.status
    return matchesQuery && matchesDate && matchesStatus
  })

  if (!records.length) {
    return <section className="evidence-index__surface evidence-index__surface--empty"><h2 className="evidence-index__badge">Kanıt kayıtları</h2><p className="evidence-detail__message">Henüz kesinleşen bir kanıt kaydı bulunmuyor.</p></section>
  }
  return <section className="evidence-index__surface" aria-labelledby="evidence-records-title">
    <h2 id="evidence-records-title" className="evidence-index__badge">Son kesinleşen kanıt kayıtları</h2>
    <form className="evidence-index__filters" onSubmit={(event) => { event.preventDefault(); setActiveFilters(draftFilters) }}>
      <label className="evidence-index__search"><span className="sr-only">Kanıt kodunda ara</span><input value={draftFilters.query} onChange={(event) => setDraftFilters((current) => ({ ...current, query: event.target.value }))} placeholder="Kanıt kodunda ara" /></label>
      <label className="evidence-index__filter"><span>Kesinleşme</span><input type="date" value={draftFilters.finalizedOn} onChange={(event) => setDraftFilters((current) => ({ ...current, finalizedOn: event.target.value }))} /></label>
      <label className="evidence-index__filter"><span>Durum</span><select value={draftFilters.status} onChange={(event) => setDraftFilters((current) => ({ ...current, status: event.target.value }))}><option value="">Tümü</option>{availableStatuses.map((status) => <option key={status} value={status}>{formatTerminalStatus(status)}</option>)}</select></label>
      <div className="evidence-index__filter-actions"><button type="button" onClick={() => { const empty = { query: '', finalizedOn: '', status: '' }; setDraftFilters(empty); setActiveFilters(empty) }}>Sıfırla</button><button type="submit">Filtrele</button></div>
    </form>
    {filteredRecords.length ? <ul className="evidence-detail__index">{filteredRecords.map((record) => {
    const params = new URLSearchParams({ evidence_code: record.evidence_code, snapshot_identifier: record.snapshot.key })
    return <li key={record.evidence_code}><Link to={`/evidence?${params}`}><div className="evidence-detail__index-heading"><strong>{record.evidence_code}</strong></div><div className="evidence-detail__index-meta"><span>QueryRun: {record.query_run.code}</span><span>Durum: {formatTerminalStatus(record.query_run.terminal_status)}</span><span>Kesinleşme: {formatTimestamp(record.finalized_at)}</span></div><span className="evidence-detail__index-action">Kanıt kaydını aç</span></Link></li>
  })}</ul> : <p className="evidence-index__no-results">Bu filtrelerle eşleşen bir kanıt kaydı bulunmuyor.</p>}
  </section>
}

export function DecisionEvidencePage() {
  const [searchParams] = useSearchParams()
  const evidenceHash = searchParams.get('evidence_hash')?.trim() ?? ''
  const evidenceCode = searchParams.get('evidence_code')?.trim() ?? ''
  const snapshotIdentifier = searchParams.get('snapshot_identifier')?.trim() ?? ''
  const [decisionDetail, setDecisionDetail] = useState<DecisionEvidenceDetail | null>(null)
  const [generalDetail, setGeneralDetail] = useState<EvidenceRecordDetail | null>(null)
  const [generalRecords, setGeneralRecords] = useState<EvidenceRecordListItem[]>([])
  const [snapshotKey, setSnapshotKey] = useState('')
  const [state, setState] = useState<'loading' | 'ready' | 'missing' | 'access' | 'retryable'>('loading')
  const evidenceKind = evidenceHash && !evidenceCode ? 'compensation' : evidenceCode && !evidenceHash ? 'general' : null
  const isGeneralIndex = !evidenceHash && !evidenceCode && !snapshotIdentifier

  const load = useCallback(async () => {
    if (isGeneralIndex) {
      setState('loading')
      setDecisionDetail(null)
      setGeneralDetail(null)
      try {
        setGeneralRecords(await getEvidenceRecordList())
        setState('ready')
      } catch (reason) {
        if (reason instanceof ApiRequestError && (reason.status === 401 || reason.status === 403)) setState('access')
        else setState('retryable')
      }
      return
    }
    if (!evidenceKind || !snapshotIdentifier) {
      setState('missing')
      return
    }
    setState('loading')
    setDecisionDetail(null)
    setGeneralDetail(null)
    setGeneralRecords([])
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
  }, [evidenceCode, evidenceHash, evidenceKind, isGeneralIndex, snapshotIdentifier])

  useEffect(() => {
    void load()
  }, [load])

  const title = isGeneralIndex ? 'Decision Evidence' : evidenceKind === 'general' ? 'Execution Evidence' : 'Decision Evidence'
  if (state === 'loading') return <section className="evidence-detail"><p className="evidence-detail__eyebrow">Yönetişim</p><h1>{title}</h1><p className="evidence-detail__message" aria-live="polite">Kanıt kaydı yükleniyor.</p></section>
  if (state === 'access') return <section className="evidence-detail"><p className="evidence-detail__eyebrow">Yönetişim</p><h1>{title}</h1><p className="evidence-detail__message" role="alert">Bu kanıt kaydını görüntüleme yetkiniz yok.</p><Link to="/login">Oturuma git</Link></section>
  if (state === 'retryable') return <section className="evidence-detail"><p className="evidence-detail__eyebrow">Yönetişim</p><h1>{title}</h1><p className="evidence-detail__message" role="alert">Kanıt kaydı geçici olarak yüklenemedi.</p><button type="button" onClick={() => void load()}>Tekrar dene</button><Link to="/ai-analysis">AI Analysis’e dön</Link></section>
  if (state === 'missing' || (!isGeneralIndex && !decisionDetail && !generalDetail)) return <section className="evidence-detail"><p className="evidence-detail__eyebrow">Yönetişim</p><h1>{title}</h1><p className="evidence-detail__message" role="alert">Kanıt kaydı bulunamadı veya seçili snapshot’a ait değil.</p><Link to="/ai-analysis">AI Analysis’e dön</Link></section>

  const evaluation = decisionDetail?.compensation_evaluation
  const selectedRule = decisionDetail?.selected_rule_version
  if (isGeneralIndex) return <section className="evidence-detail evidence-index" aria-labelledby="decision-evidence-title">
    <header className="evidence-index__header"><h1 id="decision-evidence-title">Karar kanıtları</h1></header>
    <GeneralEvidenceListView records={generalRecords} />
  </section>
  return <section className={`evidence-detail${generalDetail ? ' evidence-execution' : ''}`} aria-labelledby="decision-evidence-title">
    {generalDetail ? <header className="evidence-execution__header"><h1 id="decision-evidence-title">Çalıştırma kanıtı</h1></header> : <header className="evidence-detail__header"><div><p className="evidence-detail__eyebrow">Snapshot-local governance kaydı</p><h1 id="decision-evidence-title">{title}</h1><p>{snapshotKey}</p></div><Link to="/ai-analysis">AI Analysis’e dön</Link></header>}
    {isGeneralIndex ? <GeneralEvidenceListView records={generalRecords} /> : generalDetail ? <GeneralEvidenceDetailView detail={generalDetail} /> : <>
      <section className="evidence-detail__summary">
        <div><span>Kanıt özeti</span><strong>{decisionDetail?.evidence_hash}</strong></div>
        <div><span>Karar</span><strong>{decisionDetail?.decision}</strong></div>
        <div><span>Durum</span><strong>{decisionDetail?.finalized ? 'Kesinleşti' : 'Taslak'}</strong></div>
        {selectedRule?.rule_code ? <div><span>Seçilmiş RuleVersion</span><strong>{selectedRule.rule_code}{selectedRule.version !== undefined ? ` v${selectedRule.version}` : ''}</strong></div> : null}
        {evaluation ? <div><span>Değerlendirme / kesinti</span><strong>{evaluation.evaluation_code} / {evaluation.outage_code}</strong></div> : null}
        {decisionDetail?.final_amount ? <div><span>Tutar</span><strong>{decisionDetail.final_amount} {decisionDetail.currency}</strong></div> : null}
      </section>
      {evaluation ? <section className="evidence-detail__section"><h2>Bağlı değerlendirme</h2><dl><dt>Sonuç</dt><dd>{formatSafeValue(evaluation.result_type)}</dd><dt>Durum</dt><dd>{formatSafeValue(evaluation.status)}</dd></dl></section> : null}
      <DetailList title="Eşleşen koşullar" values={decisionDetail?.matched_conditions ?? []} />
      <DetailList title="Başarısız koşullar" values={decisionDetail?.failed_conditions ?? []} />
      <DetailList title="Hariç tutulan kurallar" values={decisionDetail?.excluded_rules ?? []} />
      <DetailList title="Uygulanan modifier’lar" values={decisionDetail?.applied_modifiers ?? []} />
      <DetailList title="Manuel inceleme nedenleri" values={decisionDetail?.manual_review_reasons ?? []} />
    </>}
  </section>
}
