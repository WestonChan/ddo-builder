import { render, act } from '@testing-library/react'
import { describe, it, expect, beforeEach } from 'vitest'
import { createElement, type Dispatch, type SetStateAction } from 'react'
import { useLocalStorage } from './useLocalStorage'

// Store the setter via a callback prop — avoids lint issues with refs and globals
let setter: Dispatch<SetStateAction<unknown>> = () => {}

function TestComponent({
  storageKey,
  initial,
  onRender,
}: {
  storageKey: string
  initial: unknown
  onRender: (val: unknown, set: Dispatch<SetStateAction<unknown>>) => void
}) {
  const [value, setValue] = useLocalStorage(storageKey, initial)
  onRender(value, setValue as Dispatch<SetStateAction<unknown>>)
  return createElement('div', { 'data-testid': 'value' }, JSON.stringify(value))
}

function renderHook(key: string, initial: unknown) {
  let lastValue: unknown
  const onRender = (val: unknown, set: Dispatch<SetStateAction<unknown>>) => {
    lastValue = val
    setter = set
  }
  render(createElement(TestComponent, { storageKey: key, initial, onRender }))
  return { getValue: () => lastValue, getSetter: () => setter }
}

describe('useLocalStorage', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('returns initialValue when localStorage is empty', () => {
    const { getValue } = renderHook('test-key', 'hello')
    expect(getValue()).toBe('hello')
  })

  it('returns stored value when localStorage has data', () => {
    localStorage.setItem('test-key', JSON.stringify({ a: 1 }))
    const { getValue } = renderHook('test-key', {})
    expect(getValue()).toEqual({ a: 1 })
  })

  it('writes to localStorage when value changes', () => {
    const { getValue, getSetter } = renderHook('test-key', 'start')
    act(() => {
      getSetter()('updated')
    })
    expect(getValue()).toBe('updated')
    expect(JSON.parse(localStorage.getItem('test-key')!)).toBe('updated')
  })

  it('falls back to initialValue when stored data is corrupt JSON', () => {
    localStorage.setItem('test-key', 'not-valid-json{{{')
    const { getValue } = renderHook('test-key', 'fallback')
    expect(getValue()).toBe('fallback')
  })

  it('works with functional updater form of setState', () => {
    const { getValue, getSetter } = renderHook('test-key', 5)
    act(() => {
      getSetter()((prev: unknown) => (prev as number) + 10)
    })
    expect(getValue()).toBe(15)
    expect(JSON.parse(localStorage.getItem('test-key')!)).toBe(15)
  })
})
