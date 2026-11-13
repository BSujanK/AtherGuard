import { useRouteError } from 'react-router-dom'
import EmptyState from '../components/EmptyState'

/** What a view that failed to render shows instead of the router's developer page: what happened and a way back. */
export default function RouteError() {
  const error = useRouteError()
  const message = error instanceof Error ? error.message : String(error ?? 'unknown error')
  return (
    <main style={{ display: 'grid', placeItems: 'center', minHeight: '100%', padding: '2rem' }}>
      <EmptyState
        title="This view hit an error"
        action={
          <button type="button" onClick={() => window.location.reload()}>
            Reload the page
          </button>
        }
      >
        Something in the page failed while drawing it ({message}). Reloading usually clears it; the data is not affected.
      </EmptyState>
    </main>
  )
}
