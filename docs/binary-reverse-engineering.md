# Binary Reverse Engineering Findings

Comprehensive results from probing all opaque data in DDO `.dat` archives.

## Summary Table

| Target | Result | Value |
|--------|--------|-------|
| Type-167 effects (45K) | Dead end | Behavior script templates, all 37K copies identical |
| Spell school encoding | Dead end | Template codes = delivery mechanism, not school |
| 0x0A localization (3.2K) | Dead end | Ogg Vorbis audio files, not text |
| Float property keys (190) | Productive | Duration, cooldown, tier multipliers identified |
| Effect types 59/173/503 | Dead end | All identical system templates, no per-instance data |
| client_general.dat 0x01 | Dead end | 4.2 MB entry is world/scene data; stat refs were false positives |
| client_general.dat 0x02 | Dead end | Visual/material data only, zero stat refs |
| 0x07 game objects (35K) | Decoded | 3 DID types: spells(16K), abilities(11K), quests(7K) |

## Type-167 Effect Entries (0x70XXXXXX)

**45,094 entries. Header is boilerplate, but TAIL contains structured sub-effect data.**

Entry type marker at offset 5: `0xA7` (167). First ~0xB0 bytes are identical across
all entries (engine boilerplate / effect system constants). The variable data starts
at byte 0xB0 and encodes a list of sub-effects.

### Header structure (bytes 0-0xAF, mostly fixed)

- Bytes 0-4: `02 00 00 00 00` (DID=2, flag=0)
- Bytes 5-8: `A7 00 00 00` (entry_type=167)
- Bytes 9-22: fixed pattern
- **Bytes 23-24: sub-type discriminator (varies!)**
  - `99 04` (0x0499 = 1177): 44,541 entries (98.8%)
  - `E8 01` (0x01E8 = 488): 464 entries (1.0%)
  - `D4 09` (0x09D4 = 2516): 66 entries (0.1%)
- Bytes 25+: fixed pattern through 0xAF

### Tail structure (bytes 0xB0+, variable)

Byte 0xB1 appears to be a **sub-effect count**:

| Entry size | Count | Byte 0xB1 | Sub-effects | Notes |
|------------|-------|-----------|-------------|-------|
| 178 bytes | 464 | 0x00 | 0 (empty) | Tail = `00 00` |
| 198 bytes | 66 | 0x01 | 1 | 22-byte tail |
| 320 bytes | 4,785 | ~0x02 | 2 | |
| 720 bytes | 37,013 | 0x05 | 5 | Majority (82%) |
| 728-816 | ~2,400 | 0x05-0x06 | 5-6 | Extended variants |

Each sub-effect block contains repeating patterns like `12 00 00 00 63 00 00 00`
which may be stat_def_id + magnitude pairs or similar structured data.

Associated with: enhancement tree effects, augment operations, dragonmark abilities,
item enchantments ("Focused", "Counterattack", "Strong Defense").

### Key finding: ALL 720-byte entries are completely identical

Deeper analysis confirmed that ALL 37,013 entries at 720 bytes share the exact
same tail content — every u16/u32 field has exactly 1 unique value across all
entries. The "5 sub-effects" are always the same sub-effects. These are
**behavior script templates**, not per-entry data.

The tail at 0xB0+ contains:
- Bytes 0xB0-0xB1: `01 05` (count=5 sub-effects, always)
- Bytes 0xB2-0x106: 5 fixed sub-effect blocks with values like `0x12` (18) and
  `0x63` (99) — engine execution parameters, not stat identifiers
- Bytes 0x107+: dup-pair property key registry (`0x10XXXXXX` values repeated
  in pairs) — lists which property keys the engine writes when applying the effect

The actual stat identity and magnitude for a given item come from the SIBLING
type-17 (stat classifier) and type-53 (magnitude) effect entries referenced by
the same parent 0x79 item. Type-167 is only the execution template.

**Verdict: Dead end for stat extraction.** Type-167 cannot distinguish between
"Enhancement bonus to Strength +6" and "Enhancement bonus to Dexterity +6" — both
reference the exact same type-167 entry.

## Other Undecoded Effect Types (0x70XXXXXX)

## Spell School Encoding (0x0147XXXX Templates)

**166 unique template codes. They do NOT encode spell school.**

- Same template code appears across multiple schools (e.g., 0x0147005A spans
  Abjuration, Enchantment, and Evocation)
- Only 9/166 template refs exist as entries in either archive
- 3 found in `client_general.dat` are 218-byte transform matrices (0x02 namespace)
- 3 found in `client_gamelogic.dat` are 11-byte item stubs (0x07 namespace)
- Template codes likely encode **delivery mechanism** (AoE shape, targeting, range)

**Implication:** Spell school must come from wiki data or an undiscovered encoding.

## Other Undecoded Effect Types (0x70XXXXXX)

The type-167 probe revealed the full effect type distribution:

| Type | Count | Status |
|------|-------|--------|
| 17 (0x11) | 88,866 | Decoded (mechanism classifier) |
| 167 (0xA7) | 45,094 | Partially decoded (container with sub-effects) |
| 53 (0x35) | 33,943 | Decoded (primary bonus entry) |
| 26 (0x1A) | 2,373 | Decoded (augment marker) |
| 59 (0x3B) | 1,811 | **Unknown** |
| 173 (0xAD) | 1,545 | **Unknown** |
| 503 (0x1F7) | 417 | **Unknown** |
| 175 (0xAF) | varies | Decoded (multi-tier augment table) |

Types 59, 173, and 503 were probed and found to be **identical template entries**:

- Type 59: 1,811 entries, ALL 70 bytes, ALL identical. stat_def_id=0. System templates.
- Type 173: 1,545 entries, ALL 184 bytes, ALL identical. stat_def_id=0. System templates.
- Type 503: 417 entries, ALL 514 bytes, ALL identical. stat_def_id=0. System templates.

None contain per-instance stat or bonus data. Dead end.

## 0x0A Namespace (client_local_English.dat)

**3,194 entries. All are Ogg Vorbis audio files.**

- Magic header: `OggS` + `vorbis` codec
- Fixed size: 4,088 or 4,096 bytes each
- Likely NPC voice lines, UI sounds, or environmental audio
- Not localization text at all

**Other namespaces in English archive:** 138,797 total entries spanning 0x00-0xFF.
The 0x25 namespace (132,783 entries) dominates. All other namespaces have 1-591
entries each -- likely miscellaneous assets (config, UI resources).

## Float-Valued Property Keys (0x79XXXXXX Entries)

**190 keys with >50% IEEE 754 float values identified out of 2,796 total keys.**

### High-Confidence Mappings

| Key | Values | Context | Interpretation |
|-----|--------|---------|----------------|
| `0x10000907` | -1, 20, 60, 900, 36000 | 99% feats | **Duration (seconds)**: -1=permanent, 20=20s, etc. |
| `0x10000B7A` | mostly 15.0 | 65% items | **Cooldown (seconds)**: 15s is standard DDO cooldown |
| `0x10001B29` | always 30.0 | 100% feats | **Feat cooldown**: 30 seconds |
| `0x10000B60` | 1, 2, 3, -1, 1.5, 2.5 | 97% items | **Effect tier/rank multiplier** |
| `0x10000B5C` | mostly +1/-1 | 63% items | **Sign multiplier** (buff vs debuff) |
| `0x10000742` | 1-999, mean 31.5 | 86% items | **Internal level** (encounter/object level) |
| `0x100024ED` | mostly 1.0, some 1.5, 0.5 | 41,848 entries | **Effect scaling multiplier** |
| `0x10000867` | always 0.25 | 90% feats | **Difficulty tier: quarter** |
| `0x10000868` | always 0.50 | 71% feats | **Difficulty tier: half** |
| `0x10000869` | always 0.75 | 71% feats | **Difficulty tier: three-quarter** |
| `0x10003B6B` | always 6.0 | death effects | **Death effect cooldown: 6 seconds** |
| `0x100048D4` | always 300.0 | death effects | **Death effect duration: 300 seconds** |

### Mount Properties (100% mount items)

| Key | Values | Interpretation |
|-----|--------|----------------|
| `0x10009C18` | always 30.0 | Mount base speed |
| `0x10009CC7` | 30 or 60 | Mount acceleration |
| `0x10009CC9` | always 120 | Fast mount max speed |
| `0x10009CCA` | always 60 | Mount turn speed |

### Coefficient Cluster (0x100007B6-0x100007F8)

Eight closely-spaced keys (0x7B6, 0x7BC, 0x7C1, 0x7C5, 0x7CC, 0x7CD, 0x7CE, 0x7E2,
0x7F0, 0x7F5, 0x7F8) all with values predominantly 1.0 and occasional fractional values
(0.35, 0.75, 0.5). These are **effect system coefficient slots** used by the engine
to scale damage/healing/duration. They appear on both items and feats.

### Pseudo-Float File References (~8.0 values)

Several keys show values clustered around 8.0 (e.g., 8.0003, 8.1795, 8.2360):

- `0x1000000E` (8,177 entries), `0x100008FC` (8,260), `0x10001D36` (4,124),
  `0x1000242D` (6,691), `0x10001A50` (1,272), `0x10005174` (2,769)

These are NOT floats. IEEE 754 value 8.0 = `0x41000000`. Values near 8.0 correspond
to raw u32 values in the `0x41XXXXXX` range -- these are **file ID references** to the
0x41 namespace in `client_general.dat` (which has 64 entries in the English archive).
They should be read as u32 pointers, not float magnitudes.

### Constant Sentinels

| Key | Value | Meaning |
|-----|-------|---------|
| `0x1000048E` | 0.0555 (64%) | Preamble marker (appears alongside structured data) |
| `0x10001A51` | 0.0555 (100%) | Same sentinel in different context |
| `0x10004E98` | 0.0555 (100%) | Same sentinel |
| `0x10000E7C` | 1.0 (100%) | Boolean flag (effect enabled) |
| `0x10001036` | 1.0 (100%) | Boolean flag |
| `0x10001D5A` | 1.0 (100%) | Boolean flag |
| `0x1000204B` | 1.0 (100%) | Boolean flag |
| `0x100012CC` | 208.3 (67%) | Fixed constant -- purpose unknown |
| `0x10001B2D` | -106024.0 (100%) | Large negative constant -- possibly sentinel |
| `0x100042E5` | 114.0 (100%) | Green Steel specific constant |

## Bonus Type Code and Stat Census

### Type-53 Entries (31,886 total)

- **Only 1 bonus_type_code value** at byte 18: `0x0004` (all entries). The
  previously mapped `0x0100 = "Enhancement"` may be at a different offset.
- Dominated by stat_def_id=376 (Haggle): 31,729 of 31,886 entries
- 4 rare stat_def_ids: 2011 (134), 1423 (17), 1588 (3), 1391 (1)
- **Verdict:** Type-53 is NOT where diverse stat bonuses live. Most item bonus
  diversity comes through type-17 entries (560 unique stat_def_ids) where the
  stat_def_id is a mechanism classifier, not a per-stat identifier.

### Type-17 Top Stat Classifiers

| stat_def_id | Count | Known Name |
|-------------|-------|-----------|
| 1254 | 31,750 | (mechanism classifier) |
| 1440 | 12,350 | (mechanism classifier) |
| 551 | 11,333 | (mechanism classifier) |
| 2114 | 8,266 | (mechanism classifier) |
| 1941 | 1,936 | Spell Points |
| 450 | 183 | Magical Resistance Rating |

## client_general.dat Non-Icon Namespaces

### 0x01 Namespace (577 entries)

- Entry 0x01000000: **4.2 MB mega-entry** -- deep probe revealed it's a world/scene
  definition, NOT a stat lookup table. Sparse structure (24 non-zero regions in 4 MB
  of mostly zeros) containing 3,652 effect refs, 2,053 item refs, 2,840 string refs.
  Only 6 dup-triples, all with sentinel value 0xFFFFFFFF. The earlier "908 stat refs"
  were u16 false positives.
- Remaining 576 entries: DID=0x000040F0 or 0x0000C0D0, ref_count=240 or 112
- Heavily float-filled (identity matrices, transformation data)
- All entries are **3D model/scene definitions**, not game mechanic data. Dead end.

### 0x02 Namespace (489 entries)

- Sizes vary 218 bytes to 26 KB
- 116 entries at 218 bytes are minimal matrices (9x 1.0f floats)
- Larger entries are complex scene/material definitions
- **Zero stat_def_id references** -- purely visual/geometric data
- Dead end for game mechanic extraction.

## 0x07 Game Objects (34,884 entries)

Streaming probe completed successfully. Three distinct types based on DID:

### DID=2: Spell/Ability Definitions (16,532 entries)

Body avg 1,377 bytes. Named examples: "Sound Burst", "Melf's Acid Arrow",
"Feeblemind", "Resist Energy: Sonic".

**Property census:** 816 unique 0x10XXXXXX keys, 25,026 total dup-triple hits.
Additionally, **221 non-0x10 stat_def_id keys** (small integers) found as
dup-pairs with float values — same format as 0x47 spell entries.

Key spell-script-specific properties:
- `0x10000FB0`: 1,621 hits, binary flag (missile absorption)
- `0x10000A17`: 1,276 hits, 889 unique values — likely spell template ID
- `0x1000ADA0`: 1,231 hits, 4 values — spell category enum
- `0x10006CDA`: 354 hits, floats [1.0, 1.16, 1.33, 1.5, 2.0, 2.5] — scaling
- 19 consecutive keys `0x10006CCD-0x10006CE1` on weapon proficiency entries

Non-0x10 stat keys encode spell-specific mechanics: key=1 (16K hits),
key=16256 ("Slow"/"Burdened"), key=16000 ("Barbarian Rage"), key=256 (stat
damage), key=1826 ("Ghoul", float 4.0), key=531 ("Mind Fog", float 0.65).

### DID=4: Simple Ability/Feat Definitions (11,250 entries)

Body avg 25 bytes. Named: "Dispel Example One", "Swim", "Disable Device",
"Remove Fear", "Scare". Small entries with 0-1 header refs to other 0x07
entries. Likely passive ability definitions and feat mechanics.

### DID=1: Quest/Dungeon Scripts (6,838 entries)

Mostly small entries: 6,269 at 0 KB (behavior script stubs), 265 at 1 KB,
121 at 2 KB. A few large entries at 28-138 KB contain complex quest logic.

**Text probe result:** Quest text is NOT embedded in DID=1 bodies directly.
The text visible in earlier probes comes from the 0x25 localization system —
DID=1 entries reference 0x25 entries for their display text. The bodies
contain binary behavior scripts (triggers, conditions, state machines).

One anomalous 328 MB mega-entry (0x07FD1000) contains a resource path table
(`entity/character/npcs/quest/...` paths) — a game asset manifest, not quest
data.

**For quest data extraction:** use the 0x25 localization system (tooltip +
description sub-entries) keyed by quest object IDs, not DID=1 bodies.

### Other DIDs

80 unique DIDs total, but most have 1-29 entries with specialized DIDs
(0x7001780B for boss encounters like "Arraetrikos", 0x79XXXXXX DIDs for
item-linked behaviors). Refs are mostly self-referential: 35,379 of 36K+
header refs point to other 0x07 entries.
