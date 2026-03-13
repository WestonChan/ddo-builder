import { useEffect, useState } from 'react'
import AppSidebar from './AppSidebar'
import type { View } from './AppSidebar'
import { useLocalStorage } from '../hooks'
import { CollapsibleSection } from '../components'
import {
  BuildSidePanel,
  CharacterView,
  useActiveCharacter,
  formatClassSummary,
  formatRace,
} from '../features/character'
import './App.css'

const VALID_VIEWS: View[] = ['build', 'character', 'gear', 'enhancements', 'destinies']

function getViewFromHash(): View {
  const hash = window.location.hash.replace('#', '')
  return VALID_VIEWS.includes(hash as View) ? (hash as View) : 'build'
}

function App() {
  const [activeView, setActiveView] = useState<View>(getViewFromHash)
  const [sidebarExpanded, setSidebarExpanded] = useLocalStorage('ddo-sidebar-expanded', false)
  const { character: selected, currentLife, lifeNumber } = useActiveCharacter()

  useEffect(() => {
    const onHashChange = () => setActiveView(getViewFromHash())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  function handleViewChange(view: View) {
    window.location.hash = view
    setActiveView(view)
  }

  const showRightPanel = activeView === 'build'
  const appClasses = [
    'app',
    showRightPanel ? '' : 'app--no-sidebar',
    sidebarExpanded ? 'app--sidebar-expanded' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div className={appClasses}>
      <AppSidebar
        activeView={activeView}
        onViewChange={handleViewChange}
        expanded={sidebarExpanded}
        onToggleExpanded={() => setSidebarExpanded(!sidebarExpanded)}
      />
      <nav className="breadcrumb">
        <button className="breadcrumb-link" onClick={() => handleViewChange('character')}>
          <span className="breadcrumb-name">{selected.name}</span>
          {currentLife && (
            <>
              <span className="breadcrumb-race">{formatRace(currentLife.race)}</span>
              <span className="breadcrumb-classes">{formatClassSummary(currentLife)}</span>
            </>
          )}
          <span className="breadcrumb-life">Life {lifeNumber}</span>
        </button>
      </nav>
      {activeView === 'build' && (
        <>
          <div className="app-content">
            <CollapsibleSection title="Level Plan" defaultExpanded>
              <div className="section-placeholder">Level-by-level planning coming soon.</div>
            </CollapsibleSection>
            <CollapsibleSection title="Gear">
              <div className="section-placeholder">Gear planning coming soon.</div>
            </CollapsibleSection>
            <CollapsibleSection title="Enhancements">
              <div className="section-placeholder">Enhancement trees coming soon.</div>
            </CollapsibleSection>
            <CollapsibleSection title="Epic Destinies">
              <div className="section-placeholder">Epic destiny trees coming soon.</div>
            </CollapsibleSection>
          </div>
          <BuildSidePanel />
        </>
      )}
      {activeView === 'character' && <CharacterView />}
      {activeView === 'gear' && (
        <div className="app-content">
          <div className="section-placeholder">Gear planner coming soon.</div>
        </div>
      )}
      {activeView === 'enhancements' && (
        <div className="app-content">
          <div className="section-placeholder">Enhancement trees coming soon.</div>
        </div>
      )}
      {activeView === 'destinies' && (
        <div className="app-content">
          <div className="section-placeholder">Epic destiny trees coming soon.</div>
        </div>
      )}
    </div>
  )
}

export default App
