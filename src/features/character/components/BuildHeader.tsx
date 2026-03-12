import { useEffect, useState } from 'react'
import './BuildHeader.css'

type Theme = 'dark' | 'light'

function getInitialTheme(): Theme {
  const stored = localStorage.getItem('theme')
  if (stored === 'light' || stored === 'dark') return stored
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

function useTheme() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('theme', theme)
  }, [theme])

  const toggle = () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))
  return { theme, toggle }
}

const THEMES = [
  { name: 'Gold', accent: '#b8962e', hover: '#d4ad3a' },
  { name: 'Crimson', accent: '#ef4444', hover: '#f87171' },
  { name: 'Mint', accent: '#6ee7b7', hover: '#a7f3d0' },
  { name: 'Coral', accent: '#f97066', hover: '#fca5a1' },
  { name: 'Ice', accent: '#67e8f9', hover: '#a5f3fc' },
  { name: 'Marigold', accent: '#eab308', hover: '#facc15' },
  { name: 'Plum', accent: '#a855f7', hover: '#c084fc' },
  { name: 'Sand', accent: '#d6c5a3', hover: '#e8dcc4' },
  { name: 'Sage', accent: '#7ba3b8', hover: '#9bbdd0' },
]

function applyAccent(accent: string, hover: string) {
  document.documentElement.style.setProperty('--accent', accent)
  document.documentElement.style.setProperty('--accent-hover', hover)
  localStorage.setItem('accent', JSON.stringify({ accent, hover }))
}

function restoreAccent() {
  try {
    const stored = localStorage.getItem('accent')
    if (!stored) return
    const { accent, hover } = JSON.parse(stored)
    if (accent && hover) {
      document.documentElement.style.setProperty('--accent', accent)
      document.documentElement.style.setProperty('--accent-hover', hover)
    }
  } catch {
    // ignore malformed data
  }
}

const ABILITY_SCORES = [
  { label: 'STR', value: 16 },
  { label: 'DEX', value: 8 },
  { label: 'CON', value: 14 },
  { label: 'INT', value: 10 },
  { label: 'WIS', value: 12 },
  { label: 'CHA', value: 8 },
]

interface BuildHeaderProps {
  activeView: 'build' | 'character'
  onViewChange: (view: 'build' | 'character') => void
}

function BuildHeader({ activeView, onViewChange }: BuildHeaderProps) {
  const { theme, toggle } = useTheme()
  const storedAccent = (() => {
    try {
      const s = localStorage.getItem('accent')
      if (!s) return ''
      const { accent } = JSON.parse(s)
      return THEMES.find((t) => t.accent === accent)?.name ?? ''
    } catch {
      return ''
    }
  })()

  useEffect(() => restoreAccent(), [])

  return (
    <header className="build-header">
      <div className="build-header-top">
        <div className="build-brand-group">
          <span className="build-brand">DDO Builder</span>
          <nav className="view-tabs">
            <button
              className={`view-tab ${activeView === 'build' ? 'active' : ''}`}
              onClick={() => onViewChange('build')}
            >
              Build
            </button>
            <button
              className={`view-tab ${activeView === 'character' ? 'active' : ''}`}
              onClick={() => onViewChange('character')}
            >
              Character
            </button>
          </nav>
          <select
            className="theme-selector"
            defaultValue={storedAccent}
            onChange={(e) => {
              const t = THEMES.find((th) => th.name === e.target.value)
              if (t) applyAccent(t.accent, t.hover)
            }}
          >
            <option value="" disabled>
              Accent
            </option>
            {THEMES.map((t) => (
              <option key={t.name} value={t.name}>
                {t.name}
              </option>
            ))}
          </select>
          <button
            className="theme-toggle btn-ghost-sm"
            onClick={toggle}
            title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
          >
            {theme === 'dark' ? '☀' : '☾'}
          </button>
        </div>
        {activeView === 'build' && (
          <div className="build-info">
            <select defaultValue="human">
              <option value="human">Human</option>
              <option value="elf">Elf</option>
              <option value="dwarf">Dwarf</option>
              <option value="halfling">Halfling</option>
            </select>
            <span className="build-class">18 Paladin / 2 Rogue</span>
            <span className="build-level">Level 20</span>
            <select className="life-selector" defaultValue="3">
              <option value="1">Life 1</option>
              <option value="2">Life 2</option>
              <option value="3">Life 3 (current)</option>
            </select>
          </div>
        )}
      </div>
      {activeView === 'build' && (
        <div className="build-ability-scores">
          {ABILITY_SCORES.map((score) => (
            <div key={score.label} className="ability-score-chip">
              <span className="label">{score.label}</span>
              <span className="value">{score.value}</span>
            </div>
          ))}
        </div>
      )}
    </header>
  )
}

export default BuildHeader
