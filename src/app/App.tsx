import { useEffect, useState } from 'react'
import BuildHeader from '../features/character/components/BuildHeader'
import SidePanel from '../features/character/components/SidePanel'
import CharacterView from '../features/character/components/CharacterView'
import CollapsibleSection from '../features/shared/CollapsibleSection'
import './App.css'

type View = 'build' | 'character'

function getViewFromHash(): View {
  const hash = window.location.hash.replace('#', '')
  return hash === 'character' ? 'character' : 'build'
}

function App() {
  const [activeView, setActiveView] = useState<View>(getViewFromHash)

  useEffect(() => {
    const onHashChange = () => setActiveView(getViewFromHash())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  function handleViewChange(view: View) {
    window.location.hash = view
    setActiveView(view)
  }

  return (
    <div className={`app ${activeView === 'character' ? 'app--no-sidebar' : ''}`}>
      <BuildHeader activeView={activeView} onViewChange={handleViewChange} />
      {activeView === 'build' ? (
        <>
          <div className="app-content">
            <CollapsibleSection title="Level Plan" defaultExpanded>
              <div className="section-placeholder">
                Level-by-level planning coming soon.
              </div>
            </CollapsibleSection>
            <CollapsibleSection title="Gear">
              <div className="section-placeholder">
                Gear planning coming soon.
              </div>
            </CollapsibleSection>
            <CollapsibleSection title="Enhancements">
              <div className="section-placeholder">
                Enhancement trees coming soon.
              </div>
            </CollapsibleSection>
            <CollapsibleSection title="Epic Destinies">
              <div className="section-placeholder">
                Epic destiny trees coming soon.
              </div>
            </CollapsibleSection>
          </div>
          <SidePanel />
        </>
      ) : (
        <CharacterView />
      )}
    </div>
  )
}

export default App
