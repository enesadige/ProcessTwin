import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

import * as authApi from './api'

type AuthContextValue = {
  user: authApi.AuthUser | null
  loading: boolean
  error: string | null
  signIn: (username: string, password: string) => Promise<authApi.AuthUser>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<authApi.AuthUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    authApi.getCurrentUser()
      .then(setUser)
      .catch((reason: unknown) => {
        if (reason instanceof Error && reason.message !== 'Authentication required.') {
          setError('Oturum durumu alınamadı. Lütfen tekrar deneyin.')
        }
      })
      .finally(() => setLoading(false))
  }, [])

  const value = useMemo<AuthContextValue>(() => ({
    user,
    loading,
    error,
    signIn: async (username, password) => {
      const nextUser = await authApi.login(username, password)
      setUser(nextUser)
      setError(null)
      return nextUser
    },
    signOut: async () => {
      try {
        await authApi.logout()
      } finally {
        setUser(null)
      }
    },
  }), [error, loading, user])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within AuthProvider')
  return context
}
