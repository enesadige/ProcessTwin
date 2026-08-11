import './ForbiddenPage.css'

export function ForbiddenPage() {
  return (
    <section className="forbidden-page" aria-labelledby="forbidden-title">
      <p className="forbidden-page__code">403</p>
      <h1 id="forbidden-title">Bu görünüm için yetkiniz yok</h1>
      <p>Hesabınız bu operasyon alanına erişim izni vermiyor.</p>
    </section>
  )
}
