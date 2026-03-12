import { useCallback, useState } from 'react'
import type { Character } from '../types'
import { PAST_LIFE_DEFS, type PastLifeDef } from '../data/pastLifeDefs'
import { computeHistoryStacks } from '../utils'
import { TooltipWrapper } from '../../shared/Tooltip'
import { useAddRemoveInput } from '../../shared/useAddRemoveInput'

function StackBar({ stacks, max, fromHistory }: { stacks: number; max: number; fromHistory: number }) {
  return (
    <span className="stack-bar">
      {Array.from({ length: max }, (_, i) => {
        const pip = (
          <span
            key={i}
            className={`stack-pip ${i < stacks ? 'filled' : ''} ${i < fromHistory ? 'locked' : ''}`}
          />
        )
        return i < fromHistory ? (
          <TooltipWrapper key={i} text="Earned from a completed reincarnation — cannot be removed manually">
            {pip}
          </TooltipWrapper>
        ) : (
          pip
        )
      })}
    </span>
  )
}

function StackRow({
  def,
  stacks,
  fromHistory,
  onSetStacks,
}: {
  def: PastLifeDef
  stacks: number
  fromHistory: number
  onSetStacks: (value: number) => void
}) {
  const hasStacks = stacks > 0

  const increment = useCallback(() => {
    if (stacks < def.max) onSetStacks(stacks + 1)
  }, [stacks, def.max, onSetStacks])

  const decrement = useCallback(() => {
    if (stacks > fromHistory) onSetStacks(stacks - 1)
  }, [stacks, fromHistory, onSetStacks])

  const { ref, onClick, onContextMenu } = useAddRemoveInput(increment, decrement)

  return (
    <div
      ref={ref as React.RefObject<HTMLDivElement>}
      className={`stack-row row-interactive ${hasStacks ? '' : 'empty'}`}
      onClick={onClick}
      onContextMenu={onContextMenu}
    >
      <span className="stack-name">{def.name}</span>
      <StackBar stacks={stacks} max={def.max} fromHistory={fromHistory} />
      <span className="stack-count">{stacks}/{def.max}</span>
      <span className="stack-bonus">{def.bonus}</span>
    </div>
  )
}

function StackSection({
  label,
  defs,
  overrides,
  historyStacks,
  onSetOverride,
}: {
  label: string
  defs: PastLifeDef[]
  overrides: Record<string, number>
  historyStacks: Record<string, number>
  onSetOverride: (id: string, value: number) => void
}) {
  return (
    <>
      <div className="section-label">{label}</div>
      {defs.map((def) => {
        const fromHistory = Math.min(historyStacks[def.id] ?? 0, def.max)
        const fromOverride = overrides[def.id] ?? 0
        const stacks = Math.min(Math.max(fromHistory, fromOverride), def.max)
        return (
          <StackRow
            key={def.id}
            def={def}
            stacks={stacks}
            fromHistory={fromHistory}
            onSetStacks={(value) => onSetOverride(def.id, value)}
          />
        )
      })}
    </>
  )
}

interface ActiveBonus {
  total: number
  unit: string
}

function BonusSummary({ bonuses }: { bonuses: ActiveBonus[] }) {
  const isDesktop = typeof window !== 'undefined' && window.innerWidth > 768
  const [expanded, setExpanded] = useState(isDesktop)

  return (
    <div className="bonus-summary">
      <div
        className="bonus-summary-header"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="section-label">Active Bonuses ({bonuses.length})</span>
        <span className="bonus-toggle">{expanded ? '▾' : '▸'}</span>
      </div>
      {expanded && bonuses.map((b) => (
        <div key={b.unit} className="bonus-row">
          <span className="bonus-value">+{b.total} {b.unit}</span>
        </div>
      ))}
    </div>
  )
}

export function PastLifeStacks({
  character,
  onSetOverride,
}: {
  character: Character
  onSetOverride: (category: string, id: string, value: number) => void
}) {
  const historyStacks = computeHistoryStacks(character.lives)
  const o = character.pastLifeOverrides

  const heroicDefs = PAST_LIFE_DEFS.filter((d) => d.category === 'heroic')
  const racialDefs = PAST_LIFE_DEFS.filter((d) => d.category === 'racial')
  const iconicDefs = PAST_LIFE_DEFS.filter((d) => d.category === 'iconic')
  const epicDefs = PAST_LIFE_DEFS.filter((d) => d.category === 'epic')

  const totalCompleted = character.lives.filter((l) => l.status === 'completed').length

  // Compute active bonuses — aggregate by unit
  const bonusByUnit: Record<string, number> = {}
  for (const def of PAST_LIFE_DEFS) {
    const catOverrides = o[def.category as keyof typeof o] ?? {}
    const fromHistory = Math.min(historyStacks[def.id] ?? 0, def.max)
    const fromOverride = catOverrides[def.id] ?? 0
    const stacks = Math.min(Math.max(fromHistory, fromOverride), def.max)
    if (stacks > 0) {
      bonusByUnit[def.bonusUnit] = (bonusByUnit[def.bonusUnit] ?? 0) + def.bonusPerStack * stacks
    }
  }
  const activeBonuses: ActiveBonus[] = Object.entries(bonusByUnit).map(([unit, total]) => ({ unit, total }))

  return (
    <div className="past-life-stacks">
      <StackSection label="Heroic" defs={heroicDefs} overrides={o.heroic} historyStacks={historyStacks} onSetOverride={(id, v) => onSetOverride('heroic', id, v)} />
      <StackSection label="Racial" defs={racialDefs} overrides={o.racial} historyStacks={historyStacks} onSetOverride={(id, v) => onSetOverride('racial', id, v)} />
      <StackSection label="Iconic" defs={iconicDefs} overrides={o.iconic} historyStacks={historyStacks} onSetOverride={(id, v) => onSetOverride('iconic', id, v)} />
      <StackSection label="Epic" defs={epicDefs} overrides={o.epic} historyStacks={historyStacks} onSetOverride={(id, v) => onSetOverride('epic', id, v)} />
      <div className="stacks-hint">Tap to add · long-press to remove</div>
      <div className="total-past-lives">Total Past Lives: {totalCompleted}</div>
      {activeBonuses.length > 0 && (
        <BonusSummary bonuses={activeBonuses} />
      )}
    </div>
  )
}
