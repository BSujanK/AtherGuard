import { useEffect, useRef, useState } from 'react'

/** True for `ms` after `token` changes; going from 0 (nothing loaded yet) to a first value is not a change. */
export function useUpdateFlash(token: number | string, ms = 2400): boolean {
  const previous = useRef(token)
  const [flashing, setFlashing] = useState(false)

  useEffect(() => {
    if (previous.current === token) return
    const first = previous.current === 0
    previous.current = token
    if (first) return
    setFlashing(true)
    const timer = setTimeout(() => setFlashing(false), ms)
    return () => clearTimeout(timer)
  }, [token, ms])

  return flashing
}
