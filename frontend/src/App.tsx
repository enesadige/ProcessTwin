import { Suspense } from 'react'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'

import { AuthProvider } from './auth/AuthContext'
import { ProtectedRoutes, RoleRoute } from './auth/RouteGuards'
import { AppErrorPage, AppLayout, AppLoading } from './components/layout/AppLayout'
import { LoginPage } from './pages/LoginPage'
import { AIAnalysisPage } from './pages/AIAnalysisPage'
import { OperationsPage } from './pages/OperationsPage'
import { ProcessTwinPage } from './pages/ProcessTwinPage'
import { PlaceholderPage } from './pages/PlaceholderPage'

const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    element: <ProtectedRoutes />,
    errorElement: <AppErrorPage />,
    children: [
      {
        element: <AppLayout />,
        children: [
          { path: '/', element: <OperationsPage /> },
          { path: '/operations', element: <OperationsPage /> },
          { path: '/customers', element: <PlaceholderPage title="Customers" section="Operations" /> },
          {
            element: <RoleRoute roles={['analyst', 'admin']} />,
            children: [
              { path: '/ai-analysis', element: <AIAnalysisPage /> },
              { path: '/processtwin', element: <ProcessTwinPage /> },
            ],
          },
          {
            element: <RoleRoute roles={['engineer', 'admin']} />,
            children: [{ path: '/network', element: <PlaceholderPage title="Network" section="Operations" /> }],
          },
          {
            element: <RoleRoute roles={['admin']} />,
            children: [
              { path: '/rules', element: <PlaceholderPage title="Rules" section="Governance" /> },
              { path: '/settings', element: <PlaceholderPage title="Settings" section="Workspace" /> },
            ],
          },
          { path: '/evidence', element: <PlaceholderPage title="Decision Evidence" section="Governance" /> },
        ],
      },
    ],
  },
])

function App() {
  return (
    <AuthProvider>
      <Suspense fallback={<AppLoading />}>
        <RouterProvider router={router} />
      </Suspense>
    </AuthProvider>
  )
}

export default App
