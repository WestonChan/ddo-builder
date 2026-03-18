# DDO Game Files

DDO is installed via CrossOver/Steam at:
```
~/Library/Application Support/CrossOver/Bottles/Steam/drive_c/Program Files (x86)/Steam/steamapps/common/Dungeons and Dragons Online/
```

Configure this path by setting `DDO_PATH` in `.env` (see `.env.example`), or pass `--ddo-path` to the CLI.

## Key `.dat` Files

- `client_gamelogic.dat` (498 MB) — item defs, feat data, enhancement trees, game rules
- `client_local_English.dat` (214 MB) — English text strings, names, descriptions
- `client_general.dat` (438 MB) — UI icons, item icons, feat icons

## Archive Format

The `.dat` files use Turbine's proprietary archive format (shared with LOTRO). Format reverse-engineered from actual DDO game files, with corrections from [DATExplorer](https://github.com/Middle-earth-Revenge/DATExplorer).

### Header (0x100 - 0x1A8)

Bytes 0x000-0x0FF are zero padding. All fields little-endian uint32.

| Offset | Field | Notes |
|--------|-------|-------|
| 0x140 | BT magic | Always `0x5442` ("BT" -- B-tree marker) |
| 0x144 | Version | `0x200` (gamelogic), `0x400` (english/general). Confirmed NOT block_size (actual block_size=2460 at 0x1A4). DATExplorer label "block_size" is wrong for DDO. |
| 0x148 | File size | Exact match to actual file size on disk |
| 0x14C | File version | DATExplorer field; purpose unclear in DDO |
| 0x154 | First free block | Free block list head. Previously misidentified as "B-tree offset". |
| 0x158 | Last free block | Free block list tail |
| 0x15C | Free block count | Number of free blocks |
| 0x160 | Root offset | **B-tree root directory node**. Previously misidentified as "free list offset". |
| 0x1A0 | File count | Number of file entries in the archive (empirically verified) |
| 0x1A4 | Block size | Always `2460` across all observed files (empirically verified) |

Use `ddo-data parse <file>` to view all header fields. Use `header_dump()` in code to see raw uint32 values for the full 0x140-0x1A4 range.

### Data Blocks

Every content block in the archive uses this wrapper:

```
[8 zero bytes] [content...]
```

The content layout depends on the archive version:

**Version 0x400** (English, general): content starts with the file ID and a type field. `size` includes this 8-byte prefix.

```
00 00 00 00 00 00 00 00  <file_id_le32> <type_le32> <actual_data...>
```

**Version 0x200** (gamelogic): content starts directly after the block header -- no embedded file ID. `size` is the content size.

```
00 00 00 00 00 00 00 00  <actual_data...>
```

The format is auto-detected by checking if the uint32 at +8 matches the entry's file ID.

### Compression

Some entries are stored compressed. Compressed entries have `disk_size < size + 8`.

**Format** (from DATUnpacker's `Subfile.cs`):
```
[uint32 LE decompressed_length] [zlib compressed data...]
```

Decompression:
1. Read first 4 bytes as LE uint32 = expected decompressed length
2. Pass remaining bytes to zlib.decompress()
3. Verify output length matches expected

Falls back to raw deflate (wbits=-15, no zlib header) if standard zlib fails.

Compression type is per-entry (stored in the file type field per DATExplorer):
- 0 = uncompressed
- 1 = maximum compression
- 2 = unknown
- 3 = default compression

### File Table (Flat Pages)

Used by the brute-force scanner. Stored in pages scattered throughout the archive. The first page always starts at offset `0x5F0`.

**Page structure:**

```
[8 zero bytes]                    block header
[uint32 count] [uint32 flags]     page header
[32-byte entry] * N               file entries
```

Known page flags: `0x00030000`, `0x00040000`, `0x00060000`, `0x00080000`, `0x000A0000`, `0x000E0000`.

**32-byte file table entry (flat page layout):**

| Bytes | Type | Field |
|-------|------|-------|
| 0-3 | uint32 | file_id -- unique identifier |
| 4-7 | uint32 | data_offset -- absolute offset to data block |
| 8-11 | uint32 | size -- data size (includes 8-byte id+type prefix) |
| 12-15 | uint32 | (varies -- timestamp or hash) |
| 16-19 | uint32 | (varies) |
| 20-23 | uint32 | disk_size -- on-disk block size (= size + 8 when uncompressed) |
| 24-27 | uint32 | reserved (always 0) |
| 28-31 | uint32 | flags |

### B-tree Directory

The archive also stores file entries in a B-tree directory structure rooted at the header's `root_offset` (0x160). This is the "proper" way to enumerate files.

**B-tree node structure:**

```
[8 zero bytes]                              block header
[62 x (uint32 size, uint32 child_offset)]   directory block (496 bytes)
[61 x 32-byte file entries]                 file block (1952 bytes)
```

Total node payload: 2456 bytes (close to the 2460 block_size).

- Sentinel values: `0x00000000` or `0xCDCDCDCD` for unused child/entry slots
- Traversal: recursive depth-first through child offsets

**32-byte file entry in B-tree nodes (DATExplorer layout):**

| Bytes | Type | Field | Notes |
|-------|------|-------|-------|
| 0-3 | uint32 | unknown1 | 95%+ are 0x00000000; non-zero entries use sequential small integers (0x1E, 0x1F, 0x20 …). Likely a per-entry generation/update counter. |
| 4-7 | uint32 | file_type | Low byte = compression type (0=none, 2=zlib). High 3 bytes = content type code (e.g. 0x001D0002 = type 29, compressed). |
| 8-11 | uint32 | file_id | Unique identifier; high byte = namespace. |
| 12-15 | uint32 | data_offset | Absolute offset to data block in the archive file. |
| 16-19 | uint32 | size | Uncompressed content size (excludes 8-byte block header). |
| 20-23 | uint32 | timestamp | **NOT Unix timestamps.** Most values are < 30,000 (would be 1970-Jan dates). Likely DDO-internal patch/generation sequence numbers or content CRCs. |
| 24-27 | uint32 | unknown2 | Small integers (0–65535). Distribution varies per archive. May be page-local sequence IDs or checksums. |
| 28-31 | uint32 | disk_size | On-disk block size (= size+8 when uncompressed). Multi-block entries have disk_size > 2460 (block_size). **61,738 of 490K gamelogic entries span multiple blocks** (12.6%). |

Note: The field ordering differs between flat pages and B-tree nodes. Both formats have been validated independently.

### File IDs

File IDs encode the entity namespace in their high byte. The B-tree in `client_gamelogic.dat` contains 490,001 entries across the following namespaces (confirmed via `dat-identify`):

| High byte | Count | Entity type |
|-----------|-------|-------------|
| `0x79` | 201,272 | **Item definitions** — dup-triple encoded property sets |
| `0x70` | 201,105 | **Effect/enchantment definitions** — 28-byte binary format (see below) |
| `0x07` | 34,884 | **Game objects** — quests, NPCs, behavior scripts, trigger logic |
| `0x47` | 24,008 | **Spells / active abilities** — DID=0x028B, many cross-archive refs |
| `0x0C` | 20,943 | **Physics/particle/animation data** — exotic DIDs, no cross-refs, float-filled bodies |
| `0x78` | 1,078 | **NPC stat definitions** — dup-triple format with 0x10XXXXXX property keys |
| `0x10` | 435 | Definition references |
| Others | ~2,100 | Scattered; rare high bytes |

Note: The brute-force file-table scanner (`scan_file_table`) finds only ~2,270 entries — roughly 0.5% of the B-tree total. Always use `traverse_btree` for comprehensive enumeration.

**Shared 24-bit namespace:** The lower 24 bits of a file ID are consistent across archives. For example, `0x79004567` in `client_gamelogic.dat` shares its lower 3 bytes with `0x25004567` in `client_local_English.dat` (the matching localization string) and `0x07004567` in the game-object namespace.

Archive ownership by high byte:
- `0x01XXXXXX` — `client_general.dat` (textures, models)
- `0x07XXXXXX`, `0x10XXXXXX`, `0x47XXXXXX`, `0x70XXXXXX`, `0x78XXXXXX`, `0x79XXXXXX`, `0x0CXXXXXX` — `client_gamelogic.dat`
- `0x0AXXXXXX`, `0x25XXXXXX` — `client_local_English.dat`

### Content Types

| Source file | Content types found |
|-------------|-------------------|
| `client_local_English.dat` | OGG Vorbis audio (voiceovers), UTF-16LE text strings |
| `client_general.dat` | 3D mesh data (vertex/index buffers), DDS textures |
| `client_gamelogic.dat` | Binary tagged format, game rules data |

### Gamelogic Entry Format

Entries in `client_gamelogic.dat` use a serialized property set format. The entry header and property encoding were reverse-engineered from DDO game data, informed by LOTRO community tools (LotroCompanion/lotro-tools, lulrai/bot-client).

**Entry header** (all entry types):
```
[DID:u32] [ref_count:u8] [ref_count x file_id:u32] [body...]
```
- `DID` = Data definition ID (entry type/class). Three types cover 94.7% of entries.
- `ref_count` + `file_ids` = cross-reference list (0x07XXXXXX gamelogic file IDs)

**Entry type distribution** (from B-tree scan of 490,001 entries):

The DID (Data Definition ID) is the first 4 bytes of each entry. The B-tree entity namespaces map onto DIDs as follows (confirmed by probing samples from each high-byte namespace):

| Namespace | DID | Primary entity type |
|-----------|-----|---------------------|
| `0x79XXXXXX` | 0x02 or custom | Item definitions (dup-triple format) |
| `0x70XXXXXX` | 0x02 | Effect/enchantment definitions (28-byte binary) |
| `0x07XXXXXX` | 0x01 | Game objects: quests, NPCs, behavior scripts |
| `0x47XXXXXX` | 0x028B | Spells and active abilities |
| `0x0CXXXXXX` | varies | Physics/particle/animation — float-filled bodies, no refs |
| `0x78XXXXXX` | 0x01450000 | NPC stat definitions — dup-triple format like 0x79 items |

DID=1 entries total 6,876 across the B-tree (99% in `0x07XXXXXX`).

Note: The old table ("57% type-0x02, 31% type-0x04, 6% type-0x01") came from the brute-force scanner and represents only ~0.5% of actual content — do not use those percentages as representative.

#### Type 0x04 entries (decoded, 99.7% parse rate)

```
[DID:u32=4] [ref_count:u8] [file_ids:u32[]] [pad:u32=0] [flag:u8] [prop_count:u8] [properties...]
```

Each property is `[key:u32][value:u32]`. When `value > 0`, it is an array count followed by `value` uint32 elements:

```
Simple:  [key:u32] [value:u32=0]
Array:   [key:u32] [count:u32] [elem:u32 x count]
```

Property keys are typically definition references (0x10XXXXXX) or small integers. Array elements have high bytes from `{0x05, 0x20, 0x2A, 0x39, 0x40, 0x47, 0x70}`, representing cross-references to various namespaces.

Use `ddo-data dat-probe <file> --id <hex>` to decode type-4 entries.

#### Effect entries — 0x70XXXXXX namespace (variable-size binary templates)

201,105 entries. Each `0x79XXXXXX` item entry holds one or more effect_ref properties pointing to `0x70XXXXXX` effect entries via any of several effect_ref keys (see property key table below).

Effect entries have DID=0x02 but do **not** use the standard type-2 property stream. They use a fixed binary layout determined by the `entry_type` field. The `entry_type` is the u32 at bytes [5..8], which varies across the 0x70XXXXXX namespace.

**Byte range notation:** all ranges are inclusive (e.g. `5.. 8` = bytes 5, 6, 7, 8 = 4 bytes).

**Common header (all effect entry types):**
```
Byte  0.. 3: DID = 0x00000002
Byte  4    : ref_count = 0x00
Byte  5.. 8: u32 = entry_type  (determines overall size and layout)
Byte  9..12: u32 = flag
```

**entry_type=17 (0x11) — 28 bytes, no magnitude field:**
```
Byte  5.. 8: entry_type = 0x00000011
Byte  9..12: flag = 0x00000001
Byte 13..14: u16 = bonus_type (0x0100 = 256 = Enhancement bonus)
Byte 15    : 0x00
Byte 16..17: u16 = stat_def_id  <- only variable field
Byte 18..23: 0x00 * 6
Byte 24..25: u16 = stat_def_id  (duplicated)
Byte 26..27: 0x00 * 2
```
All 14,452+ entries with stat_def_id=1254 use this type and are byte-identical (no magnitude). Magnitude likely fixed per stat_def definition, or always 1 (stacking unit).

**entry_type=26 (0x1A) — 37 bytes:**
```
Byte  5.. 8: entry_type = 0x0000001A
Byte  9..12: flag = 0x00000001
Byte 13..14: u16 = bonus_type (0x0100)
Byte 15    : 0x00
Byte 16..17: u16 = stat_def_id
Byte 18..19: u16 = 0x0001
Byte 20..23: u32 = 0x083F9C42  (observed constant)
Byte 24    : 0x01
Byte 25..27: 0x00 * 3
Byte 28..29: u16 = stat_def_id  (duplicated)
Byte 30..33: u32 = 0xFFFFFFFF
Byte 34..36: 0x00 * 3
```
Entry_type=26 is used by multiple stat groups: stat_def_id=1207 (2,038 effects), stat_def_id=1450 (232 effects), and others. Within each stat_def_id group, all entries with the same stat_def_id are **byte-identical** — a single per-stat template shared across all FIDs with that stat. These appear to be "secondary augment marker" entries that accompany primary entry_type=53 effects. Magnitude is NOT stored here — these are type markers, not bonus quantifiers.

**entry_type=53 (0x35) — 84 bytes, magnitude at offset 68:**
```
Byte  5.. 8: entry_type = 0x00000035
Byte  9..12: flag = 0x00000001
Byte 13..14: u16 = bonus_type (0x0100)
Byte 15    : 0x00
Byte 16..17: u16 = stat_def_id
Byte 18..27: (variable/structured data)
Byte 28..29: u16 = stat_def_id  (duplicated)
Byte 30..47: 0xFF * 18 (sentinel block)
Byte 48..51: u32 = 0x00000001
Byte 52..67: (variable structured data, IDs/refs)
Byte 68..71: u32 = MAGNITUDE  <- enchantment bonus value (e.g. 11 for "+11")
Byte 72..75: u32 = cap_value  (e.g. 99, 63)
Byte 76..83: (additional flags/counts)
```
Confirmed: effect entries for "Yellow Slot - Diamond of Haggle +11" (stat_def_id=376) have byte 68 = 0x0B = **11**. Multiple FIDs can be byte-identical copies of the same full specification (stat+type+magnitude). Items share effect entries rather than encoding the bonus per-item.

**entry_type=175 (0xAF) — 186 bytes, magnitude-table format:**
```
Byte  0.. 3: DID = 0x00000002
Byte  4    : ref_count = 0x00
Byte  5.. 8: entry_type = 0x000000AF
Byte  9..12: flag = 0x00000003
Byte 13..14: u16 = bonus_type = 0x0000
Byte 15    : 0x00
Byte 16..17: u16 = stat_def_id = 0x0000 (no stat)
Byte 18..63: structured parameter block
Byte 64..  : 16-element u16 table — consecutive pairs (n, n, n+1, n+1, ...) starting
             at entry-specific base n. Entry 0x7000000B starts n=1; 0x7000000E starts n=2.
             Likely encodes the bonus magnitude table for multi-tier augments.
```
Confirmed on Haggle Diamond companion effect 0x7000000E (stat_def_id=0, flag=3). The magnitude table differs by exactly 1 between sibling entries — these are the "augment tier" scaling tables used alongside entry_type=53 (which stores the specific magnitude).

**stat_def_id is a property class identifier**, not necessarily a specific stat name alone. Known values:

| stat_def_id | Hex | Observed on |
|-------------|-----|-------------|
| 1254 | 0x04E6 | 14,452+ item refs; skill augments (Listen, Intimidate, Balance), Heroism enchantments |
| 1251 | 0x04E3 | 4,575+ item refs; skill augments (Tumble, Disable Device), PRR-related items |
| 1941 | 0x0795 | Named item "Zarigan's Arcane Enlightenment: Spell Points" |
| 1572 | 0x0624 | Named item "Saving Throws vs Traps" |
| 450  | 0x01C2 | Named item "+6 Magical Resistance Rating" |
| 376  | 0x0178 | Haggle augments; entry_type=53 with magnitude at byte 68 |
| 1207 | 0x04B7 | Yellow Slot Diamond of Haggle +11; entry_type=26 |

**Enchantment magnitude encoding:** The numeric bonus (e.g., "+11") IS stored in the effect entry at entry_type-specific offsets. For entry_type=53, it is at byte offset 68. For entry_type=17, there is no magnitude field (either always 1, or defined by the stat spec). The parent item entry does NOT need to re-encode the magnitude.

**Multiple effect_ref keys** — items reference effect entries through several property keys, not just 0x10000919:

| Key | Frequency | Notes |
|-----|-----------|-------|
| 0x10000919 | 16,168 total (236 named) | Primary effect_ref (confirmed); in DISCOVERED_KEYS |
| 0x10001390 | ~185 named items | Secondary effect_ref, often paired with 0x10000919; in DISCOVERED_KEYS |
| 0x100012AC | ~49 named items | Tertiary effect_ref slot; in DISCOVERED_KEYS |
| 0x100012BC | ~14 named items | Quaternary effect_ref slot; in DISCOVERED_KEYS |
| 0x100011CB | augment items | Simple augment crystal ref; not yet in DISCOVERED_KEYS |
| 0x1000085B | augment items | Simple augment crystal ref; not yet in DISCOVERED_KEYS |
| 0x100023E6 | augment items | Simple augment crystal ref; not yet in DISCOVERED_KEYS |
| 0x1000149C | augment items | Simple augment crystal ref (2 values per key); not yet in DISCOVERED_KEYS |
| 0x100012F0 | 4 named items | Rare; not yet in DISCOVERED_KEYS |
| 0x100012E8 | 3 named items | Rare; not yet in DISCOVERED_KEYS |

To decode: use `ddo-data dat-dump --id 0x70XXXXXX` to hex-inspect a specific effect entry.

**Known dup-triple property keys** (all `0x10XXXXXX`; defined in `DISCOVERED_KEYS` in `namemap.py`):

| Key | Name | Confidence | Evidence |
|-----|------|------------|---------|
| 0x1000361A | level | high | 4,715 entries; range 1–30; quest/encounter level |
| 0x10000E29 | rarity | high | 6,401 entries; values 2–5 (Common→Epic) |
| 0x10003D24 | durability | medium | 3,898 entries; range 1–169; matches DDO item types |
| 0x10001BA1 | equipment_slot | medium | 8,345 entries; range 2–17; slot codes |
| 0x10001C59 | item_category | medium | 13,217 entries; range 1–12; item type enum |
| 0x100012A2 | effect_value | medium | 4,988 entries; range 1–100; numeric magnitude |
| 0x10000919 | effect_ref | high | Primary 0x70XXXXXX effect ref slot |
| 0x10001390 | effect_ref_2 | high | Secondary effect ref (185 named items) |
| 0x100012AC | effect_ref_3 | medium | Tertiary effect ref (49 named items) |
| 0x100012BC | effect_ref_4 | medium | Quaternary effect ref (14 named items) |
| 0x10001C5D | minimum_level | high | Confirmed: stored directly (e.g. ML=31 for Black Opal Bracers) |
| 0x10006392 | effect_ref_compound | medium | Effect ref in rc=19 compound entries |
| 0x10000882 | unknown_compound_0882 | low | Most common key in rc=19 compound entries (83%); purpose unknown |
| 0x100008AC | is_unique_or_deconstructable | low | Binary flag (0/1); rare val=1 on ring deconstruction items |
| 0x10001C5B | item_subtype | low | Small enum 1–6 (plus 16, 20); near min_level cluster |
| 0x10001C5F | stat_def_id_item | low | Medium int 369–1574; overlaps stat_def_id range of effect entries |
| 0x10001C58 | item_schema_ref | low | All values 0x10XXXXXX refs; adjacent to min_level cluster |

#### Type 0x02 entries (three decoding strategies)

Type-2 entries have several sub-populations, decoded by three strategies in order:

**Simple variant** (~785/1304, 60%): identical to type-4 format except `pad=1`:
```
[DID:u32=2] [ref_count:u8] [file_ids:u32[]] [pad:u32=1] [flag:u8] [prop_count:u8] [properties...]
```
Properties use the same `[key:u32][value:u32]` greedy encoding as type-4 (where non-zero value < 256 is an array count). Parses exactly with 0 bytes remaining.

**Complex variant** (~519/1304, 40%): body starts with a `tsize` (skip byte + VLE) giving a property count, followed by property data. Three decoding strategies are tried:

1. **complex-pairs**: greedy `[key:u32][value:u32]` pairs consume the body exactly.
2. **complex-typed**: VLE-encoded property stream where each property is `[key:VLE][type_tag:VLE][value:typed]`. Accepted when coverage > 50% and at least one property decodes. Type tags follow the Turbine engine format (see below).
3. **complex-partial**: pattern detection fallback — identifies definition refs, ASCII strings, floats, and file ID cross-references within the body.

**Turbine property stream type tags** (from LOTRO community research, applied to DDO):

| Tag | Type | Value encoding |
|-----|------|---------------|
| 0 | int | u32 LE |
| 1 | float | f32 LE |
| 2 | bool | u32 LE (0 or 1) |
| 3 | string | VLE length + Latin-1 bytes |
| 4 | array | VLE element_count + VLE element_type + elements |
| 5 | struct | tsize + recursive property stream (max depth 3) |
| 6 | int64 | 8 bytes LE |
| 7 | double | 8 bytes LE |

Unknown type tags cause the decoder to stop and return a partial result.

DDO lacks the property definition registry (DID 0x34000000 in LOTRO) that maps property IDs to types. The complex-typed decoder infers types from the stream's embedded type tags rather than a registry lookup.

Use `ddo-data dat-probe <file> --id <hex>` to decode type-2 entries.

#### Type 0x01 entries (behavior/trigger scripts)

6,876 entries in the B-tree (vs. 137 via brute-force scanner). Located almost entirely in the `0x07XXXXXX` game-object namespace.

**Structure:** No fixed ref-count header section (refs=0 in all observed entries). Body starts immediately after the 5-byte header (`[DID:u32=1][ref_count:u8=0]`).

**Size distribution:**
- 11 bytes (body = `01 00 00 00 00 00`): ~3,996 entries (58%) — null/stub behavior nodes
- 68–600 bytes: NPC AI scripts, quest triggers, trap logic
- 1,000–5,000 bytes: complex behavioral sequences with multiple actions

**Binary patterns in body:**
- `0x01` type byte at start, followed by a count/type byte
- `0x10XXXXXX` definition references (property keys / schema pointers)
- `0x70XXXXXX` effect file references
- IEEE 754 floats (1.0f = `00 00 80 3F` very common — likely speed/scale/probability)
- Length-prefixed ASCII strings: `[u8 length][text bytes]` — contain human-readable script descriptions (e.g., "Set up particle fx, and make the crate disappear after some time.")

**Named entity examples** (via localization cross-reference):
- Quests: "The Rising Light" (496 B), "Lava Caves: Time is Money" (68 B)
- NPCs: "Duergar Laborer[E]" (599 B), "Ax Cultist[E]" (150 B)
- Spell powers / stats: "Corrosion" (416 B), "Glaciation" (427 B)
- Enhancement entries: "Bard Virtuoso II" (11 B stub), "Slaver Quality Dexterity" (4,873 B)
- Item stubs: "Thorn Blade" (11 B), augment crystals (11 B) — actual item data in `0x79XXXXXX`

The 11-byte item stubs are cross-reference nodes: the same lower-24-bit ID appears in both `0x07XXXXXX` (stub DID=1) and `0x79XXXXXX` (full dup-triple item definition). The game engine resolves the item name via the 0x07 stub's localization link.

Uses the same Turbine property stream format as complex type-2, but without a registry to map property IDs to types.

#### Spell entries — 0x47XXXXXX namespace

24,008 entries. DID=0x0000028B (decimal 651) in all observed cases. Each entry has 10–41 file ID refs in the header, pointing to cross-archive assets.

Named examples: "Repair Serious Damage", "Knock", "Mounting up!", "Soulweaver/Splendid Cacophony". Names resolve via the shared 24-bit namespace with `client_local_English.dat`.

**Body is 0–2 bytes** — essentially empty. The entire spell definition is packed into the ref list in the header. Ref pattern observed across all probed entries:

```
[0x01470000]        -- spell template pointer (client_general.dat)
[0xNN000000]        -- spell type/school indicator
[0x001F0000]        -- constant (purpose unknown)
[small_int pairs...]-- parameter data as 0x00XXXXXX refs
```

Ref slot semantics confirmed across 152 named spells:
- **Slot 0**: `0x01470000`–`0x0147XXXX` — spell template in `client_general.dat`
- **Slot 1**: `0xNN000000` — spell variant/type identifier. High byte only carries information (low 3 bytes always 0). **NOT a school code** — distribution is near-uniform across 256 values (~94 spells per code), and the same named spell ("Shield") has 4 consecutive codes (0xCE–0xD1) for its 4 class variants. This is an internal spell-class/variant ID; actual school is probably in the `client_general.dat` template referenced by Slot 0.
- **Slot 2**: `0x001FXXXX` — first parameter block indicator
- **Slots 3+**: packed binary spell parameters — small integers (spell level, component IDs, power values, stat_def_ids matching those in effect entries). These are NOT file ID refs despite the 4-byte format. Values 946 (0x3B2), 947 (0x3B3), 950 (0x3B6) appear frequently and match stat_def_ids found in non-0x10 dup-pairs.

The 0x0A (localization) string refs in spell entries resolve to school/category names (confirmed via `oa_ref_strings` distribution). Small integers in slots 3+ can exceed 32 bits logically — treat the entire ref list as a packed binary parameter block, not as a list of file IDs.

#### Item entries — 0x79XXXXXX namespace (dup-triple format)

201,272 entries in three structural variants distinguished by `ref_count` (byte[4]):

**ref_count=0 (145,383 entries)** — standard item definitions:
```
[DID:u32] [ref_count:u8=0] [preamble:u16] [dup-triple property stream...]
```
Property stream preamble at bytes[5..6]. Most common preamble = `0x0010` (68K entries). The 2-byte preamble is a schema version code, NOT a category discriminator — feats, items, augments, and NPCs all share the same preamble values. The property stream uses dup-triples: `[key:u32][key:u32][val:u32]` where the key is a `0x10XXXXXX` property ID repeated twice. Non-0x10 records (key < `0x10000000`) also appear: key=stat_def_id, value=float32 or a `0x10XXXXXX` type reference.

**ref_count=19 (37,971 entries)** — compound entries with spell and effect refs:
```
[DID:u32] [ref_count:u8=19] [19 × file_id:u32] [preamble:u16=0x3264] [dup-triple stream...]
```
Ref list pattern (per-entry):
- refs[0]: `0x00001000` (null/schema indicator)
- refs[1..2]: `0x476XXXXX` — spell template refs in `client_general.dat`
- refs[3]: `0x70XXXXXX` — effect ref (FID mirrors parent item's low 3 bytes)
- refs[4..7]: `0x07XXXXXX` — localization refs
- refs[8..18]: mixed `0x01XXXXXX`, `0x06XXXXXX`, `0x13XXXXXX`, and others
Preamble always `0x3264`. Total entry size ~2.3 KB. Most common dup-triple key: `0x10000882` (83% of these entries). These appear to be feats/enhancements/compound abilities with associated spells and effect definitions.

**ref_count=46 (14,213 entries)** — large compound entries:
```
[DID:u32] [ref_count:u8=46] [46 × file_id:u32] [preamble:u16=0x6CD2] [dup-triple stream...]
```
Ref list contains 14 null refs, 14 `0x10XXXXXX` property-meta refs, and 2 each of multiple other namespaces (`0x3A`, `0x9E`, etc.). Preamble always `0x6CD2`. Total entry size ~3.7 KB. These are the most complex item-type entries; examples include "Vestments of Ravenloft" and various augment diamonds.

**0x10XXXXXX namespace (435 entries)** — property key declarations, NOT file content. These exist in the B-tree for schema lookup but their `data_offset` and `size` fields contain internal cross-reference values (not valid block offsets). Reading them as archive content always fails with "Missing block header."

#### VLE (Variable-Length Encoding)

The Turbine engine uses VLE for integer encoding in property streams (from LOTRO community tools):
- Byte < 0x80: value is the byte itself (0-127)
- Byte == 0xE0: followed by a full uint32 LE
- Byte has 0xC0 set: 4-byte value from 3 more bytes
- Otherwise (0x80 set, 0x40 clear): 2-byte value

DDO uses VLE in complex type-2 entry bodies (confirmed: tsize at body start gives valid property counts). Simple type-2 and type-4 entries use plain uint32 key-value pairs.

#### TLV hypotheses (failed)

Three TLV encoding hypotheses were tested via `dat-validate`:
- Hypothesis A (prop_id:u32, type_tag:u8, value): 3.6% parse rate, 0 cross-refs
- Hypothesis B (prop_id:u32, length:u32, value): 0% parse rate
- Hypothesis C (type_tag:u8, prop_id:u32, value): 0% parse rate

All failed because the format is not flat TLV -- it uses definition references as keys, arrays with counts, and nested structures rather than sequential tagged properties.

**Analysis tooling** (in `dat_parser/`):
- `probe.py` -- data-driven format probe: entry header parsing, pattern detection, type-4 and type-2 decoders, VLE property stream decoder
- `identify.py` -- entity category inventory: B-tree traversal + localization cross-reference, high-byte namespace distribution, name prefix analysis
- `survey.py` -- statistical survey: type code histogram, size distribution, string density
- `tagged.py` -- legacy TLV scanner (superseded by probe.py for structured decoding)
- `validate.py` -- cross-archive TLV hypothesis validation harness
- `constants.py` -- shared constants (file ID high bytes, archive labels)
- `compare.py` -- byte-by-byte comparison of same-type entries

Use `ddo-data dat-probe`, `ddo-data dat-survey`, `ddo-data dat-dump --id <hex>`, and `ddo-data dat-compare-entries --type <hex>` for exploration.

### Open Questions

- Multi-block files (entries where data may span multiple blocks) — quantified (61,738 of 490K gamelogic entries, 12.6%) but reading not yet implemented
- Exact purpose of `unknown2` and `timestamp` in B-tree entries (unknown1 = generation counter; timestamp = NOT Unix, likely patch sequence; unknown2 = small per-archive integer)
- Property type system for complex type-0x02/0x01 entries (LOTRO uses a registry at DID 0x34000000; DDO lacks it)
- Meaning of remaining 0x10XXXXXX keys (~200+ remain unmapped beyond 10 keys in DISCOVERED_KEYS)
- Spell school source: slot 1 is a variant/type ID (NOT school code); actual school must come from the `client_general.dat` template (slot 0 ref)
- Compound entry structure (ref_count=19, ref_count=46 groups): purpose of the large ref lists and keys 0x10000882, 0x10006392

**Resolved:**
- 0x144 field: confirmed NOT block_size. Values 0x200 (gamelogic) / 0x400 (english, general) are version codes.
- minimum_level: stored directly as key 0x10001C5D in dup-triple items (not computed at runtime)
- 0x47XXXXXX body: empty (0-2 bytes); entire definition in header ref list
- 0x0CXXXXXX: physics/particle/animation data — float-filled bodies, exotic DIDs
- 0x78XXXXXX: NPC stat definitions using dup-triple format with 0x10XXXXXX keys
- 0x70XXXXXX effect entry layout: variable-size, determined by entry_type at bytes[5..8]. Magnitude stored at type-specific offset (byte 68 for entry_type=53/0x35). entry_type=26 (37B): all copies identical, stat_def_id=1207, flag=1 — secondary augment marker. entry_type=175 (186B): stat_def_id=0, flag=3, contains 16-element magnitude-table starting at byte 64.
- Enchantment magnitude encoding: for entry_type=53 (0x35) effects, the u32 at byte 68 IS the bonus value. Multiple effect FIDs can be byte-identical copies sharing the same stat+type+magnitude specification.
- Non-0x10 dup-pairs: a second class of property records with key=stat_def_id (< 0x10000000), value=float32 or reference. Key repeated twice like standard dup-triples. Confirmed in feat/spell entries (keys 946, 947, 950 with float values).
- Multiple effect_ref keys: 10+ distinct keys all store 0x70XXXXXX values; different item types use different slots.
- 0x10XXXXXX FIDs in B-tree: these are property key declarations, NOT readable file content. Their B-tree metadata (data_offset, size) contains internal cross-references, not a valid block offset. Reading 0x10XXXXXX as archive content will always fail with "Missing block header."
- Non-0x10 dup-pair key=686 (0x2AE) value=0x10000B22: 0x10000B22 is a "property meta-key" reference, not a file content entry. It functions as a type/bonus-category identifier used in augment gem entries.
- 0x79XXXXXX preamble semantics: the 2-byte preamble at `prop_start = 5 + ref_count * 4` is a schema version code (81 distinct values). NOT a category discriminator — all item types appear under preamble 0x0010 (most common, 68K entries). Separate from ref_count: entries with ref_count=0 have preamble at bytes[5..6]; ref_count=19 entries have preamble at bytes[81..82] = always 0x3264; ref_count=46 entries have preamble at bytes[189..190] = always 0x6CD2.

## Implementation Status

### Archive parsing
- [x] Header parsing (all fields 0x140-0x1A4)
- [x] Brute-force file table scanner (flat page detection)
- [x] B-tree directory traversal (depth-first from root_offset)
- [x] Decompression (zlib with length prefix + raw deflate fallback)
- [x] File extraction with magic-byte type detection (OGG, DDS, XML, WAV, BMP)
- [ ] Multi-block file support (entries spanning multiple data blocks)

### Gamelogic entry format
- [x] Statistical survey (type code histogram, size distribution, string density)
- [x] TLV hypothesis probing (3 encoding hypotheses -- all failed, superseded by probe)
- [x] Entry comparison (constant/bounded/variable field detection)
- [x] UTF-16LE string detection and file ID cross-reference detection
- [x] Cross-archive TLV validation harness (`dat-validate` command)
- [x] UTF-16LE string table loader (`client_local_English.dat`)
- [x] Entry header decoder (DID + ref_count + file_ids -- all entry types)
- [x] Data-driven format probe (VLE primitives, pattern detection)
- [x] Type 0x04 entry decoder (99.7% parse rate, simple + array properties)
- [x] Type 0x02 entry decoder (simple + complex-pairs + complex-typed via VLE property stream; complex-partial pattern detection fallback)
- [ ] Type 0x01 entry decoder (behavior scripts — structure characterized, full decoder not yet built)
- [x] 0x70XXXXXX effect entry layout (variable-size by entry_type; stat_def_id at data[16..17]; magnitude at byte 68 for entry_type=53; 7 stat_def_ids partially mapped)
- [ ] 0x70XXXXXX stat_def_id lookup table (7 values identified; full mapping requires cross-referencing general.dat stat definitions)
- [x] 0x47XXXXXX spell entry format (body empty; definition packed in header ref list; slot 0=template ref, slot 1=spell variant/type ID NOT school code, slots 2+=packed params)
- [x] Property key census (`dat-registry` command -- empirical statistics)
- [x] Property ID name mapping (17 keys in DISCOVERED_KEYS; 10+ effect_ref key variants identified; cluster 0x10001C5B–0x10001C60 partially characterized)
  - **Naming convention:** keys with confirmed meaning use descriptive names (`minimum_level`, `effect_ref`). Keys that are observed but not yet understood use `unknown_<context>_<hex4>` (e.g. `unknown_compound_0882`). Do not use speculative descriptive names for unconfirmed fields.
- [x] Non-0x10 dup-pair records (stat_def_id keys with float/ref values; confirmed in feat/spell entries)
- [x] 0x79 dup-triple entry decoder (item definitions with [key][key][value] encoding)
- [x] Structured localization entry decoder (0x25XXXXXX with VLE string lengths, sub-entry refs)
- [ ] Nested/recursive property sets

### Game data extraction
- [x] Items parser (0x79 dup-triple decoding, enum resolution, wiki merge)
- [ ] Feats parser
- [ ] Enhancements parser
- [ ] Classes parser
- [ ] Races parser
- [ ] Augments parser (slotted gems/crystals and typed augment slots)
- [ ] Spells parser (spell lists per class, spell levels)
- [ ] Set bonuses parser (named item sets with piece-count thresholds)
- [ ] Epic destinies parser
- [ ] Filigrees parser (sentient weapon augments)
- [ ] Past lives parser (heroic, racial, iconic, epic reincarnation bonuses)
- [ ] Reaper enhancements parser
- [x] JSON export pipeline (`ddo-data extract` command -- items)

### Asset extraction
- [x] DDS texture extraction from client_general.dat
- [x] DDS to PNG conversion (Pillow)
- [x] Icon pipeline (`ddo-data icons` command)

### Supplementary data
- [x] DDO Wiki scraper — items (`ddo-data scrape --type items`)
- [x] DDO Wiki scraper — feats (`ddo-data scrape --type feats`)
- [x] DDO Wiki scraper — enhancements (`ddo-data scrape --type enhancements`)
- [ ] DDO Wiki scraper — quests
- [ ] DDO Wiki scraper — augments, spells, set bonuses, epic destinies
- [x] Data merging (game files + wiki data -- items via `_merge_wiki_data`)

### CLI
- [x] `parse`, `list`, `dat-extract`, `dat-peek`, `dat-stats`
- [x] `dat-dump`, `dat-compare`, `dat-survey`, `dat-compare-entries`, `dat-validate`, `dat-probe`, `dat-registry`
- [x] `extract` (JSON export -- items with `--wiki-items` merge)
- [x] `icons` (DDS to PNG)
- [x] `dat-namemap` (property key name mapping via wiki cross-reference)
- [x] `dat-identify` (entity category inventory via B-tree + localization cross-reference)
- [x] `scrape` (wiki items, feats, enhancements)

## Credits

See [README.md](../README.md#credits) for the full list of references and acknowledgments.

Our implementation was independently reverse-engineered from actual DDO game files, with corrections from community LOTRO/DDO tools.
