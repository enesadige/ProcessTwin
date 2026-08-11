import { isRouteErrorResponse, NavLink, Outlet, useRouteError } from 'react-router-dom'

import './AppLayout.css'

const navGroups = [
  {
    label: 'Workspace',
    items: [
      { label: 'AI Analysis', to: '/ai-analysis', marker: 'AI' },
      { label: 'Operations', to: '/', marker: 'OP' },
      { label: 'ProcessTwin', to: '/processtwin', marker: 'PT' },
    ],
  },
  {
    label: 'Operations',
    items: [
      { label: 'Network', to: '/network', marker: 'NW' },
      { label: 'Customers', to: '/customers', marker: 'CU' },
    ],
  },
  {
    label: 'Governance',
    items: [
      { label: 'Rules', to: '/rules', marker: 'RL' },
      { label: 'Decision Evidence', to: '/evidence', marker: 'EV' },
    ],
  },
]

export function AppLayout() {
  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="app-brand">
          <div className="app-brand__mark" aria-hidden="true">PT</div>
          <div>
            <p className="app-brand__name">ProcessTwin</p>
            <p className="app-brand__meta">Operations intelligence</p>
          </div>
        </div>
        <nav className="app-nav" aria-label="Primary navigation">
          {navGroups.map((group) => (
            <div className="app-nav__group" key={group.label}>
              <p className="app-nav__group-label">{group.label}</p>
              {group.items.map((item) => (
                <NavLink
                  className={({ isActive }) =>
                    isActive ? 'app-nav__link app-nav__link--active' : 'app-nav__link'
                  }
                  end={item.to === '/'}
                  key={item.to}
                  to={item.to}
                >
                  <span className="app-nav__marker" aria-hidden="true">{item.marker}</span>
                  <span>{item.label}</span>
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="app-sidebar__footer">
          <NavLink className="app-nav__link" to="/settings">
            <span className="app-nav__marker" aria-hidden="true">ST</span>
            <span>Settings</span>
          </NavLink>
          <div className="auth-shell" aria-label="Signed-in workspace">
            <span className="auth-shell__avatar" aria-hidden="true">ED</span>
            <span className="auth-shell__details">
              <strong>Operations user</strong>
              <small>Workspace access</small>
            </span>
            <span className="auth-shell__status" title="Auth boundary ready" />
          </div>
        </div>
      </aside>
      <div className="app-content">
        <header className="app-topbar">
          <div>
            <p className="app-topbar__eyebrow">ProcessTwin AI</p>
            <p className="app-topbar__title">Telecom operations workspace</p>
          </div>
          <div className="app-topbar__status">
            <span className="app-topbar__status-dot" aria-hidden="true" />
            <span>Workspace ready</span>
          </div>
        </header>
        <main className="app-main"><Outlet /></main>
      </div>
    </div>
  )
}

export function AppLoading() {
  return <div className="app-state"><span className="app-state__spinner" aria-hidden="true" />Loading workspace</div>
}

export function AppErrorPage() {
  const error = useRouteError()
  const title = isRouteErrorResponse(error) && error.status === 404 ? 'Page not found' : 'Workspace unavailable'
  const detail = isRouteErrorResponse(error) ? error.statusText : 'The requested view could not be loaded.'

  return (
    <main className="app-error">
      <p className="app-error__code">{isRouteErrorResponse(error) ? error.status : 'ERROR'}</p>
      <h1>{title}</h1>
      <p>{detail}</p>
      <NavLink className="app-error__link" to="/">Return to Operations</NavLink>
    </main>
  )
}
