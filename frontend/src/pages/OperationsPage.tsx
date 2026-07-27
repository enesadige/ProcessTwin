import './OperationsPage.css'

const metrics = [
  { label: 'MVP scope', value: '4 MCP', note: 'Network, Customer, Rule, Compensation' },
  { label: 'Area', value: 'Maltepe', note: 'First vertical slice' },
  { label: 'Device', value: 'BNG', note: 'Standard network term' },
  { label: 'Evidence', value: 'Required', note: 'Decision Evidence enabled' },
]

export function OperationsPage() {
  return (
    <section className="operations-page">
      <div className="page-heading">
        <div>
          <h1 className="page-heading__title">Operations cockpit</h1>
          <p className="page-heading__description">
            Native React shell for the Maltepe outage analysis flow. Real data, charts, graph
            topology and orchestration states will be attached in later tasks.
          </p>
        </div>
        <span className="status-pill">Frontend ready</span>
      </div>

      <div className="metric-grid">
        {metrics.map((metric) => (
          <article className="metric-card" key={metric.label}>
            <p className="metric-card__label">{metric.label}</p>
            <p className="metric-card__value">{metric.value}</p>
            <p className="metric-card__note">{metric.note}</p>
          </article>
        ))}
      </div>

      <article className="panel">
        <h2 className="panel__title">Primary demo query</h2>
        <p className="demo-query">
          Maltepe'de gecen ay en uzun suren kesinti hangisiydi, kac musteri
          etkilendi, kok nedeni neydi ve hangi telafi secenekleri uygulanabilir?
        </p>
      </article>
    </section>
  )
}
