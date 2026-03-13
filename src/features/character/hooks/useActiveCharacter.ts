import { STUB_CHARACTERS, STUB_PLANNED_BUILDS } from '../data/stubCharacters'
import type { Character, Life, PastLifeCounts } from '../types'
import {
  computeLifeNumbers,
  getCurrentLifeNumber,
  EMPTY_UNTRACKED,
  updateCategoryMap,
} from '../utils'
import { useLocalStorage } from '../../../hooks'

export interface Selection {
  characterId: string
  lifeId: string
  plannedBuildId: string | null
}

const defaultStub = STUB_CHARACTERS[0]
const defaultSelection: Selection = {
  characterId: defaultStub.id,
  lifeId: defaultStub.lives[defaultStub.currentLifeIndex]?.id ?? '',
  plannedBuildId: null,
}

/** Migrate old localStorage shape: pastLifeOverrides → untrackedLives */
function migrateCharacters(chars: Character[]): Character[] {
  return chars.map((c) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const raw = c as any
    if (!c.untrackedLives && raw.pastLifeOverrides) {
      return { ...c, untrackedLives: raw.pastLifeOverrides }
    }
    if (!c.untrackedLives) {
      return { ...c, untrackedLives: EMPTY_UNTRACKED }
    }
    return c
  })
}

/** Shared hook for reading the active character, selection, and planned builds from localStorage. */
export function useActiveCharacter() {
  const [characters, setCharacters] = useLocalStorage<Character[]>(
    'ddo-characters',
    STUB_CHARACTERS,
    migrateCharacters,
  )
  const [selection, setSelection] = useLocalStorage<Selection>('ddo-selection', defaultSelection)
  const [plannedBuilds, setPlannedBuilds] = useLocalStorage<Life[]>(
    'ddo-plannedBuilds',
    STUB_PLANNED_BUILDS,
  )

  const character = characters.find((c) => c.id === selection.characterId) ?? characters[0]
  const currentLife = character.lives[character.currentLifeIndex]
  const lifeNumbers = computeLifeNumbers(character)
  const lifeNumber = getCurrentLifeNumber(character)

  const viewingPlannedBuild = selection.plannedBuildId
    ? plannedBuilds.find((b) => b.id === selection.plannedBuildId)
    : undefined

  function selectCharacter(charId: string) {
    const char = characters.find((c) => c.id === charId)
    if (!char) return
    setSelection({
      characterId: charId,
      lifeId: char.lives[char.currentLifeIndex]?.id ?? '',
      plannedBuildId: null,
    })
  }

  function selectPlannedBuild(buildId: string) {
    setSelection((prev) => ({ ...prev, lifeId: '', plannedBuildId: buildId }))
  }

  function selectLife(lifeId: string) {
    setSelection((prev) => ({ ...prev, lifeId, plannedBuildId: null }))
  }

  function setOverride(category: keyof PastLifeCounts, id: string, value: number) {
    setCharacters((prev) =>
      prev.map((c) => {
        if (c.id !== selection.characterId) return c
        const untracked = { ...c.untrackedLives }
        return {
          ...c,
          untrackedLives: {
            ...untracked,
            [category]: updateCategoryMap(untracked[category], id, value),
          },
        }
      }),
    )
  }

  function setBuildDesired(category: keyof PastLifeCounts, id: string, value: number) {
    if (!selection.plannedBuildId) return
    const buildId = selection.plannedBuildId
    setPlannedBuilds((prev) =>
      prev.map((b) => {
        if (b.id !== buildId) return b
        const desired: PastLifeCounts = b.desiredPastLives ?? EMPTY_UNTRACKED
        return {
          ...b,
          desiredPastLives: {
            ...desired,
            [category]: updateCategoryMap(desired[category], id, value),
          },
        }
      }),
    )
  }

  return {
    characters,
    setCharacters,
    character,
    currentLife,
    lifeNumbers,
    lifeNumber,
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
  }
}
