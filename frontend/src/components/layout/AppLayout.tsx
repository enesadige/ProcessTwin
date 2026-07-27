import { NavLink, Outlet } from 'react-router-dom'

import './AppLayout.css'

const navItems = [
  { label: 'Operations', to: '/' },
  { label: 'ProcessTwin', to: '/processtwin' },
]

export function AppLayout() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-brand">
          <p className="app-brand__name">ProcessTwin AI</p>
          <p className="app-brand__meta">Maltepe BNG MVP</p>
        </div>
        <nav className="app-nav" aria-label="Primary navigation">
          {navItems.map((item) => (
            <NavLink
              className={({ isActive }) =>
                isActive ? 'app-nav__link app-nav__link--active' : 'app-nav__link'
              }
              end={item.to === '/'}
              key={item.to}
              to={item.to}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
