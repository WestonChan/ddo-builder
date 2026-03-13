import { useState, useEffect, type Dispatch, type SetStateAction } from 'react'

/**
 * Drop-in replacement for useState that persists to localStorage.
 * On first render, reads from localStorage (falling back to initialValue).
 * On every update, writes the new value to localStorage.
 */
export function useLocalStorage<T>(
  key: string,
  initialValue: T,
  migrate?: (value: T) => T,
): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = localStorage.getItem(key)
      if (stored !== null) {
        const parsed = JSON.parse(stored) as T
        return migrate ? migrate(parsed) : parsed
      }
    } catch {
      // corrupt data — fall back
    }
    return initialValue
  })

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value))
    } catch {
      // storage full or unavailable — silently ignore
    }
  }, [key, value])

  return [value, setValue]
}
