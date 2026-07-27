import './ProcessTwinPage.css'

export function ProcessTwinPage() {
  return (
    <section className="processtwin-page">
      <article className="scenario-panel">
        <h1 className="scenario-panel__title">ProcessTwin scenario</h1>
        <p className="scenario-panel__text">
          The MVP will compare baseline and candidate outcomes for a Maltepe BNG outage through
          Django SimulationService before a separate Simulation MCP is added.
        </p>
        <div className="scenario-grid">
          <div className="scenario-box">
            <p className="scenario-box__label">Baseline</p>
            <p className="scenario-box__value">90 minute BNG failure</p>
          </div>
          <div className="scenario-box">
            <p className="scenario-box__label">Candidate</p>
            <p className="scenario-box__value">180 minute outage, 120 minute refund threshold</p>
          </div>
        </div>
      </article>
    </section>
  )
}
