import { useState } from 'react'
import './SidePanel.css'

type Tab = 'stats' | 'feats'

const ABILITY_SCORES = [
  { label: 'STR', value: 18 },
  { label: 'DEX', value: 12 },
  { label: 'CON', value: 16 },
  { label: 'INT', value: 10 },
  { label: 'WIS', value: 14 },
  { label: 'CHA', value: 8 },
]

const STATS = [
  { label: 'HP', value: '420' },
  { label: 'SP', value: '300' },
  { label: 'AC', value: '85' },
  { label: 'PRR', value: '42' },
  { label: 'MRR', value: '30' },
  { label: 'Dodge', value: '18%' },
  { label: 'Fortification', value: '108%' },
]

const SAVES = [
  { label: 'Fortitude', value: '32' },
  { label: 'Reflex', value: '28' },
  { label: 'Will', value: '24' },
]

const COMBAT = [
  { label: 'BAB', value: '20' },
  { label: 'Melee Power', value: '78' },
  { label: 'Ranged Power', value: '42' },
  { label: 'Spell Power', value: '108' },
]

const ACTIVE_FEATS = [
  'Cleave',
  'Great Cleave',
  'Smite Evil',
  'Lay on Hands',
  'Turn Undead',
]

const PASSIVE_FEATS = [
  'Power Attack',
  'Two Handed Fighting',
  'Improved Critical: Slashing',
  'Toughness',
  'Evasion',
]

function StatsTab() {
  return (
    <>
      <div className="section-label">Ability Scores</div>
      <div className="ability-scores-grid">
        {ABILITY_SCORES.map((score) => (
          <div key={score.label} className="ability-score-row row-interactive">
            <span className="label">{score.label}</span>
            <span className="value">{score.value}</span>
          </div>
        ))}
      </div>
      <hr className="stats-separator" />
      {STATS.map((stat) => (
        <div key={stat.label} className="stat-row row-interactive">
          <span className="label">{stat.label}</span>
          <span className="value">{stat.value}</span>
        </div>
      ))}
      <hr className="stats-separator" />
      {SAVES.map((stat) => (
        <div key={stat.label} className="stat-row row-interactive">
          <span className="label">{stat.label}</span>
          <span className="value">{stat.value}</span>
        </div>
      ))}
      <hr className="stats-separator" />
      {COMBAT.map((stat) => (
        <div key={stat.label} className="stat-row row-interactive">
          <span className="label">{stat.label}</span>
          <span className="value">{stat.value}</span>
        </div>
      ))}
    </>
  )
}

function FeatsTab() {
  return (
    <>
      <div className="section-label">Active</div>
      {ACTIVE_FEATS.map((feat) => (
        <div key={feat} className="feat-entry row-interactive">
          {feat}
        </div>
      ))}
      <div className="section-label">Passive</div>
      {PASSIVE_FEATS.map((feat) => (
        <div key={feat} className="feat-entry row-interactive">
          {feat}
        </div>
      ))}
    </>
  )
}

function SidePanel() {
  const [activeTab, setActiveTab] = useState<Tab>('stats')

  return (
    <aside className="side-panel">
      <div className="side-panel-tabs">
        <button
          className={`side-panel-tab ${activeTab === 'stats' ? 'active' : ''}`}
          onClick={() => setActiveTab('stats')}
        >
          Stats
        </button>
        <button
          className={`side-panel-tab ${activeTab === 'feats' ? 'active' : ''}`}
          onClick={() => setActiveTab('feats')}
        >
          Feats
        </button>
      </div>
      <div className="side-panel-content">
        {activeTab === 'stats' ? <StatsTab /> : <FeatsTab />}
      </div>
    </aside>
  )
}

export default SidePanel
