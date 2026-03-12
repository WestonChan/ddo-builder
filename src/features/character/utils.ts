import type { Life } from './types'

export function formatClassSummary(life: Life): string {
  return life.classes
    .map((c) => {
      const name = c.classId.charAt(0).toUpperCase() + c.classId.slice(1)
      return `${c.levels} ${name}`
    })
    .join(' / ')
}

export function formatRace(race: string): string {
  return race.charAt(0).toUpperCase() + race.slice(1)
}

export function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1)
}

/** Count past life stacks from completed lives in the history */
export function computeHistoryStacks(lives: Life[]): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const life of lives) {
    if (life.status !== 'completed' || !life.reincarnation) continue
    const r = life.reincarnation
    if (r.type === 'epic') {
      const key = r.epicSphere ?? ''
      counts[key] = (counts[key] ?? 0) + 1
    } else if (r.type === 'heroic') {
      for (const c of life.classes) {
        counts[c.classId] = (counts[c.classId] ?? 0) + 1
      }
    } else if (r.type === 'racial') {
      counts[life.race] = (counts[life.race] ?? 0) + 1
    } else if (r.type === 'iconic') {
      counts[life.race] = (counts[life.race] ?? 0) + 1
    }
  }
  return counts
}
