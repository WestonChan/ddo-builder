export interface Race {
  id: string
  name: string
  statModifiers: Record<string, number>
}

export interface CharacterClass {
  id: string
  name: string
  hitDie: number
}

export interface Feat {
  id: string
  name: string
  description: string
  prerequisites: string[]
}

export interface Enhancement {
  id: string
  name: string
  treeName: string
  tier: number
  cost: number
  description: string
}

export interface CharacterBuild {
  name: string
  race: string
  classes: { classId: string; levels: number }[]
  feats: string[]
  enhancements: string[]
}
