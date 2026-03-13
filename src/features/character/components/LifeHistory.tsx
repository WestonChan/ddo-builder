import { useState } from 'react'
import type { Character, Life, ReincarnationType } from '../types'
import { PAST_LIFE_DEFS } from '../data/pastLifeDefs'
import {
  capitalize,
  EPIC_SPHERE_LIST,
  formatClassSummary,
  formatRace,
  getPlannedBuildPastLives,
} from '../utils'
import { EditableText, StarIcon, TrashIcon, PlusIcon } from '../../../components'

// --- Reincarnate types ---

export type ReincarnateResult =
  | { mode: 'epic'; epicFeatId: string }
  | { mode: 'true'; type: ReincarnationType }

type ReincarnateMode = 'epic' | 'true'

const TRUE_REINCARNATION_TYPES: { value: ReincarnationType; label: string }[] = [
  { value: 'heroic', label: 'Class (Heroic TR)' },
  { value: 'racial', label: 'Racial' },
  { value: 'iconic', label: 'Iconic' },
]

const EPIC_FEATS_BY_SPHERE = EPIC_SPHERE_LIST.map((s) => ({
  sphere: s,
  feats: PAST_LIFE_DEFS.filter((d) => d.category === 'epic' && d.sphere === s.sphere),
}))

// --- ReincarnatePanel ---

function ReincarnatePanel({
  onCancel,
  onConfirm,
}: {
  onCancel: () => void
  onConfirm: (result: ReincarnateResult) => void
}) {
  const [mode, setMode] = useState<ReincarnateMode>('epic')
  const [epicFeatId, setEpicFeatId] = useState(EPIC_FEATS_BY_SPHERE[0].feats[0]?.id ?? '')
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
          <label>Epic Past Life Feat</label>
          <div className="epic-feat-select">
            {EPIC_FEATS_BY_SPHERE.map(({ sphere, feats }) => (
              <div key={sphere.sphere} className="epic-feat-group">
                <div className="epic-feat-group-label">{sphere.label}</div>
                <div className="reincarnate-type-options">
                  {feats.map((f) => (
                    <button
                      key={f.id}
                      className={`reincarnate-type-btn ${epicFeatId === f.id ? 'active' : ''}`}
                      onClick={() => setEpicFeatId(f.id)}
                    >
                      {f.name}
                    </button>
                  ))}
                </div>
              </div>
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
              mode === 'epic' ? { mode: 'epic', epicFeatId } : { mode: 'true', type: trueType },
            )
          }
        >
          Confirm
        </button>
      </div>
    </div>
  )
}

// --- LifeRow (shared layout for all history/planned entries) ---

function LifeRow({
  active,
  lifeNumber,
  name,
  summary,
  onClick,
  onRename,
  className,
  children,
}: {
  active: boolean
  lifeNumber?: number | string
  name: string
  summary: string
  onClick: () => void
  onRename: (name: string) => void
  className?: string
  children?: React.ReactNode
}) {
  return (
    <div
      className={`life-entry row-interactive ${className ?? ''} ${active ? 'viewing' : ''}`}
      onClick={onClick}
    >
      <span className="life-marker">{active ? <StarIcon /> : ''}</span>
      {lifeNumber != null && <span className="life-number">{lifeNumber}</span>}
      {active ? (
        <EditableText
          value={name}
          placeholder="Name..."
          className="life-name"
          onCommit={onRename}
        />
      ) : (
        <span className="life-name">
          {name || <span className="editable-text-placeholder">Name...</span>}
        </span>
      )}
      <span className="life-summary">{summary}</span>
      <div className="life-actions">{children}</div>
    </div>
  )
}

// --- LifeHistory ---

export function LifeHistory({
  character,
  lifeNumbers,
  viewingLifeId,
  showReincarnate,
  onToggleReincarnate,
  onCancelReincarnate,
  onConfirmReincarnate,
  onViewLife,
  onCopyToPlanned,
  onRenameLife,
  plannedBuilds,
  viewingPlannedBuildId,
  onSelectPlannedBuild,
  onRenamePlannedBuild,
  onApplyPlannedBuild,
  onDeletePlannedBuild,
  onAddPlannedBuild,
}: {
  character: Character
  lifeNumbers: Map<string, number>
  viewingLifeId: string
  showReincarnate: boolean
  onToggleReincarnate: () => void
  onCancelReincarnate: () => void
  onConfirmReincarnate: (result: ReincarnateResult) => void
  onViewLife: (lifeId: string) => void
  onCopyToPlanned: (lifeId: string) => void
  onRenameLife: (lifeId: string, newName: string) => void
  plannedBuilds: Life[]
  viewingPlannedBuildId: string | null
  onSelectPlannedBuild: (buildId: string) => void
  onRenamePlannedBuild: (buildId: string, newName: string) => void
  onApplyPlannedBuild: (buildId: string) => void
  onDeletePlannedBuild: (buildId: string) => void
  onAddPlannedBuild: () => void
}) {
  const completed = character.lives.filter((l) => l.status === 'completed')
  const current = character.lives.filter((l) => l.status === 'current')
  const buildDesc = (life: Life) => `${formatRace(life.race)} ${formatClassSummary(life)}`

  const reincLabel = (life: Life) => {
    if (!life.reincarnation) return ''
    const r = life.reincarnation
    if (r.type === 'epic') {
      const feat = PAST_LIFE_DEFS.find((d) => d.id === r.epicFeatId)
      return `Epic TR: ${feat?.name ?? r.epicFeatId ?? ''}`
    }
    return `${capitalize(r.type)} TR`
  }

  return (
    <div>
      <div className="life-history-title">Reincarnation History</div>
      {/* Completed — flat chronological list of all reincarnation events */}
      {completed.length > 0 && <div className="section-label">Completed</div>}
      {completed.map((life) => {
        const n = lifeNumbers.get(life.id)
        return (
          <LifeRow
            key={life.id}
            active={viewingLifeId === life.id}
            lifeNumber={n != null ? `Life ${n}` : undefined}
            name={life.name}
            summary={`${reincLabel(life)} — ${buildDesc(life)}`}
            onClick={() => onViewLife(life.id)}
            onRename={(name) => onRenameLife(life.id, name)}
          >
            <button
              className="row-action-btn"
              onClick={(e) => {
                e.stopPropagation()
                onCopyToPlanned(life.id)
              }}
            >
              Copy to Planned
            </button>
          </LifeRow>
        )
      })}

      {/* Current life */}
      {current.map((life) => (
        <div key={life.id}>
          <div className="section-label">Current</div>
          <LifeRow
            active={viewingLifeId === life.id}
            lifeNumber={`Life ${lifeNumbers.get(life.id) ?? '?'}`}
            name={life.name}
            summary={buildDesc(life)}
            className="current-life-entry"
            onClick={() => onViewLife(life.id)}
            onRename={(name) => onRenameLife(life.id, name)}
          >
            {completed.length > 0 && (
              <button
                className="row-action-btn"
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
              className="row-action-btn btn-primary-sm"
              onClick={(e) => {
                e.stopPropagation()
                onToggleReincarnate()
              }}
            >
              Reincarnate
            </button>
          </LifeRow>
          {showReincarnate && (
            <ReincarnatePanel onCancel={onCancelReincarnate} onConfirm={onConfirmReincarnate} />
          )}
        </div>
      ))}

      {/* Planned builds (global) */}
      <div className="section-label">Planned</div>
      {plannedBuilds.map((build) => {
        const pastLives = getPlannedBuildPastLives(build)
        return (
          <LifeRow
            key={build.id}
            active={viewingPlannedBuildId === build.id}
            lifeNumber={`Needs ${pastLives} PLs`}
            name={build.name}
            summary={buildDesc(build)}
            onClick={() => onSelectPlannedBuild(build.id)}
            onRename={(name) => onRenamePlannedBuild(build.id, name)}
          >
            <button
              className="row-action-btn"
              onClick={(e) => {
                e.stopPropagation()
                onApplyPlannedBuild(build.id)
              }}
            >
              Apply
            </button>
            <button
              className="row-action-btn delete"
              onClick={(e) => {
                e.stopPropagation()
                onDeletePlannedBuild(build.id)
              }}
              aria-label="Delete planned build"
            >
              <TrashIcon />
            </button>
          </LifeRow>
        )
      })}
      <button className="add-planned-life-btn" onClick={onAddPlannedBuild}>
        <PlusIcon /> Add Planned Build
      </button>
    </div>
  )
}
