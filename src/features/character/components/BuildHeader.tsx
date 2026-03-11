import './BuildHeader.css'

const ABILITY_SCORES = [
  { label: 'STR', value: 16 },
  { label: 'DEX', value: 8 },
  { label: 'CON', value: 14 },
  { label: 'INT', value: 10 },
  { label: 'WIS', value: 12 },
  { label: 'CHA', value: 8 },
]

function BuildHeader() {
  return (
    <header className="build-header">
      <div className="build-header-top">
        <div className="build-brand-group">
          <span className="build-brand">DDO Builder</span>
          <div className="build-actions">
            <button className="build-action-btn">Save</button>
            <button className="build-action-btn">Load</button>
          </div>
        </div>
        <div className="build-info">
          <select defaultValue="human">
            <option value="human">Human</option>
            <option value="elf">Elf</option>
            <option value="dwarf">Dwarf</option>
            <option value="halfling">Halfling</option>
          </select>
          <span className="build-class">18 Paladin / 2 Rogue</span>
          <span className="build-level">Level 20</span>
        </div>
      </div>
      <div className="build-ability-scores">
        {ABILITY_SCORES.map((score) => (
          <div key={score.label} className="ability-score-chip">
            <span className="label">{score.label}</span>
            <span className="value">{score.value}</span>
          </div>
        ))}
      </div>
    </header>
  )
}

export default BuildHeader
