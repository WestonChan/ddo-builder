import './BuildHeader.css'

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

function applyTheme(accent: string, hover: string) {
  document.documentElement.style.setProperty('--accent', accent)
  document.documentElement.style.setProperty('--accent-hover', hover)
}

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
          {location.hostname === 'localhost' && (
            <select
              className="theme-selector"
              defaultValue=""
              onChange={(e) => {
                const theme = THEMES.find((t) => t.name === e.target.value)
                if (theme) applyTheme(theme.accent, theme.hover)
              }}
            >
              <option value="" disabled>
                Theme
              </option>
              {THEMES.map((t) => (
                <option key={t.name} value={t.name}>
                  {t.name}
                </option>
              ))}
            </select>
          )}
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
