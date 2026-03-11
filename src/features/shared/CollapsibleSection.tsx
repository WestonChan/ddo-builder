import { useState } from 'react'
import './CollapsibleSection.css'

interface CollapsibleSectionProps {
  title: string
  defaultExpanded?: boolean
  children: React.ReactNode
}

function CollapsibleSection({
  title,
  defaultExpanded = false,
  children,
}: CollapsibleSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded)

  return (
    <div className="collapsible-section">
      <button
        className="collapsible-header"
        onClick={() => setExpanded(!expanded)}
      >
        <span className={`chevron ${expanded ? 'expanded' : ''}`}>&#9654;</span>
        {title}
      </button>
      <div className={`collapsible-content ${expanded ? 'expanded' : ''}`}>
        <div className="collapsible-content-inner">{children}</div>
      </div>
    </div>
  )
}

export default CollapsibleSection
