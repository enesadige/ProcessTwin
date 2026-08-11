import './PlaceholderPage.css'

type PlaceholderPageProps = {
  section: string
  title: string
}

export function PlaceholderPage({ section, title }: PlaceholderPageProps) {
  return (
    <section className="placeholder-page" aria-labelledby="placeholder-title">
      <div className="placeholder-page__header">
        <div>
          <p className="placeholder-page__eyebrow">{section}</p>
          <h1 id="placeholder-title">{title}</h1>
        </div>
        <span className="placeholder-page__status">Preparing workspace</span>
      </div>
      <div className="placeholder-page__body">
        <span className="placeholder-page__indicator" aria-hidden="true" />
        <div>
          <h2>View ready</h2>
          <p>This workspace is prepared for the next delivery.</p>
        </div>
      </div>
    </section>
  )
}
