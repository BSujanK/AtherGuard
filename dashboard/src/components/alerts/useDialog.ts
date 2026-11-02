import { type RefObject, useEffect, useLayoutEffect, useRef } from 'react'

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

const focusables = (root: HTMLElement): HTMLElement[] =>
  Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.closest('[hidden], [inert]') === null)

/**
 * Behaviour of a modal dialog: focus moves into `panel` when it mounts, Tab and Shift+Tab stay inside it (also when a
 * click on plain text has left focus on the page body), Escape closes it, and focus goes back to where it was when it
 * closes. `returnFocus` names the element to use when the original one is gone, for example a virtualised row that
 * scrolled out of the DOM or a deep link that opened the dialog with nothing focused.
 */
export function useDialog(
  panel: RefObject<HTMLElement | null>,
  onClose: () => void,
  returnFocus?: () => HTMLElement | null,
): void {
  const close = useRef(onClose)
  const fallback = useRef(returnFocus)
  useLayoutEffect(() => {
    close.current = onClose
    fallback.current = returnFocus
  })

  useEffect(() => {
    const root = panel.current
    if (!root) return
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    focusables(root)[0]?.focus()

    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        close.current()
        return
      }
      if (event.key !== 'Tab') return
      const items = focusables(root)
      if (items.length === 0) {
        event.preventDefault()
        return
      }
      const first = items[0]!
      const last = items[items.length - 1]!
      const active = document.activeElement
      if (!root.contains(active)) {
        event.preventDefault()
        ;(event.shiftKey ? last : first).focus()
      } else if (event.shiftKey && active === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && active === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      const target = opener?.isConnected && opener !== document.body ? opener : fallback.current?.()
      target?.focus()
    }
  }, [panel])
}
