import { isRouteErrorResponse, NavLink, Outlet, useRouteError } from 'react-router-dom'

import { useAuth } from '../../auth/AuthContext'
import type { UserRole } from '../../auth/api'
import './AppLayout.css'

type NavItem = { label: string; to: string; marker: string; roles?: UserRole[] }
const navGroups: { label: string; items: NavItem[] }[] = [
  {
    label: 'Workspace',
    items: [
      { label: 'AI Analysis', to: '/ai-analysis', marker: 'AI', roles: ['analyst', 'admin'] },
      { label: 'Operations', to: '/', marker: 'OP' },
      { label: 'ProcessTwin', to: '/processtwin', marker: 'PT', roles: ['analyst', 'admin'] },
    ],
  },
  {
    label: 'Operations',
    items: [
      { label: 'Network', to: '/network', marker: 'NW', roles: ['engineer', 'admin'] },
      { label: 'Customers', to: '/customers', marker: 'CU' },
    ],
  },
  {
    label: 'Governance',
    items: [
      { label: 'Rules', to: '/rules', marker: 'RL', roles: ['admin'] },
      { label: 'Decision Evidence', to: '/evidence', marker: 'EV' },
    ],
  },
]

export function AppLayout() {
  const { user, signOut } = useAuth()
  const canSee = (roles?: UserRole[]) => !roles || roles.includes(user?.role ?? 'viewer')
  const initials = user?.username.slice(0, 2).toUpperCase() ?? 'PT'

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="app-brand">
          <img className="app-brand__logo" src="/turkcell.png" alt="Turkcell" />
        </div>
        <nav className="app-nav" aria-label="Primary navigation">
          {navGroups.map((group) => (
            <div className="app-nav__group" key={group.label}>
              <p className="app-nav__group-label">{group.label}</p>
              {group.items.filter((item) => canSee(item.roles)).map((item) => (
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
          {canSee(['admin']) && <NavLink className="app-nav__link" to="/settings">
            <span className="app-nav__marker" aria-hidden="true">ST</span><span>Settings</span>
          </NavLink>}
          <div className="auth-shell" aria-label="Signed-in workspace">
            <span className="auth-shell__avatar" aria-hidden="true">{initials}</span>
            <span className="auth-shell__details">
              <strong>{user?.username}</strong>
              <small>{user?.role} access</small>
            </span>
            <button className="auth-shell__logout" type="button" onClick={() => void signOut()} aria-label="Log out">Exit</button>
          </div>
        </div>
      </aside>
      <div className="app-content">
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
