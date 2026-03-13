import { useCallback, useState } from 'react'
import type { Character, Life, PastLifeCounts } from '../types'
import { PAST_LIFE_DEFS, type PastLifeDef } from '../data/pastLifeDefs'
import { computeHistoryStacks, EPIC_SPHERE_LIST, formatBonusList } from '../utils'
import { TooltipWrapper, ChevronDownIcon, ChevronRightIcon } from '../../../components'
import { useAddRemoveInput } from '../../../hooks'

// --- Normal mode StackBar (existing behavior) ---

function StackBarNormal({
  stacks,
  max,
  fromHistory,
  fromCurrentHistory,
  currentStacks,
}: {
  stacks: number
  max: number
  fromHistory: number
  fromCurrentHistory: number
  currentStacks: number
}) {
  return (
    <span className="stack-bar">
      {Array.from({ length: max }, (_, i) => {
        const isFilled = i < stacks
        const isLocked = i < fromHistory
        const isCurrentHasLocked = i < fromCurrentHistory
        const isCurrentHasFilled = !isCurrentHasLocked && i < currentStacks
        const pip = (
          <span
            key={i}
            className={`stack-pip ${isFilled ? 'filled' : ''} ${isLocked ? 'locked' : ''} ${isCurrentHasLocked ? 'current-has' : ''} ${isCurrentHasFilled ? 'current-has-filled' : ''}`}
          />
        )
        return isLocked ? (
          <TooltipWrapper
            key={i}
            text="Earned from a completed reincarnation — cannot be removed manually"
          >
            {pip}
          </TooltipWrapper>
        ) : (
          pip
        )
      })}
    </span>
  )
}

// --- Overlay mode StackBar (planned build view) ---

function StackBarOverlay({
  buildDesired,
  charHas,
  charFromHistory,
  max,
}: {
  buildDesired: number
  charHas: number
  charFromHistory: number
  max: number
}) {
  return (
    <span className="stack-bar">
      {Array.from({ length: max }, (_, i) => {
        const buildWants = i < buildDesired
        const charOwns = i < charHas
        const isFromHistory = i < charFromHistory

        let pipClass = 'stack-pip'
        let tooltip = ''

        if (buildWants) {
          pipClass += charOwns && isFromHistory ? ' locked' : ' filled'
          if (!charOwns) pipClass += ' pip-missing'
        } else if (charOwns) {
          pipClass += isFromHistory ? ' pip-has-locked' : ' pip-has-filled'
        }

        if (buildWants && charOwns) {
          tooltip = 'Character has this — build needs it'
        } else if (!buildWants && charOwns) {
          tooltip = "Character has this — build doesn't need it"
        } else if (buildWants && !charOwns) {
          tooltip = "Build needs this — character doesn't have it yet"
        }

        const pip = <span key={i} className={pipClass} />

        return tooltip ? (
          <TooltipWrapper key={i} text={tooltip}>
            {pip}
          </TooltipWrapper>
        ) : (
          pip
        )
      })}
    </span>
  )
}

// --- StackRow ---

function StackRow({
  def,
  stacks,
  fromHistory,
  fromCurrentHistory,
  currentStacks,
  onSetStacks,
  overlay,
}: {
  def: PastLifeDef
  stacks: number
  fromHistory: number
  fromCurrentHistory: number
  currentStacks: number
  onSetStacks: (value: number) => void
  overlay?: { charHas: number; charFromHistory: number }
}) {
  const hasStacks = stacks > 0

  const increment = useCallback(() => {
    if (stacks < def.max) onSetStacks(stacks + 1)
  }, [stacks, def.max, onSetStacks])

  const minStacks = overlay ? 0 : fromHistory
  const decrement = useCallback(() => {
    if (stacks > minStacks) onSetStacks(stacks - 1)
  }, [stacks, minStacks, onSetStacks])

  const { ref, onClick, onContextMenu } = useAddRemoveInput(increment, decrement)

  // Bonus text based on current stacks
  const earnedText = formatBonusList(def.bonuses.slice(0, stacks))
  const rawUnearned = formatBonusList(def.bonuses.slice(stacks))
  const unearnedText = rawUnearned !== earnedText ? rawUnearned : ''

  return (
    <div
      ref={ref as React.RefObject<HTMLDivElement>}
      className={`stack-row row-interactive ${hasStacks || (overlay && overlay.charHas > 0) ? '' : 'empty'}`}
      onClick={onClick}
      onContextMenu={onContextMenu}
    >
      <span className="stack-name">{def.name}</span>
      {overlay ? (
        <StackBarOverlay
          buildDesired={stacks}
          charHas={overlay.charHas}
          charFromHistory={overlay.charFromHistory}
          max={def.max}
        />
      ) : (
        <StackBarNormal
          stacks={stacks}
          max={def.max}
          fromHistory={fromHistory}
          fromCurrentHistory={fromCurrentHistory}
          currentStacks={currentStacks}
        />
      )}
      <span className="stack-count">
        {stacks}/{def.max}
      </span>
      <span className="stack-bonus">
        {earnedText && <span className="bonus-earned">{earnedText}</span>}
        {unearnedText && <span className="bonus-remaining">{unearnedText}</span>}
      </span>
    </div>
  )
}

// --- StackSection ---

function StackSection({
  label,
  defs,
  overrides,
  historyStacks,
  currentHistoryStacks,
  onSetOverride,
  buildDesired,
  charStacks,
}: {
  label: string
  defs: PastLifeDef[]
  overrides: Record<string, number>
  historyStacks: Record<string, number>
  currentHistoryStacks: Record<string, number>
  onSetOverride: (id: string, value: number) => void
  buildDesired?: Record<string, number>
  charStacks?: Record<string, number>
}) {
  const isOverlay = !!buildDesired
  return (
    <>
      <div className="section-label">{label}</div>
      {defs.map((def) => {
        if (isOverlay) {
          // Overlay mode: pips = build's desired stacks, overlay = character's actual
          const stacks = Math.min(buildDesired[def.id] ?? 0, def.max)
          const fromHistory = Math.min(historyStacks[def.id] ?? 0, def.max)
          const fromOverride = (charStacks ?? {})[def.id] ?? 0
          const charHas = Math.min(fromHistory + fromOverride, def.max)
          return (
            <StackRow
              key={def.id}
              def={def}
              stacks={stacks}
              fromHistory={0}
              fromCurrentHistory={0}
              currentStacks={0}
              onSetStacks={(value) => onSetOverride(def.id, value)}
              overlay={{ charHas, charFromHistory: fromHistory }}
            />
          )
        }
        // Normal mode
        const fromHistory = Math.min(historyStacks[def.id] ?? 0, def.max)
        const fromCurrentHistory = Math.min(currentHistoryStacks[def.id] ?? 0, def.max)
        const fromOverride = overrides[def.id] ?? 0
        const stacks = Math.min(fromHistory + fromOverride, def.max)
        const currentStacks = Math.min(fromCurrentHistory + fromOverride, def.max)
        return (
          <StackRow
            key={def.id}
            def={def}
            stacks={stacks}
            fromHistory={fromHistory}
            fromCurrentHistory={fromCurrentHistory}
            currentStacks={currentStacks}
            onSetStacks={(value) => onSetOverride(def.id, Math.max(0, value - fromHistory))}
          />
        )
      })}
    </>
  )
}

// --- BonusSummary ---

interface ActiveBonus {
  label: string
  value: string
}

function BonusSummary({ bonuses }: { bonuses: ActiveBonus[] }) {
  const isDesktop = typeof window !== 'undefined' && window.innerWidth > 768
  const [expanded, setExpanded] = useState(isDesktop)

  return (
    <div className="bonus-summary">
      <div className="bonus-summary-header" onClick={() => setExpanded(!expanded)}>
        <span className="bonus-toggle">
          {expanded ? <ChevronDownIcon /> : <ChevronRightIcon />}
        </span>
        <span className="section-label">Active Bonuses ({bonuses.length})</span>
      </div>
      <div className={`bonus-rows ${expanded ? 'expanded' : ''}`}>
        <div className="bonus-rows-inner">
          {bonuses.map((b) => (
            <div key={b.label} className="bonus-row">
              <span className="bonus-value">
                {b.label}: {b.value}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

const STACK_SECTIONS: {
  category: keyof PastLifeCounts
  label: string
  filter?: (d: PastLifeDef) => boolean
}[] = [
  { category: 'heroic', label: 'Class' },
  { category: 'racial', label: 'Racial' },
  { category: 'iconic', label: 'Iconic' },
  ...EPIC_SPHERE_LIST.map(({ sphere, label }) => ({
    category: 'epic' as const,
    label: `Epic — ${label}`,
    filter: (d: PastLifeDef) => d.sphere === sphere,
  })),
]

// --- PastLifeStacks (main export) ---

export function PastLifeStacks({
  character,
  viewingLifeId,
  plannedBuild,
  onSetOverride,
  onSetBuildDesired,
}: {
  character: Character
  viewingLifeId: string
  plannedBuild?: Life
  onSetOverride: (category: keyof PastLifeCounts, id: string, value: number) => void
  onSetBuildDesired?: (category: keyof PastLifeCounts, id: string, value: number) => void
}) {
  const isOverlay = !!plannedBuild

  // Character's actual stacks (used in both modes)
  const viewingIndex = character.lives.findIndex((l) => l.id === viewingLifeId)
  const livesBeforeViewed =
    viewingIndex >= 0 ? character.lives.slice(0, viewingIndex) : character.lives
  const historyStacks = computeHistoryStacks(livesBeforeViewed)
  const livesBeforeCurrent = character.lives.slice(0, character.currentLifeIndex)
  const currentHistoryStacks = computeHistoryStacks(livesBeforeCurrent)
  const o = character.untrackedLives

  // Build's desired stacks (only in overlay mode)
  const desired: PastLifeCounts | undefined = plannedBuild?.desiredPastLives

  const totalCompleted = livesBeforeViewed.filter((l) => l.status === 'completed').length

  // In overlay mode, use onSetBuildDesired; in normal mode, use onSetOverride
  const handleSet = isOverlay && onSetBuildDesired ? onSetBuildDesired : onSetOverride

  // Collect active bonuses (normal mode only — overlay shows build's desired bonuses)
  const activeBonuses: ActiveBonus[] = []
  if (!isOverlay) {
    for (const def of PAST_LIFE_DEFS) {
      const catOverrides = o[def.category as keyof typeof o] ?? {}
      const fromHistory = Math.min(historyStacks[def.id] ?? 0, def.max)
      const fromOverride = catOverrides[def.id] ?? 0
      const stacks = Math.min(fromHistory + fromOverride, def.max)
      if (stacks > 0) {
        activeBonuses.push({
          label: def.name,
          value: formatBonusList(def.bonuses.slice(0, stacks)),
        })
      }
    }
  }

  return (
    <div className="past-life-stacks">
      {STACK_SECTIONS.map(({ category, label, filter }) => {
        const defs = PAST_LIFE_DEFS.filter((d) => d.category === category && (!filter || filter(d)))
        return (
          <StackSection
            key={label}
            label={label}
            defs={defs}
            overrides={o[category]}
            historyStacks={historyStacks}
            currentHistoryStacks={currentHistoryStacks}
            onSetOverride={(id, v) => handleSet(category, id, v)}
            buildDesired={isOverlay ? (desired?.[category] ?? {}) : undefined}
            charStacks={isOverlay ? o[category] : undefined}
          />
        )
      })}
      <div className="stacks-hint">
        {isOverlay
          ? 'Tap to add desired · long-press to remove'
          : 'Tap to add · long-press to remove'}
      </div>
      {!isOverlay && <div className="total-past-lives">Total Past Lives: {totalCompleted}</div>}
      {activeBonuses.length > 0 && <BonusSummary bonuses={activeBonuses} />}
    </div>
  )
}
