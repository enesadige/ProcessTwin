import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { AppLoading } from '../components/layout/AppLayout'
import { useAuth } from './AuthContext'
import type { UserRole } from './api'
import { ForbiddenPage } from '../pages/ForbiddenPage'

export function ProtectedRoutes() {
  const { loading, user } = useAuth()
  const location = useLocation()
  if (loading) return <AppLoading />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <Outlet />
}

export function RoleRoute({ roles }: { roles: UserRole[] }) {
  const { user } = useAuth()
  if (!user || !roles.includes(user.role)) return <ForbiddenPage />
  return <Outlet />
}
