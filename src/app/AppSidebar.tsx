import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  SwordShieldIcon,
  PersonIcon,
  BackpackIcon,
  TreeIcon,
  ConstellationIcon,
  ShieldBrandIcon,
  SunIcon,
  MoonIcon,
  ChevronRightIcon,
  ChevronLeftIcon,
  GearIcon,
  CheckIcon,
  TooltipWrapper,
} from '../components'
import { useTheme, THEMES, applyAccent, restoreAccent } from '../hooks'
import './AppSidebar.css'

export type View = 'build' | 'character' | 'gear' | 'enhancements' | 'destinies'

const NAV_ITEMS: { view: View; label: string; Icon: React.FC }[] = [
  { view: 'character', label: 'Character', Icon: PersonIcon },
  { view: 'build', label: 'Build', Icon: SwordShieldIcon },
  { view: 'gear', label: 'Gear', Icon: BackpackIcon },
  { view: 'enhancements', label: 'Enhancements', Icon: TreeIcon },
  { view: 'destinies', label: 'Epic Destinies', Icon: ConstellationIcon },
]

interface AppSidebarProps {
  activeView: View
  onViewChange: (view: View) => void
  expanded: boolean
  onToggleExpanded: () => void
}

function getActiveAccent(): string | null {
  try {
    const stored = localStorage.getItem('accent')
    if (!stored) return null
    return JSON.parse(stored).accent ?? null
  } catch {
    return null
  }
}

function SettingsPanel({
  theme,
  onToggleTheme,
  activeAccent,
  onAccentChange,
  onClose,
  anchorRef,
}: {
  theme: 'dark' | 'light'
  onToggleTheme: () => void
  activeAccent: string | null
  onAccentChange: (accent: string, hover: string) => void
  onClose: () => void
  anchorRef: React.RefObject<HTMLButtonElement | null>
}) {
  const panelRef = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)

  // Position relative to anchor button
  useEffect(() => {
    const btn = anchorRef.current
    const panel = panelRef.current
    if (!btn || !panel) return
    const rect = btn.getBoundingClientRect()
    const panelRect = panel.getBoundingClientRect()
    const left = rect.right + 8
    // Align bottom of panel with bottom of button, clamp to viewport
    let top = rect.bottom - panelRect.height
    top = Math.max(8, Math.min(top, window.innerHeight - panelRect.height - 8))
    setPos({ top, left })
  }, [anchorRef])

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (!panelRef.current?.contains(target) && !anchorRef.current?.contains(target)) {
        onClose()
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose, anchorRef])

  return (
    <div
      ref={panelRef}
      className="settings-panel"
      style={pos ? { top: pos.top, left: pos.left } : { visibility: 'hidden' }}
    >
      <div className="settings-section">
        <div className="settings-label">Theme</div>
        <div className="settings-theme-toggle">
          <button
            className={`settings-theme-opt${theme === 'light' ? ' active' : ''}`}
            onClick={() => {
              if (theme !== 'light') onToggleTheme()
            }}
          >
            <SunIcon /> Light
          </button>
          <button
            className={`settings-theme-opt${theme === 'dark' ? ' active' : ''}`}
            onClick={() => {
              if (theme !== 'dark') onToggleTheme()
            }}
          >
            <MoonIcon /> Dark
          </button>
        </div>
      </div>

      <div className="settings-section">
        <div className="settings-label">Accent Color</div>
        <div className="settings-accent-grid">
          {THEMES.map((t) => (
            <button
              key={t.name}
              className={`settings-accent-swatch${activeAccent === t.accent ? ' selected' : ''}`}
              onClick={() => onAccentChange(t.accent, t.hover)}
            >
              <span className="settings-accent-dot" style={{ background: t.accent }} />
              <span className="settings-accent-name">{t.name}</span>
              {activeAccent === t.accent && (
                <span className="settings-accent-check">
                  <CheckIcon />
                </span>
              )}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

function AppSidebar({ activeView, onViewChange, expanded, onToggleExpanded }: AppSidebarProps) {
  const { theme, toggle } = useTheme()
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [activeAccent, setActiveAccent] = useState<string | null>(getActiveAccent)
  const settingsBtnRef = useRef<HTMLButtonElement>(null)

  useEffect(() => restoreAccent(), [])

  return (
    <div className={`sidebar-wrapper${expanded ? ' expanded' : ''}`}>
      {/* Toggle handle (outside aside so overflow:hidden doesn't clip it) */}
      <button
        className="sidebar-toggle"
        onClick={onToggleExpanded}
        title={expanded ? 'Collapse sidebar' : 'Expand sidebar'}
      >
        {expanded ? <ChevronLeftIcon /> : <ChevronRightIcon />}
      </button>

      <aside className={`app-sidebar${expanded ? ' expanded' : ''}`}>
        {/* Brand mark */}
        <div className="sidebar-top">
          <button
            className="sidebar-brand"
            onClick={() => onViewChange('build')}
            title="DDO Builder"
          >
            <ShieldBrandIcon />
          </button>
        </div>

        {/* Navigation icons */}
        <nav className="sidebar-nav">
          {NAV_ITEMS.map(({ view, label, Icon }) => (
            <TooltipWrapper key={view} text={label} placement={expanded ? undefined : 'right'}>
              <button
                className={`sidebar-nav-btn${activeView === view ? ' active' : ''}`}
                onClick={() => onViewChange(view)}
              >
                <Icon />
                {expanded && <span className="sidebar-nav-label">{label}</span>}
              </button>
            </TooltipWrapper>
          ))}
        </nav>

        {/* Settings */}
        <div className="sidebar-bottom">
          <TooltipWrapper text="Settings" placement={expanded ? undefined : 'right'}>
            <button
              ref={settingsBtnRef}
              className={`sidebar-nav-btn sidebar-settings-btn${settingsOpen ? ' active' : ''}`}
              onClick={() => setSettingsOpen(!settingsOpen)}
            >
              <GearIcon />
              {expanded && <span className="sidebar-nav-label">Settings</span>}
            </button>
          </TooltipWrapper>
        </div>
      </aside>

      {settingsOpen &&
        createPortal(
          <SettingsPanel
            theme={theme}
            onToggleTheme={toggle}
            activeAccent={activeAccent}
            onAccentChange={(accent, hover) => {
              applyAccent(accent, hover)
              setActiveAccent(accent)
            }}
            onClose={() => setSettingsOpen(false)}
            anchorRef={settingsBtnRef}
          />,
          document.body,
        )}
    </div>
  )
}

export default AppSidebar
