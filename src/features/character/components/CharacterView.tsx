import { useState } from 'react'
import type { Life } from '../types'
import {
  computeMismatchWarnings,
  formatClassSummary,
  formatRace,
  getCurrentLifeNumber,
} from '../utils'
import { useActiveCharacter } from '../hooks/useActiveCharacter'
import { ConfirmModal, StarIcon, PlusIcon } from '../../../components'
import { PastLifeStacks } from './PastLifeStacks'
import { LifeHistory, type ReincarnateResult } from './LifeHistory'
import './CharacterView.css'

function CharacterView() {
  const {
    characters,
    setCharacters,
    character: selected,
    currentLife,
    lifeNumbers,
    selection,
    setSelection,
    plannedBuilds,
    setPlannedBuilds,
    viewingPlannedBuild,
    selectCharacter,
    selectPlannedBuild,
    selectLife,
    setOverride,
    setBuildDesired,
  } = useActiveCharacter()

  const [showReincarnate, setShowReincarnate] = useState(false)
  const [applyConfirm, setApplyConfirm] = useState<{
    buildId: string
    desc: string
    warnings: string[]
  } | null>(null)

  const viewingLifeId = selection.lifeId
  const viewingPlannedBuildId = selection.plannedBuildId

  return (
    <div className="character-view">
      {/* Character list */}
      <div className="section-label">Your Characters</div>
      <div className="character-list">
        {characters.map((char) => {
          const charCurrentLife = char.lives[char.currentLifeIndex]
          const isActive = char.id === selection.characterId
          return (
            <div
              key={char.id}
              className={`character-row row-interactive ${isActive ? 'active' : ''}`}
              onClick={() => selectCharacter(char.id)}
            >
              <span className="character-marker">{isActive ? <StarIcon /> : ''}</span>
              <span className="character-name">{char.name}</span>
              <span className="character-server">{char.server}</span>
              <span className="character-class-summary">
                {charCurrentLife ? formatClassSummary(charCurrentLife) : '—'}
              </span>
              <span className="character-life-count">Life {getCurrentLifeNumber(char)}</span>
              <span className="character-row-actions">
                <button className="row-action-btn">Export</button>
                <button className="row-action-btn delete">Delete</button>
              </span>
            </div>
          )
        })}
      </div>
      <div className="character-list-actions">
        <button className="btn-ghost">
          <PlusIcon /> New Character
        </button>
        <button className="btn-ghost">Import JSON</button>
        <button
          className="btn-ghost import-ddo-btn"
          onClick={() => window.alert('DDO Builder V2 (.xml) import coming soon.')}
        >
          Import DDO Builder
        </button>
      </div>

      {/* Past lives */}
      <hr className="past-lives-divider" />
      <div className="past-lives-header">
        <h2>
          {viewingPlannedBuild
            ? `Past Lives — ${viewingPlannedBuild.name || 'Planned Build'} × ${selected.name}`
            : `Past Lives (${selected.name})`}
        </h2>
      </div>
      <div className="past-lives-content">
        <PastLifeStacks
          character={selected}
          viewingLifeId={viewingPlannedBuildId ? '' : viewingLifeId}
          plannedBuild={viewingPlannedBuild}
          onSetOverride={setOverride}
          onSetBuildDesired={viewingPlannedBuildId ? setBuildDesired : undefined}
        />
        <LifeHistory
          character={selected}
          lifeNumbers={lifeNumbers}
          viewingLifeId={viewingLifeId}
          showReincarnate={showReincarnate}
          onToggleReincarnate={() => setShowReincarnate(!showReincarnate)}
          onCancelReincarnate={() => setShowReincarnate(false)}
          onConfirmReincarnate={(result: ReincarnateResult) => {
            // TODO: implement actual reincarnation logic
            console.log('Reincarnate:', result)
            setShowReincarnate(false)
          }}
          onViewLife={selectLife}
          onCopyToPlanned={(lifeId) => {
            const life = selected.lives.find((l) => l.id === lifeId)
            if (!life) return
            const newBuild: Life = {
              ...life,
              id: crypto.randomUUID(),
              status: 'planned',
              reincarnation: undefined,
              notes: undefined,
            }
            setPlannedBuilds((prev) => [...prev, newBuild])
          }}
          onRenameLife={(lifeId, newName) => {
            setCharacters((prev) =>
              prev.map((c) => {
                if (c.id !== selection.characterId) return c
                return {
                  ...c,
                  lives: c.lives.map((l) => (l.id === lifeId ? { ...l, name: newName } : l)),
                }
              }),
            )
          }}
          plannedBuilds={plannedBuilds}
          viewingPlannedBuildId={viewingPlannedBuildId}
          onSelectPlannedBuild={selectPlannedBuild}
          onRenamePlannedBuild={(buildId: string, newName: string) => {
            setPlannedBuilds((prev) =>
              prev.map((b) => (b.id === buildId ? { ...b, name: newName } : b)),
            )
          }}
          onApplyPlannedBuild={(buildId: string) => {
            const build = plannedBuilds.find((b) => b.id === buildId)
            if (!build) return
            const desc = `${formatRace(build.race)} ${formatClassSummary(build)}`
            const warnings = computeMismatchWarnings(build.desiredPastLives, selected)
            setApplyConfirm({ buildId, desc, warnings })
          }}
          onDeletePlannedBuild={(buildId: string) => {
            setPlannedBuilds((prev) => prev.filter((b) => b.id !== buildId))
            if (viewingPlannedBuildId === buildId) {
              setSelection((prev) => ({
                ...prev,
                plannedBuildId: null,
                lifeId: currentLife?.id ?? '',
              }))
            }
          }}
          onAddPlannedBuild={() => {
            const newBuild: Life = {
              id: crypto.randomUUID(),
              name: '',
              race: 'human',
              classes: [{ classId: 'fighter', levels: 20 }],
              feats: [],
              enhancements: [],
              status: 'planned',
            }
            setPlannedBuilds((prev) => [...prev, newBuild])
          }}
        />
      </div>

      {applyConfirm && (
        <ConfirmModal
          title="Apply Planned Build"
          message={
            applyConfirm.warnings.length > 0
              ? `This will overwrite your current life's build data with "${applyConfirm.desc}". This cannot be undone.\n\nWarning: ${selected.name} is missing past lives this build expects:\n${applyConfirm.warnings.join('\n')}`
              : `This will overwrite your current life's build data with "${applyConfirm.desc}". This cannot be undone.`
          }
          confirmLabel="Apply"
          requireInput={applyConfirm.desc}
          onCancel={() => setApplyConfirm(null)}
          onConfirm={() => {
            const build = plannedBuilds.find((b) => b.id === applyConfirm.buildId)
            if (build) {
              setCharacters((prev) =>
                prev.map((c) => {
                  if (c.id !== selection.characterId) return c
                  const lives = c.lives.map((l, i) => {
                    if (i !== c.currentLifeIndex) return l
                    return {
                      ...l,
                      name: build.name || l.name,
                      race: build.race,
                      classes: [...build.classes],
                    }
                  })
                  return { ...c, lives }
                }),
              )
            }
            setApplyConfirm(null)
          }}
        />
      )}
    </div>
  )
}

export default CharacterView
