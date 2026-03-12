import type { Character, Life } from '../types'

// --- Stub data ---
// Each reincarnation is its own life entry. Epic TRs duplicate the build.
// True TRs (heroic/racial/iconic) are followed by a new build.

const STUB_LIVES: Life[] = [
  // Life 1 build: Human Fighter — did 2 epic TRs then heroic TR
  {
    id: '1a',
    name: '',
    race: 'human',
    classes: [{ classId: 'fighter', levels: 20 }],
    feats: [],
    enhancements: [],
    status: 'completed',
    reincarnation: { type: 'epic', epicSphere: 'martial', completedAt: '2025-01-10' },
  },
  {
    id: '1b',
    name: '',
    race: 'human',
    classes: [{ classId: 'fighter', levels: 20 }],
    feats: [],
    enhancements: [],
    status: 'completed',
    reincarnation: { type: 'epic', epicSphere: 'arcane', completedAt: '2025-01-12' },
  },
  {
    id: '1c',
    name: '',
    race: 'human',
    classes: [{ classId: 'fighter', levels: 20 }],
    feats: [],
    enhancements: [],
    status: 'completed',
    reincarnation: { type: 'heroic', completedAt: '2025-01-15' },
  },
  // Life 2 build: Elf Ranger — did 1 epic TR then racial TR
  {
    id: '2a',
    name: '',
    race: 'elf',
    classes: [{ classId: 'ranger', levels: 20 }],
    feats: [],
    enhancements: [],
    status: 'completed',
    reincarnation: { type: 'epic', epicSphere: 'divine', completedAt: '2025-06-18' },
  },
  {
    id: '2b',
    name: '',
    race: 'elf',
    classes: [{ classId: 'ranger', levels: 20 }],
    feats: [],
    enhancements: [],
    status: 'completed',
    reincarnation: { type: 'racial', completedAt: '2025-06-20' },
  },
  // Life 3 build: Human Paladin/Rogue — did 1 epic TR, still current
  {
    id: '3a',
    name: '',
    race: 'human',
    classes: [
      { classId: 'paladin', levels: 18 },
      { classId: 'rogue', levels: 2 },
    ],
    feats: [],
    enhancements: [],
    status: 'completed',
    reincarnation: { type: 'epic', epicSphere: 'martial', completedAt: '2025-08-01' },
  },
  {
    id: '3b',
    name: '',
    race: 'human',
    classes: [
      { classId: 'paladin', levels: 18 },
      { classId: 'rogue', levels: 2 },
    ],
    feats: [],
    enhancements: [],
    status: 'current',
  },
  // Planned lives
  {
    id: '4',
    name: '',
    race: 'dwarf',
    classes: [{ classId: 'barbarian', levels: 20 }],
    feats: [],
    enhancements: [],
    status: 'planned',
  },
  {
    id: '5',
    name: '',
    race: 'halfling',
    classes: [{ classId: 'rogue', levels: 20 }],
    feats: [],
    enhancements: [],
    status: 'planned',
  },
]

export const STUB_CHARACTERS: Character[] = [
  {
    id: 'char-1',
    name: 'Thordak',
    server: 'Thrane',
    lives: STUB_LIVES,
    currentLifeIndex: 6,
    pastLifeOverrides: {
      heroic: { paladin: 2, fighter: 3, rogue: 1 },
      racial: { human: 2, elf: 1 },
      iconic: {},
      epic: { martial: 2 },
    },
    createdAt: '2025-01-01',
    updatedAt: '2025-12-01',
  },
  {
    id: 'char-2',
    name: 'Aelindra',
    server: 'Moonsea',
    lives: [
      {
        id: '10',
        name: 'Life 1',
        race: 'elf',
        classes: [{ classId: 'wizard', levels: 20 }],
        feats: [],
        enhancements: [],
        status: 'current',
      },
    ],
    currentLifeIndex: 0,
    pastLifeOverrides: { heroic: {}, racial: {}, iconic: {}, epic: {} },
    createdAt: '2025-03-01',
    updatedAt: '2025-11-15',
  },
]
