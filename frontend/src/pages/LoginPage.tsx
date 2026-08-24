import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext'
import './LoginPage.css'

export function LoginPage() {
  const { user, loading, error: sessionError, signIn } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (loading) return <div className="login-state">Oturum kontrol ediliyor</div>
  if (user) return <Navigate to="/" replace />

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await signIn(username, password)
      const target = typeof location.state?.from === 'string' && location.state.from.startsWith('/')
        ? location.state.from
        : '/'
      navigate(target, { replace: true })
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : 'Giriş yapılamadı.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="login-page">
      <section className="login-panel" aria-labelledby="login-title">
        <img className="login-logo" src="/turkcell.png" alt="Turkcell" />
        <h1 id="login-title">Çalışma alanına giriş yapın</h1>
        <form onSubmit={submit} className="login-form">
          <label htmlFor="username">Kullanıcı adı veya e-posta</label>
          <input id="username" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required />
          <label htmlFor="password">Parola</label>
          <input id="password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required />
          {(error || sessionError) && <p className="login-error" role="alert">{error || sessionError}</p>}
          <button type="submit" disabled={busy}>{busy ? 'Giriş yapılıyor...' : 'Giriş yap'}</button>
        </form>
      </section>
    </main>
  )
}
