import { createBrowserRouter, RouterProvider } from 'react-router-dom'

import { AppLayout } from './components/layout/AppLayout'
import { OperationsPage } from './pages/OperationsPage'
import { ProcessTwinPage } from './pages/ProcessTwinPage'

const router = createBrowserRouter([
  {
    element: <AppLayout />,
    children: [
      { path: '/', element: <OperationsPage /> },
      { path: '/processtwin', element: <ProcessTwinPage /> },
    ],
  },
])

function App() {
  return <RouterProvider router={router} />
}

export default App
