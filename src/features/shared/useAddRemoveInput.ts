import { useCallback, useEffect, useRef } from 'react'
import type { MouseEvent } from 'react'

/**
 * Unified add/remove input hook.
 * - Desktop: left-click → onAdd, right-click → onRemove
 * - Mobile: tap → onAdd, long-press → onRemove
 *
 * Returns { ref, onClick, onContextMenu } to spread onto the target element.
 * The ref attaches native touch listeners with { passive: false } to allow preventDefault.
 */
export function useAddRemoveInput(onAdd: () => void, onRemove: () => void, ms = 500) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const firedRef = useRef(false)
  const elRef = useRef<HTMLElement | null>(null)

  // Keep callback refs current without re-attaching listeners
  const onAddRef = useRef(onAdd)
  const onRemoveRef = useRef(onRemove)
  useEffect(() => {
    onAddRef.current = onAdd
    onRemoveRef.current = onRemove
  })

  // --- Touch (mobile): tap = add, long-press = remove ---

  const handleTouchStart = useCallback(
    (e: TouchEvent) => {
      e.preventDefault()
      firedRef.current = false
      timerRef.current = setTimeout(() => {
        firedRef.current = true
        onRemoveRef.current()
      }, ms)
    },
    [ms],
  )

  const handleTouchEnd = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    if (!firedRef.current) onAddRef.current()
  }, [])

  const handleTouchCancel = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
  }, [])

  useEffect(() => {
    const el = elRef.current
    if (!el) return

    el.addEventListener('touchstart', handleTouchStart, { passive: false })
    el.addEventListener('touchend', handleTouchEnd)
    el.addEventListener('touchcancel', handleTouchCancel)

    return () => {
      el.removeEventListener('touchstart', handleTouchStart)
      el.removeEventListener('touchend', handleTouchEnd)
      el.removeEventListener('touchcancel', handleTouchCancel)
    }
  }, [handleTouchStart, handleTouchEnd, handleTouchCancel])

  // --- Click (desktop): left-click = add, right-click = remove ---

  const onClick = useCallback(() => {
    onAddRef.current()
  }, [])

  const onContextMenu = useCallback((e: MouseEvent) => {
    e.preventDefault()
    onRemoveRef.current()
  }, [])

  return { ref: elRef, onClick, onContextMenu }
}
