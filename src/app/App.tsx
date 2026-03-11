import BuildHeader from '../features/character/components/BuildHeader'
import SidePanel from '../features/character/components/SidePanel'
import CollapsibleSection from '../features/shared/CollapsibleSection'
import './App.css'

function App() {
  return (
    <div className="app">
      <BuildHeader />
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
    </div>
  )
}

export default App
