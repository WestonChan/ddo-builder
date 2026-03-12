import { useState } from 'react'
import { STUB_CHARACTERS } from '../data/stubCharacters'
import { formatClassSummary, formatRace } from '../utils'
import { ConfirmModal } from '../../shared/ConfirmModal'
import { PastLifeStacks } from './PastLifeStacks'
import { LifeHistory, type ReincarnateResult } from './LifeHistory'
import './CharacterView.css'

function CharacterView() {
  const [characters, setCharacters] = useState(STUB_CHARACTERS)
  const [selectedId, setSelectedId] = useState(STUB_CHARACTERS[0].id)
  const [showReincarnate, setShowReincarnate] = useState(false)
  const [applyConfirm, setApplyConfirm] = useState<{
    lifeId: string
    desc: string
  } | null>(null)

  const selected = characters.find((c) => c.id === selectedId) ?? characters[0]

  return (
    <div className="character-view">
      {/* Character list */}
      <div className="section-label">Your Characters</div>
      <div className="character-list">
        {characters.map((char) => {
          const currentLife = char.lives[char.currentLifeIndex]
          const isActive = char.id === selectedId
          return (
            <div
              key={char.id}
              className={`character-row row-interactive ${isActive ? 'active' : ''}`}
              onClick={() => setSelectedId(char.id)}
            >
              <span className="character-marker">
                {isActive ? '★' : ''}
              </span>
              <span className="character-name">{char.name}</span>
              <span className="character-server">{char.server}</span>
              <span className="character-class-summary">
                {currentLife ? formatClassSummary(currentLife) : '—'}
              </span>
              <span className="character-life-count">
                Life {char.currentLifeIndex + 1}
              </span>
              <span className="character-row-actions">
                <button className="btn-ghost-sm">Export</button>
                <button className="btn-ghost-sm delete">Delete</button>
              </span>
            </div>
          )
        })}
      </div>
      <div className="character-list-actions">
        <button className="btn-ghost">+ New Character</button>
        <button className="btn-ghost">Import JSON</button>
        <button
          className="btn-ghost import-ddo-btn"
          onClick={() =>
            window.alert('DDO Builder V2 (.xml) import coming soon.')
          }
        >
          Import DDO Builder
        </button>
      </div>

      {/* Past lives */}
      <hr className="past-lives-divider" />
      <div className="past-lives-header">
        <h2>Past Lives ({selected.name})</h2>
      </div>
      <div className="past-lives-content">
        <PastLifeStacks
          character={selected}
          onSetOverride={(category, id, value) => {
            setCharacters((prev) =>
              prev.map((c) => {
                if (c.id !== selectedId) return c
                const overrides = { ...c.pastLifeOverrides }
                const catMap = { ...overrides[category as keyof typeof overrides] }
                if (value <= 0) {
                  delete catMap[id]
                } else {
                  catMap[id] = value
                }
                return {
                  ...c,
                  pastLifeOverrides: { ...overrides, [category]: catMap },
                }
              }),
            )
          }}
        />
        <LifeHistory
          character={selected}
          showReincarnate={showReincarnate}
          onToggleReincarnate={() => setShowReincarnate(!showReincarnate)}
          onCancelReincarnate={() => setShowReincarnate(false)}
          onConfirmReincarnate={(result: ReincarnateResult) => {
            // TODO: implement actual reincarnation logic
            console.log('Reincarnate:', result)
            setShowReincarnate(false)
          }}
          onApplyPlanned={(lifeId) => {
            const life = selected.lives.find((l) => l.id === lifeId)
            if (!life) return
            const currentLife = selected.lives[selected.currentLifeIndex]
            const isNewLife = !currentLife || currentLife.classes.length === 0
            if (isNewLife) {
              console.log('Apply planned life (new):', lifeId)
              return
            }
            const desc = `${formatRace(life.race)} ${formatClassSummary(life)}`
            setApplyConfirm({ lifeId, desc })
          }}
        />
      </div>

      {applyConfirm && (
        <ConfirmModal
          title="Apply Planned Life"
          message={`This will overwrite your current life's build data with "${applyConfirm.desc}". This cannot be undone.`}
          confirmLabel="Apply"
          requireInput={applyConfirm.desc}
          onCancel={() => setApplyConfirm(null)}
          onConfirm={() => {
            // TODO: implement apply planned life logic
            console.log('Apply planned life:', applyConfirm.lifeId)
            setApplyConfirm(null)
          }}
        />
      )}
    </div>
  )
}

export default CharacterView
