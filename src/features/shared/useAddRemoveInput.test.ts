import { render, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { useAddRemoveInput } from './useAddRemoveInput'

function TestComponent({
  onAdd,
  onRemove,
  ms,
}: {
  onAdd: () => void
  onRemove: () => void
  ms?: number
}) {
  const { ref, onClick, onContextMenu } = useAddRemoveInput(onAdd, onRemove, ms)
  return createElement('div', {
    ref,
    onClick,
    onContextMenu,
    'data-testid': 'target',
  })
}

function touch(el: HTMLElement, type: 'touchstart' | 'touchend' | 'touchcancel') {
  el.dispatchEvent(new Event(type, { bubbles: true, cancelable: true }))
}

describe('useAddRemoveInput', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe('desktop: click / right-click', () => {
    it('fires onAdd on left-click', () => {
      const onAdd = vi.fn()
      const onRemove = vi.fn()
      const { getByTestId } = render(createElement(TestComponent, { onAdd, onRemove }))
      const el = getByTestId('target')

      act(() => {
        el.click()
      })

      expect(onAdd).toHaveBeenCalledTimes(1)
      expect(onRemove).not.toHaveBeenCalled()
    })

    it('fires onRemove on right-click', () => {
      const onAdd = vi.fn()
      const onRemove = vi.fn()
      const { getByTestId } = render(createElement(TestComponent, { onAdd, onRemove }))
      const el = getByTestId('target')

      act(() => {
        el.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }))
      })

      expect(onRemove).toHaveBeenCalledTimes(1)
      expect(onAdd).not.toHaveBeenCalled()
    })
  })

  describe('mobile: tap / long-press', () => {
    it('fires onAdd on quick tap (touch start + end before timeout)', () => {
      const onAdd = vi.fn()
      const onRemove = vi.fn()
      const { getByTestId } = render(createElement(TestComponent, { onAdd, onRemove, ms: 500 }))
      const el = getByTestId('target')

      act(() => {
        touch(el, 'touchstart')
      })
      act(() => {
        vi.advanceTimersByTime(200)
      })
      act(() => {
        touch(el, 'touchend')
      })

      expect(onAdd).toHaveBeenCalledTimes(1)
      expect(onRemove).not.toHaveBeenCalled()
    })

    it('fires onRemove when held past timeout', () => {
      const onAdd = vi.fn()
      const onRemove = vi.fn()
      const { getByTestId } = render(createElement(TestComponent, { onAdd, onRemove, ms: 500 }))
      const el = getByTestId('target')

      act(() => {
        touch(el, 'touchstart')
      })
      act(() => {
        vi.advanceTimersByTime(600)
      })

      expect(onRemove).toHaveBeenCalledTimes(1)

      // Releasing after long press should NOT fire add
      act(() => {
        touch(el, 'touchend')
      })
      expect(onAdd).not.toHaveBeenCalled()
    })

    it('does not fire either callback on cancel', () => {
      const onAdd = vi.fn()
      const onRemove = vi.fn()
      const { getByTestId } = render(createElement(TestComponent, { onAdd, onRemove, ms: 500 }))
      const el = getByTestId('target')

      act(() => {
        touch(el, 'touchstart')
      })
      act(() => {
        touch(el, 'touchcancel')
      })
      act(() => {
        vi.advanceTimersByTime(600)
      })

      expect(onAdd).not.toHaveBeenCalled()
      expect(onRemove).not.toHaveBeenCalled()
    })

    it('respects custom timeout duration', () => {
      const onAdd = vi.fn()
      const onRemove = vi.fn()
      const { getByTestId } = render(createElement(TestComponent, { onAdd, onRemove, ms: 200 }))
      const el = getByTestId('target')

      act(() => {
        touch(el, 'touchstart')
      })
      act(() => {
        vi.advanceTimersByTime(250)
      })

      expect(onRemove).toHaveBeenCalledTimes(1)
    })
  })
})
