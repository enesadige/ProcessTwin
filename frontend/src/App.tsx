import { Suspense } from 'react'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'

import { AppErrorPage, AppLayout, AppLoading } from './components/layout/AppLayout'
import { OperationsPage } from './pages/OperationsPage'
import { ProcessTwinPage } from './pages/ProcessTwinPage'
import { PlaceholderPage } from './pages/PlaceholderPage'

const router = createBrowserRouter([
  {
    element: <AppLayout />,
    errorElement: <AppErrorPage />,
    children: [
      { path: '/', element: <OperationsPage /> },
      { path: '/ai-analysis', element: <PlaceholderPage title="AI Analysis" section="Workspace" /> },
      { path: '/operations', element: <OperationsPage /> },
      { path: '/network', element: <PlaceholderPage title="Network" section="Operations" /> },
      { path: '/customers', element: <PlaceholderPage title="Customers" section="Operations" /> },
      { path: '/rules', element: <PlaceholderPage title="Rules" section="Governance" /> },
      {
        path: '/evidence',
        element: <PlaceholderPage title="Decision Evidence" section="Governance" />,
      },
      { path: '/processtwin', element: <ProcessTwinPage /> },
      { path: '/settings', element: <PlaceholderPage title="Settings" section="Workspace" /> },
    ],
  },
])

function App() {
  return (
    <Suspense fallback={<AppLoading />}>
      <RouterProvider router={router} />
    </Suspense>
  )
}

export default App
