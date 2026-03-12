/** Definition of a single past life feat for the stacks UI */
export interface PastLifeDef {
  id: string
  name: string
  category: 'heroic' | 'racial' | 'iconic' | 'epic'
  max: number
  bonusPerStack: number
  bonusUnit: string
  bonus: string // display text on stack row
}

/**
 * Stub past life definitions — will be replaced by data from
 * public/data/past-life-feats.json once the data pipeline produces it.
 */
export const PAST_LIFE_DEFS: PastLifeDef[] = [
  // Heroic — keyed by classId
  { id: 'paladin', name: 'Paladin', category: 'heroic', max: 3, bonusPerStack: 1, bonusUnit: 'hit/dmg vs evil', bonus: '+1 hit/dmg vs evil per stack' },
  { id: 'fighter', name: 'Fighter', category: 'heroic', max: 3, bonusPerStack: 10, bonusUnit: 'HP', bonus: '+10 HP per stack' },
  { id: 'rogue', name: 'Rogue', category: 'heroic', max: 3, bonusPerStack: 1, bonusUnit: 'Reflex save', bonus: '+1 Reflex save per stack' },
  { id: 'wizard', name: 'Wizard', category: 'heroic', max: 3, bonusPerStack: 1, bonusUnit: 'spell penetration', bonus: '+1 spell penetration per stack' },
  // Racial — keyed by raceId
  { id: 'human', name: 'Human', category: 'racial', max: 3, bonusPerStack: 1, bonusUnit: 'ability point', bonus: '+1 ability point per stack' },
  { id: 'elf', name: 'Elf', category: 'racial', max: 3, bonusPerStack: 1, bonusUnit: 'dex skills', bonus: '+1 dex skills per stack' },
  // Iconic
  { id: 'morninglord', name: 'Morninglord', category: 'iconic', max: 3, bonusPerStack: 1, bonusUnit: 'Turn Undead', bonus: '+1 Turn Undead per stack' },
  { id: 'bladeforged', name: 'Bladeforged', category: 'iconic', max: 3, bonusPerStack: 1, bonusUnit: 'Reconstruct', bonus: '+1 Reconstruct per stack' },
  // Epic — keyed by sphere
  { id: 'martial', name: 'Martial', category: 'epic', max: 3, bonusPerStack: 1, bonusUnit: 'physical ability', bonus: '+1 physical ability per stack' },
  { id: 'arcane', name: 'Arcane', category: 'epic', max: 3, bonusPerStack: 1, bonusUnit: 'spell ability', bonus: '+1 spell ability per stack' },
  { id: 'divine', name: 'Divine', category: 'epic', max: 3, bonusPerStack: 1, bonusUnit: 'spell ability', bonus: '+1 spell ability per stack' },
  { id: 'primal', name: 'Primal', category: 'epic', max: 3, bonusPerStack: 1, bonusUnit: 'physical ability', bonus: '+1 physical ability per stack' },
]
