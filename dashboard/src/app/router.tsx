import { createBrowserRouter, Navigate, type RouteObject } from 'react-router-dom'
import EmptyState from '../components/EmptyState'
import Alerts from '../views/Alerts'
import LiveMap from '../views/LiveMap'
import Sensors from '../views/Sensors'
import Story from '../views/Story'
import Shell from './Shell'

/**
 * Client routes. `/alerts` and `/sensors` are JSON endpoints on the same server and win over the
 * SPA fallback, so the views live at distinct paths.
 */
export const routes: RouteObject[] = [
  {
    path: '/',
    element: <Shell />,
    children: [
      { index: true, element: <Navigate to="/map" replace /> },
      { path: 'map', element: <LiveMap /> },
      { path: 'alerts-why', element: <Alerts /> },
      { path: 'sensors-sources', element: <Sensors /> },
      { path: 'story', element: <Story /> },
      {
        path: '*',
        element: (
          <EmptyState title="That page does not exist">
            Use the navigation on the left to open the live map, the alerts or the sensors.
          </EmptyState>
        ),
      },
    ],
  },
]

export const createAppRouter = () => createBrowserRouter(routes)
