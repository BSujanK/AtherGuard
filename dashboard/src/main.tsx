import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import './fonts.css'
import './styles/tokens.css'
import './styles/global.css'
import { createAppRouter } from './app/router'
import { connectStream } from './data/stream'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

connectStream(queryClient)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={createAppRouter()} />
    </QueryClientProvider>
  </StrictMode>,
)
