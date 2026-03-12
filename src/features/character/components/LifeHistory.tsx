import { useState } from 'react'
import type { Character, EpicSphere, Life, ReincarnationType } from '../types'
import { capitalize, formatClassSummary, formatRace } from '../utils'

// --- Reincarnate types ---

export type ReincarnateResult =
  | { mode: 'epic'; sphere: EpicSphere }
  | { mode: 'true'; type: ReincarnationType }

type ReincarnateMode = 'epic' | 'true'

const TRUE_REINCARNATION_TYPES: { value: ReincarnationType; label: string }[] = [
  { value: 'heroic', label: 'Heroic' },
  { value: 'racial', label: 'Racial' },
  { value: 'iconic', label: 'Iconic' },
]

const EPIC_SPHERES: { value: EpicSphere; label: string }[] = [
  { value: 'arcane', label: 'Arcane' },
  { value: 'divine', label: 'Divine' },
  { value: 'martial', label: 'Martial' },
  { value: 'primal', label: 'Primal' },
]

// --- ReincarnatePanel ---

function ReincarnatePanel({
  onCancel,
  onConfirm,
}: {
  onCancel: () => void
  onConfirm: (result: ReincarnateResult) => void
}) {
  const [mode, setMode] = useState<ReincarnateMode>('epic')
  const [epicSphere, setEpicSphere] = useState<EpicSphere>('martial')
  const [trueType, setTrueType] = useState<ReincarnationType>('heroic')

  return (
    <div className="reincarnate-panel">
      <div className="reincarnate-panel-header">Reincarnate</div>
      <div className="reincarnate-panel-field">
        <label>Reincarnation type</label>
        <div className="reincarnate-type-options">
          <button
            className={`reincarnate-type-btn ${mode === 'epic' ? 'active' : ''}`}
            onClick={() => setMode('epic')}
          >
            Epic TR
          </button>
          <button
            className={`reincarnate-type-btn ${mode === 'true' ? 'active' : ''}`}
            onClick={() => setMode('true')}
          >
            True Reincarnate
          </button>
        </div>
      </div>
      {mode === 'epic' && (
        <div className="reincarnate-panel-field">
          <label>Epic Sphere</label>
          <div className="reincarnate-type-options">
            {EPIC_SPHERES.map((es) => (
              <button
                key={es.value}
                className={`reincarnate-type-btn ${epicSphere === es.value ? 'active' : ''}`}
                onClick={() => setEpicSphere(es.value)}
              >
                {es.label}
              </button>
            ))}
          </div>
        </div>
      )}
      {mode === 'true' && (
        <div className="reincarnate-panel-field">
          <label>This ends the current life and starts a new build</label>
          <div className="reincarnate-type-options">
            {TRUE_REINCARNATION_TYPES.map((rt) => (
              <button
                key={rt.value}
                className={`reincarnate-type-btn ${trueType === rt.value ? 'active' : ''}`}
                onClick={() => setTrueType(rt.value)}
              >
                {rt.label}
              </button>
            ))}
          </div>
        </div>
      )}
      <div className="reincarnate-panel-actions">
        <button className="btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button
          className="btn-primary"
          onClick={() =>
            onConfirm(
              mode === 'epic'
                ? { mode: 'epic', sphere: epicSphere }
                : { mode: 'true', type: trueType },
            )
          }
        >
          Confirm
        </button>
      </div>
    </div>
  )
}

// --- LifeHistory ---

export function LifeHistory({
  character,
  showReincarnate,
  onToggleReincarnate,
  onCancelReincarnate,
  onConfirmReincarnate,
  onApplyPlanned,
}: {
  character: Character
  showReincarnate: boolean
  onToggleReincarnate: () => void
  onCancelReincarnate: () => void
  onConfirmReincarnate: (result: ReincarnateResult) => void
  onApplyPlanned: (lifeId: string) => void
}) {
  const completed = character.lives.filter((l) => l.status === 'completed')
  const current = character.lives.filter((l) => l.status === 'current')
  const planned = character.lives.filter((l) => l.status === 'planned')
  const buildDesc = (life: Life) =>
    `${formatRace(life.race)} ${formatClassSummary(life)}`

  const reincLabel = (life: Life) => {
    if (!life.reincarnation) return ''
    const r = life.reincarnation
    if (r.type === 'epic') return `Epic TR: ${capitalize(r.epicSphere ?? '')}`
    return `${capitalize(r.type)} TR`
  }

  return (
    <div>
      <div className="life-history-title">Reincarnation History</div>
      {/* Completed — flat chronological list of all reincarnation events */}
      {completed.length > 0 && (
        <div className="section-label">Completed</div>
      )}
      {completed.map((life) => (
        <div
          key={life.id}
          className={`life-entry row-interactive ${life.reincarnation?.type === 'epic' ? 'epic-tr-entry' : 'true-tr-entry'}`}
        >
          <span className="life-marker" />
          <span className={`life-label ${life.reincarnation?.type === 'epic' ? 'epic-label' : ''}`}>
            {reincLabel(life)}
          </span>
          <span className="life-summary">— {buildDesc(life)}</span>
        </div>
      ))}

      {/* Current life */}
      {current.map((life) => (
        <div key={life.id}>
          <div className="section-label">Current</div>
          <div className="life-entry row-interactive current-life-entry">
            <span className="life-marker">★</span>
            <span className="life-summary">{buildDesc(life)}</span>
            {completed.length > 0 && (
              <button
                className="btn-ghost-sm"
                onClick={(e) => {
                  e.stopPropagation()
                  // TODO: undo last reincarnation
                  console.log('Undo reincarnation')
                }}
              >
                Undo
              </button>
            )}
            <button
              className="reincarnate-btn"
              onClick={(e) => {
                e.stopPropagation()
                onToggleReincarnate()
              }}
            >
              Reincarnate
            </button>
          </div>
          {showReincarnate && (
            <ReincarnatePanel
              onCancel={onCancelReincarnate}
              onConfirm={onConfirmReincarnate}
            />
          )}
        </div>
      ))}

      {/* Planned lives */}
      {planned.length > 0 && (
        <div className="section-label">Planned</div>
      )}
      {planned.map((life) => (
        <div key={life.id} className="life-entry row-interactive">
          <button
            className="btn-ghost-sm"
            onClick={(e) => {
              e.stopPropagation()
              onApplyPlanned(life.id)
            }}
          >
            Apply
          </button>
          <span className="life-summary">
            {buildDesc(life)}
          </span>
        </div>
      ))}

      <button className="add-planned-life-btn">+ Add Planned Life</button>
    </div>
  )
}
