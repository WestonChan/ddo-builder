# DDO Game Files

DDO is installed via CrossOver/Steam at:
```
~/Library/Application Support/CrossOver/Bottles/Steam/drive_c/Program Files (x86)/Steam/steamapps/common/Dungeons and Dragons Online/
```

Configure this path by setting `DDO_PATH` in `.env` (see `.env.example`), or pass `--ddo-path` to the CLI.

## Key `.dat` Files

- `client_gamelogic.dat` (504 MB) -- item defs, feat data, enhancement trees, game rules
- `client_local_English.dat` (214 MB) -- English text strings, names, descriptions, audio
- `client_general.dat` (438 MB) -- UI/item/feat icons; also 577 entries in 0x01 namespace and 489 in 0x02 (stat definition tables? spell school lookups?)

### Other `.dat` Files (not useful for build planning)

- `client_surface.dat` (3.4 GB) -- terrain/environment textures
- `client_sound.dat` (4.1 GB) -- music, sound effects
- `client_highres.dat` (4.1 GB) -- high-resolution textures
- `client_mesh.dat` (2.3 GB) -- 3D models
- `client_anim.dat` (415 MB) -- character/NPC animations
- `client_cell_1-4.dat` (760 MB) -- zone/dungeon geometry
- `client_map_1-4.dat` (88 MB) -- map images
- `client_local_DE.dat` (94 MB) -- German localization
- `client_local_FR.dat` (94 MB) -- French localization

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
| 551  | 0x0227 | **Framework classifier** — appears on "Tempest Rune of Exceptional Strength" augments AND "Passive: +15 Competence Bonus to the Spot skill." effect packages simultaneously; confirms entry_type=17 stat_def_ids are NOT unique per-stat identifiers |

**Probe investigation finding (2026-03-18):** An exhaustive reverse-mapping search across all `0x79XXXXXX` entries confirmed that stat_def_ids 1254, 1251, 1440, 551, and 2114 each appear on items from wildly different stat categories (ability scores, skills, resistances, etc.). The `bonus_type_code` field is also unhelpful — every `entry_type=17` effect has `bonus_type_code=0x0000`. The actual stat identity (e.g. "this is a Strength bonus") is NOT encoded in the `entry_type=17` effect entry itself. It must come from a separate mechanism not yet decoded — possibly entry_type=167 effects, a stat-definition lookup table in a different archive, or a property on the parent item entry.

**Enchantment magnitude encoding:** The numeric bonus (e.g., "+11") IS stored in the effect entry at entry_type-specific offsets. For entry_type=53, it is at byte offset 68. For entry_type=17, there is no magnitude field (either always 1, or defined by the stat spec). The parent item entry does NOT need to re-encode the magnitude.

**Multiple effect_ref keys** — items reference effect entries through several property keys, not just 0x10000919:

| Key | Frequency | Notes |
|-----|-----------|-------|
| 0x10000919 | 16,168 total (236 named) | Primary effect_ref (confirmed); in DISCOVERED_KEYS |
| 0x10001390 | ~185 named items | Secondary effect_ref, often paired with 0x10000919; in DISCOVERED_KEYS |
| 0x100012AC | ~49 named items | Tertiary effect_ref slot; in DISCOVERED_KEYS |
| 0x100012BC | ~14 named items | Quaternary effect_ref slot; in DISCOVERED_KEYS |
| 0x100011CB | augment/compound items | effect_ref_5; in DISCOVERED_KEYS |
| 0x1000085B | augment/compound items | effect_ref_6; in DISCOVERED_KEYS |
| 0x100023E6 | augment/compound items | effect_ref_7; in DISCOVERED_KEYS |
| 0x1000149C | augment/compound items | effect_ref_8 (2 values per key); in DISCOVERED_KEYS |
| 0x100012F0 | 4 named items | effect_ref_9; rare; in DISCOVERED_KEYS |
| 0x100012E8 | 3 named items | effect_ref_10; rare; in DISCOVERED_KEYS |

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
| 0x100011CB | effect_ref_5 | medium | 0x70XXXXXX refs; co-occurs with effect_ref_6/7/8 on compound items |
| 0x1000085B | effect_ref_6 | medium | 0x70XXXXXX refs; always paired with effect_ref_5 group |
| 0x100023E6 | effect_ref_7 | medium | 0x70XXXXXX refs; always paired with effect_ref_5 group |
| 0x1000149C | effect_ref_8 | medium | 0x70XXXXXX refs; some items have 2 values |
| 0x100012F0 | effect_ref_9 | medium | 0x70XXXXXX refs; 4 items |
| 0x100012E8 | effect_ref_10 | medium | 0x70XXXXXX refs; 3 items |
| 0x10001C5E | unknown_cluster_1C5E | low | Values are 0x10XXXXXX key refs; most common=0x10000909 (68x) |
| 0x10001C60 | unknown_cluster_1C60 | low | Packed 4B; bytes[2..3] echo item_category key ID (0x1C59) |
| 0x10000909 | unknown_constant_0909 | low | All 139 items share value 0x09190100; schema-type identifier node |
| 0x10001347 | unknown_constant_1347 | low | 97 items, always 0x39611300; likely CRC constant; paired with 0x10001348 |
| 0x10001348 | unknown_constant_1348 | low | 97 items, always 0xAB82A800; always paired with 0x10001347 |
| 0x10000E39 | unknown_item_class_E39 | low | Enum 0/1/8; val=1 and val=8 on trainer/unique items (all cat=-1) |
| 0x10000B32 | unknown_item_flags_B32 | low | Enum 0/18/22/32; mostly 0; rare non-zero on Shield, Deconstruction items |
| 0x100008B4 | unknown_rank_8B4 | low | Small int max=45; many values appear ×3 (DDO enhancement tiers?) |
| 0x10004281 | unknown_pool_flag_4281 | low | Binary 0/4; val=4 on cat=12 items, val=0 on cat=2 |
| 0x100023F5 | unknown_signed_modifier_23F5 | low | Signed int −10 to +34; negative values on items like Armor, Sapphire of Vertigo |
| 0x10000A48 | unknown_group_ref_A48 | low | 155 items; large values (loot group IDs?); always paired with 0x10000DE2 |
| 0x10000DE2 | unknown_template_ref_DE2 | low | 151 items; 5 distinct values; paired with 0x10000A48 |
| 0x10002DD9 | unknown_flag_or_float_2DD9 | low | Binary: 0 (144x) or 0x40000000=float 2.0 (1x, Scale: Sonic Spell Crit Damage) |
| 0x10000901 | unknown_override_ref_0901 | low | Mostly 0; non-zero → 0x10XXXXXX key ref (optional property override?) |
| 0x10000B2E | unknown_content_ref_B2E | low | 138 items; 17 distinct; all cat=-1 |
| 0x10000002 | unknown_format_sig_0002 | low | 127 items; packed large values; all cat=-1; very low key ID → fundamental schema marker |
| 0x1000048E | unknown_constant_pair_048E | low | 2 constants: 0x3D632E00 (91x), 0x60951300 (36x); adjacent to 0x1000048D |
| 0x1000048D | unknown_constant_048D | low | Always 0xA4487500; same magic constant as 0x10005175 and 0x100018AA |
| 0x100018AA | unknown_constant_18AA | low | Mostly 0xA4487500; all cat=-1 |
| 0x10005175 | unknown_constant_5175 | low | Always 0xA4487500; all cat=-1 |
| 0x10000917 | unknown_flag_0917 | low | 99 items; val=2 only on 'Bottled Rainstorm' (1 item) |
| 0x10002877 | unknown_flag_2877 | low | 83 items; val=0x00800000 only on 'Green Fire' (1 item) |
| 0x1000088E | unknown_bitmask_088E | low | 98 items; all cat=-1; packed bitmask (high u16=0x0004 common) |
| 0x10006F7F | unknown_versioned_ref_6F7F | low | 93 items; low byte always 0x01; content ref with version flag |
| 0x10002899 | unknown_template_ref_2899 | low | 86 items; 6 distinct; low byte 0/1 variant pattern |
| 0x10001399 | damage_dice_notation | medium | 83 items; packed ASCII dice: bytes[1..3]="XdY", byte[0]=bonus |
| 0x10001585 | unknown_rank_1585 | low | 78 items; small int max=46; all cat=-1; similar to unknown_rank_8B4 |
| 0x10000E7C | unknown_float_one_E7C | low | Always 0x3F800000 = IEEE 754 float 1.0; all cat=-1 |
| 0x10002BCE | unknown_float_modifier_2BCE | low | Mostly 0; rarely IEEE floats ≈0.01–0.15 (3 named items) |
| 0x1000283C | unknown_group2_ref_283C | low | 78 items; all cat=-1; 6 distinct values (low byte 0/1) |
| 0x10002840 | unknown_group2_ref_2840 | low | 78 items; all cat=-1; co-occurs with 0x1000283C/0x10002BCE/0x10000E7C |
| 0x10001071 | unknown_chain_head_1071 | low | Always 0x1000A084; head pointer in 78-item property chain |
| 0x10001072 | unknown_chain_count_1072 | low | Always 1; count field in 78-item chain (Wildhunter, Item Restoration group) |
| 0x10001073 | unknown_chain_type_1073 | low | Mostly 18; type/slot-kind field in 78-item chain |
| 0x10001076 | unknown_chain_start_1076 | low | Always 0x10730300; pointer to 0x107XXXXX value sub-chain |
| 0x1000A084 | unknown_chain_node_A084 | low | 6 distinct item refs; data node pointed to by 0x10001071 |
| 0x10710000 | unknown_chain_ptr_7100 | low | Always 0x10711000; 0x107XXXXX linked-chain node |
| 0x10730300 | unknown_chain_next_7303 | low | Always 0x10731000; 0x107XXXXX chain → next node |
| 0x10731000 | unknown_chain_value_7310 | low | Mostly 0x00121000; terminal value in 0x107XXXXX chain |
| 0x10760000 | unknown_chain_terminal_7600 | low | Always 0x03001000; terminal node in 0x107XXXXX chain |
| 0x10711000 | unknown_chain_value_7110 | low | Always 0xA0841000; terminal value in 0x10710000→0x10711000 sub-chain |
| 0x10001349 | unknown_constant_1349 | low | Always 0x78F2A800; third member of the 0x10001347/48/49 constant triple (97 items each) |
| 0x10003102 | unknown_constant_3102 | low | Single constant value; likely schema or type tag |
| 0x10003972 | unknown_constant_3972 | low | Always 0xA4487500 (magic schema-type tag); one of four keys sharing this constant |
| 0x10001A51 | unknown_constant_1A51 | low | Single constant value; likely schema tag |
| 0x10001B8D | effect_ref_shared_1B8D | medium | 73 items all share SAME FID 0x700027E1; may be global baseline effect |
| 0x10001BC4 | effect_ref_11_BC4 | medium | 0x70XXXXXX effect FIDs; part of sequential BC4/BC6/BC7 effect_ref triple |
| 0x10001BC6 | effect_ref_12_BC6 | medium | 0x70XXXXXX effect FIDs; part of sequential BC4/BC6/BC7 effect_ref triple |
| 0x10001BC7 | effect_ref_13_BC7 | medium | 0x70XXXXXX effect FIDs; part of sequential BC4/BC6/BC7 effect_ref triple |
| 0x10000B60 | unknown_float_tier_B60 | low | IEEE 754 float32; values 0.0/1.0/2.0/3.0/4.0/−1.0 → tier/rank multiplier |
| 0x10000B5C | unknown_float_sign_B5C | low | IEEE 754 float32; values ±1.0/0.0 → sign or direction coefficient |
| 0x100007F8 | unknown_float_coeff_7F8 | low | IEEE 754 float32; mostly 1.0; part of 7E2/7F0/7F5/7F8 coefficient group |
| 0x100007F0 | unknown_float_coeff_7F0 | low | IEEE 754 float32; mostly 1.0; part of 7E2/7F0/7F5/7F8 coefficient group |
| 0x100007F5 | unknown_float_coeff_7F5 | low | IEEE 754 float32; mostly 1.0; part of 7E2/7F0/7F5/7F8 coefficient group |
| 0x100007E2 | unknown_float_coeff_7E2 | low | IEEE 754 float32; mostly 1.0; part of 7E2/7F0/7F5/7F8 coefficient group |
| 0x100008FC | unknown_float_approx8_8FC | low | IEEE 754 float32; values ~8.0–8.2; possibly item weight |
| 0x10000742 | unknown_float_level_742 | low | IEEE 754 float32; values 6.0–32.0; possibly float level requirement |
| 0x10BB0000 | unknown_chain_ptr_BB00 | low | Always 0x10BB1000; head of 0x10BB0000→0x10BB1000 pointer sub-chain |
| 0x10BB1000 | unknown_chain_value_BB10 | low | Terminal value node for the 0x10BB chain |
| 0x100010BB | unknown_chain_node_10BB | low | Parallel key to the 0x10BB chain; 0x10-namespace equivalent |
| 0x10000ABC | unknown_ability_flags_ABC | low | Part of ABC/ABD/ABE cluster; bitfield-like or small enum |
| 0x10000ABD | unknown_ability_id_ABD | low | Part of ABC/ABD/ABE cluster; small integer max=126; likely ability/feat index |
| 0x10000ABE | unknown_ability_bits_ABE | low | Part of ABC/ABD/ABE cluster; second flags field |
| 0x10000539 | unknown_triple_param_A_539 | low | Small int max=73; part of co-occurring 539/53B/53D triple (70 items) |
| 0x1000053B | unknown_triple_param_B_53B | low | Small int max=76; part of co-occurring 539/53B/53D triple |
| 0x1000053D | unknown_triple_param_C_53D | low | Small int max=82; part of co-occurring 539/53B/53D triple |
| 0x100007EB | unknown_flag_enum_7EB | low | Small enum with ~6 distinct values |
| 0x10000E87 | unknown_content_ref_E87 | low | Mix of 0x10XXXXXX refs and small ints; possibly content/pack reference |
| 0x100015C3 | unknown_flag_15C3 | low | Binary or small-enum flag |
| 0x1000224E | unknown_count_224E | low | Small integer; count or index field |
| 0x10000E8F | unknown_triple_param_D_E8F | low | Small int max=36; part of E87/E8F/E90 triple (64/67 items overlap with E90) |
| 0x10000E90 | unknown_triple_param_E_E90 | low | Small int max=25; part of E87/E8F/E90 triple |
| 0x10001954 | unknown_zero_constant_1954 | low | 66 items; always 0; schema tag/reserved slot |
| 0x10001A46 | unknown_zero_constant_1A46 | low | 63 items; always 0; schema tag/reserved slot |
| 0x10000B1D | unknown_zero_constant_B1D | low | 62 items; always 0; schema tag/reserved slot |
| 0x100017A0 | unknown_zero_constant_17A0 | low | 62 items; always 0; schema tag/reserved slot |
| 0x1000073D | unknown_float_sparse_73D | low | Float32; mostly 0.0, sparse non-zero 4.0–32.0; optional level/dim parameter |
| 0x10006CDA | unknown_float_coeff_6CDA | low | Float32; mostly 0.0, sparse 1.0/0.5/0.05; multiplier or fractional coefficient |
| 0x10000B7A | unknown_float_B7A | low | Float32; mostly 15.0 (60/63); likely a fixed dimension default |
| 0x100007BC | unknown_float_coeff_7BC | low | Float32; mostly 1.0; extension of the 7E2/7F0/7F5/7F8 coefficient group |
| 0x1000131A | unknown_float_range_A_131A | low | Float32; 40 distinct values 4.0–32.0; adjacent to 131B, likely min/max pair |
| 0x1000131B | unknown_float_range_B_131B | low | Float32; 40 distinct values 4.0–32.0; adjacent to 131A, paired float bound |
| 0x10001A6B | unknown_float_dim_1A6B | low | Float32; 33 distinct values 1.0–19.0; per-item scaling dimension |
| 0x10005176 | unknown_float_approx8_5176 | low | Float32; ~8.0–8.2 cluster; like 0x100008FC; part of 5175/5176/5177 triple |
| 0x10005177 | unknown_float_tiny_5177 | low | Float32; mostly 0x3D632E00 (~0.055); tiny constant; part of 5175/5176/5177 triple |
| 0x10000B22 | unknown_slot_ref_B22 | low | Values are 0x10XXXXXX key IDs (not file IDs); most common: 0x1000085B (effect_ref_6) |
| 0x1000726E | effect_ref_14_726E | medium | Mostly 0, sparse 0x70XXXXXX FIDs; optional effect_ref slot |
| 0x10005405 | effect_ref_15_5405 | medium | Mostly 0, one 0x70XXXXXX FID; very sparse optional effect_ref slot |
| 0x100008A3 | unknown_small_int_8A3 | low | Small int max=35; 67 items; mostly 0; diverse non-zero values |
| 0x100030F5 | unknown_flag_30F5 | low | 3 vals: 0/32/8; 16 items have 32 (bit 5 set) |
| 0x100007E5 | unknown_flag_7E5 | low | Near-binary 0/8; adjacent to 7E2/7F0/7F5/7F8 float cluster |
| 0x10000854 | unknown_small_int_854 | low | Small int max=~37; 62 items; diverse values; similar to 8A3 |
| 0x10002842 | unknown_constant_2842 | low | Always 0x00284300; another magic-constant schema tag |
| 0x10000000 | unknown_preamble_ref_0000 | low | Zero key ID; may be preamble region artifact; packed byte values + occasional 0x10XXXXXX refs |
| 0x1000053A | unknown_seq6_param_B_53A | low | Small int; even sub-set member of 539/53A/53B/53C/53D/53E 6-member sequence |
| 0x1000053C | unknown_seq6_param_D_53C | low | Small int; even sub-set member of 6-member 53X sequence |
| 0x1000053E | unknown_seq6_param_F_53E | low | Small int; even (final) member of 6-member 53X sequence |
| 0x10003973 | unknown_constant_3973 | low | Always 0xE399D700; companion constant to 0x10003972 schema tag |
| 0x10000747 | unknown_small_int_747 | low | Small enum 2–5 (29x:4, 27x:3); adjacent to float_level_742 |
| 0x10001919 | unknown_ref_or_zero_1919 | low | 0 (40x) or 0x100013E6 ref (22x); adjacent to 191A |
| 0x1000191A | unknown_small_int_191A | low | 0 (40x) or 20 (22x); paired with 1919 |
| 0x10001D94 | unknown_constant_1D94 | low | Mostly 0x670E8400 constant; adjacent to 1D95 |
| 0x10001D95 | unknown_float_sparse_1D95 | low | Float32; mostly 0.0, sparse 15.0/30.0/35.0; adjacent to 1D94 |
| 0x1000000F | unknown_preamble_ref_000F | low | Always 0x3D632E00; low key ID — likely preamble artifact; same value as 5177 |
| 0x10000B24 | unknown_float_coeff_B24 | low | Float32; mostly 0.0, sparse ≤1.0 fractional values; adjacent to B22 (slot_ref) |
| 0x10000C3E | unknown_zero_constant_C3E | low | 61 items; always 0; schema tag/reserved |
| 0x10001B0A | unknown_zero_constant_1B0A | low | 60 items; always 0; schema tag/reserved |
| 0x10001A4A | unknown_ref_slot_A_1A4A | low | 60 items (all 3 co-occur); mostly 0 else 0x10XXXXXX refs; part of 1A4A/4B/4C triple |
| 0x10001A4B | unknown_ref_slot_B_1A4B | low | Part of 1A4A/4B/4C triple; 0x10XXXXXX refs |
| 0x10001A4C | unknown_param_C_1A4C | low | Part of 1A4A/4B/4C triple; small ints or packed bytes |
| 0x100029A9 | unknown_packed_id_29A9 | low | Packed 3-byte data with low-byte 0/1 flag |
| 0x1000080F | unknown_packed_data_80F | low | 29 distinct large values; likely packed multi-byte fields |
| 0x10001AED | unknown_ref_or_zero_1AED | low | 0 (39x) or one of two 0x10XXXXXX refs; same pattern as 1919 |
| 0x10002368 | unknown_float_sparse_2368 | low | Float32; mostly 0.0, one item has 60.0 |

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

23,962 entries (46 read errors). **Two DID types** split evenly:

| DID | Count | Avg refs | Avg body | Description |
|-----|-------|----------|----------|-------------|
| 0x028B | 12,116 (50.6%) | 33.4 | 22.4B | Full spell definitions |
| 0x008B | 11,762 (49.1%) | 22.2 | 11.0B | Compact definitions |

15,807 entries have names (resolved via 0x25XXXXXX shared namespace). 2,530 spells appear as multiple class variants. Remaining ~70 entries have miscellaneous DIDs (0x01, 0x02, 0x04, etc.).

**Body size**: 88% have body 0–3 bytes, but a tail extends to 1,832 bytes. Body contains overflow stat data when the ref list is full.

**No 0x0A localization refs** found in any slot (previous claim was incorrect). School is NOT encoded as a string ref.

##### Preamble (slots 0–2)

- **Slot 0**: `0x0147XXXX` — spell mechanic template code (NOT a file ref — zero matches in general.dat). Low 16 bits identify the template (847 unique). Defines the spell's delivery/VFX system. Multiple spells share templates when they use the same mechanic.
- **Slot 1**: `0xNN000000` — class-variant discriminator. High byte only carries information. Near-uniform across 256 values. Same spell has consecutive codes per class (e.g., Shield: 0xCE–0xD1).
- **Slot 2**: `0x001FXXXX` — parameter block indicator. Low 16 bits are a variant index within the template family.

##### Template code meanings (slot 0 low 16 bits)

Template codes classify spells by **mechanical delivery type**. Confirmed mappings (from wiki correlation on 250 spells across 65 templates):

| Template | Delivery type | Target | Range | Confirmed school | Examples |
|----------|--------------|--------|-------|-----------------|----------|
| 0x0000 | Direct damage/touch | mixed | Standard/Touch | mixed | Magic Missile, Burning Hands, Chill Touch |
| 0x0001 | Ranged directed effect | mixed | Standard | mixed | Dispel Magic, Wall of Fire, Heal |
| 0x0003 | Buff/debuff AoE | mixed | Standard AOE | mixed | Remove Fear, Stinking Cloud, Mind Fog |
| 0x0006 | Touch cure/removal | Friend, Self | Standard (100%) | mixed | Remove Curse, Neutralize Poison |
| 0x0007 | Single-target mind | mixed | Standard/AOE | 60% Enchantment | Charm Person, Command, Otto's Dance |
| 0x0008 | Persistent positional AoE | Foe, Positional | Standard AOE (81%) | mixed | Wail of Banshee, Ray of Exhaustion |
| 0x0009 | Cloud/fog ground effect | Foe, Positional, Breakable (100%) | Standard AOE (100%) | 100% Conjuration | Acid Fog, Cloudkill, Incendiary Cloud |
| 0x000A | Personal transmutation | Friend, Self (100%) | Standard | 67% Transmutation | Tumble, Protection from Evil |
| 0x0017 | Personal force shield | Self (100%) | Personal (100%) | 100% Abjuration | Shield (all class variants) |
| 0x0042 | Stat buff | Friend, Self (69%) | Standard | 50% Transmutation | Aid, Bear's Endurance, Bull's Strength |
| 0x0044 | Self concealment | mixed | Standard (67%) | 33% Illusion | Blur, Displacement, Stoneskin |
| 0x0055 | Ranged bolt/ray | Foe, Directional | Double | 75% Conjuration | Black Dragon Bolt, Call Lightning |
| 0x0068 | Touch/close debuff | Foe/mixed | Touch/AOE | 56% Necromancy | Slay Living, Enervation, Haste |
| 0x008C | Mass repair | Friend, Self (100%) | Standard AOE (100%) | 100% Transmutation | Mass Repair (all tiers) |

Coverage: ~22% of wiki-matched spells have a template with consistent range mapping (>=65%); ~15% for target. Generic templates (0x0000, 0x0001) contain diverse spell types and don't resolve to a single targeting mode.

##### Stat 708 — spell effect category

| Value | Pattern | Examples |
|-------|---------|----------|
| 2 | Healing/removal | Remove Paralysis, Neutralize Poison |
| 17 | General damage/effect (mixed schools/levels) | Shout, Flame Strike, Cure Serious |
| 18 | Protection/ward | Restoration, Nightshield, Glyph of Warding |
| 19 | Area blasting | Fireball, Cloudkill, Meteor Swarm |
| 21 | Physical/crowd control | Blade Barrier, Power Word: Stun |
| 22 | Mind-affecting/debuff | Finger of Death, Charm, Inflict Wounds |
| 23 | Buff/utility | Shield of Faith, Prayer, Melf's Acid Arrow |

##### Stat 731 — spell behavior mode

| Value | Pattern | Examples |
|-------|---------|----------|
| 1 | Special/unique behavior | Charm Monster, Focusing Chant |
| 3 | Enhanced combat (higher metamagic eligibility) | Delayed Blast Fireball, Feeblemind |
| 5 | Standard combat spell (default, 75% of spells) | Fireball, Cure Light Wounds |
| 8 | Movement/utility | Teleport, Dimension Door, Water Breathing |
| 10 | Mixed utility | Remove Fear, Spell Resistance |

##### Stat encoding (slots 3+)

Slots 3+ encode **stat_def_id dup-triple pairs** — the same encoding concept as 0x79 item entries, but packed into the ref list. Two formats observed:

**Compact format** (refs 6–10, typically DID 0x028B or 0x008B):
```
[3] 0x00SSSSxx  -- stat_def_id SSSS packed with flag byte xx
[4] 0x00SSSS00  -- stat_def_id SSSS repeated (dup)
[5] 0x0000VV00  -- value VV shifted left 8 bits
[6] 0x00SSSS00  -- next stat_def_id
[7] 0x00SSSS00  -- repeated
[8] 0x0000VV00  -- value
```
Example (Fireball): stat 708=19, stat 731=5

**Extended format** (refs 20+, complex spells):
```
[N]   0x0000SSSS  -- stat_def_id as clean u32
[N+1] 0x0000SSSS  -- stat_def_id repeated
[N+2] value        -- u32 value (may be int, float, or def ref)
```
Example (Shield refs=26): `[708, 708, 17, 731, 731, 5]`

When the ref list is full, stat encoding continues into the body using the same format.

##### Discovered stat_def_ids in spell entries

~90 unique stat_def_ids found. Top by frequency:

| Stat | Hex | Value type | Top values | Meaning |
|------|-----|------------|------------|---------|
| 708 | 0x02C4 | int | 17, 19, 21, 23, 18 | Spell effect category (3,608 entries). See table above. Does NOT map to school. |
| 731 | 0x02DB | int | 5, 1, 8, 3, 10 | Spell behavior mode (3,707 entries). See table above. Not spell level. |
| 943 | 0x03AF | int | 1 (96%) | Boolean flag (1,382 entries) |
| 946 | 0x03B2 | float | 0.1, 1.0, 0.01, 0.3, 0.5 | Damage/effect scaling coefficient |
| 947 | 0x03B3 | ref | 0x20XXXXXX packed refs | Cross-reference (packed archive ref) |
| 950 | 0x03B6 | ref | 0x10XXXXXX def refs | Property definition reference |
| 524 | 0x020C | float | 0.45, 1.0, 0.5, 0.34 | Scaling coefficient |
| 531 | 0x0213 | float | 0.45, 1.0, 0.5, 0.4 | Scaling coefficient |
| 553 | 0x0229 | float | -5, -100, -30, -3 | Negative float parameter (NOT SP cost — verified against wiki, 0% match) |
| 554 | 0x022A | float | 5, 30, 100, 3, 25 | Positive float parameter (mirrors stat 553) |
| 719 | 0x02CF | int | 1 (97%), 0 | Boolean flag |
| 723 | 0x02D3 | float | 8, 18, 4, 13, 9 | Float parameter (NOT cooldown — verified against wiki, 0% match) |
| 724 | 0x02D4 | float | 6, 5, 50, 25, 20 | Float parameter |
| 1368 | 0x0558 | packed | varies | Packed spell parameter |
| 1381 | 0x0565 | packed | varies | Packed spell parameter |

Stats 946/947/950 use the same IDs as non-0x10 dup-pairs in item entries.

##### What spell entries encode vs. what they don't

**Encoded in 0x47 entries** (mechanical parameters):
- Spell name (via 0x25 shared namespace)
- Internal template/category code (slot 0) — defines delivery/VFX type
- Class-variant discriminator (slot 1; same spell has consecutive codes per class)
- Damage/effect scaling coefficients (stats 946, 524, 531)
- Cross-references to other game systems (stats 947, 950)
- Boolean flags and internal classification (stats 708, 731, 943, 719)

**Extractable from localization entries** (0x25XXXXXX in English archive):
- **In-game description** — via TOOLTIP sub-entry (ref 0x0B609513). Contains effect text, damage formulas, stat bonuses. Available for 97% of player spells (371/480 wiki-matched). Only 7% of NPC abilities have tooltips, making tooltip presence a strong player-spell indicator.
- **Short summary** — via SUMMARY sub-entry (ref 0x0F0EFF4E) when present.
- Saving throw type is mentioned in ~3% of tooltips; caster level references in ~1%. Tooltip text is prose, not structured.

**NOT encoded anywhere in the binary data** (verified via exhaustive search across spell entries, localization text, and all stat values):
- **School** — not in any ref slot, byte position, stat value, localization sub-entry, or general.dat template
- **Spell level** — no byte or stat value correlates with wiki spell level
- **SP cost** — not in tooltip text (0%), not in stat values (0%), not in body bytes
- **Cooldown** — not in tooltip text (0%), stats 723/724 do not match wiki values
- **Metamagic eligibility** — not identified in any stat or byte pattern
- **Maximum caster level** — not found as a direct value; occasionally referenced in tooltip prose

These player-facing attributes (school, level, SP, cooldown) are defined elsewhere — likely in the class spell table system (possibly 0x07XXXXXX game objects) or computed at runtime. The wiki remains the authoritative source for this metadata.

##### Player spell discrimination

Of 24K spell entries, most are NPC abilities (Arrow, Bolt, Attack, Set Bonus, etc.). Player-castable spells can be identified by:
1. **Tooltip presence** — 97% of player spells have TOOLTIP sub-entries vs 7% of NPC abilities
2. **Wiki name match** — 480 known player spells from wiki scraping
3. Both DID types (0x028B, 0x008B) contain player and NPC spells in similar ratios (~2% player)

##### Corrections to prior analysis

- Body is NOT always 0–2 bytes; 12% have body_size >= 4 (up to 1,832B)
- No 0x0A localization string refs found in any ref slot
- Two DIDs (0x028B and 0x008B) split the namespace, not one
- ref_count ranges from 0 to 252 (not 10–41 as previously documented)
- Stat_def_id values in the ref list are NOT "small integers" — many are IEEE 754 floats or 0x10/0x20 definition references
- Slot 0 is NOT a file reference into client_general.dat — it's an internal template code
- 37,937 compound 0x79 entries reference 0x47 spells for weapon procs/on-hit effects, not class spell assignments
- Ref-list dup-triple encoding is primarily a 0x47 phenomenon (41% of spell entries). Only 111 of 201K item entries (0.05%) embed spell parameters in their ref lists — these are "spell-items" with DID 0x028B/0x008B that use the spell preamble format. Their 253 ref-list stat values are entirely separate from the body's 0x10XXXXXX property keys. Other namespaces (0x07 game objects: 20 entries, 0x0C physics: 47 entries) show minimal dup-triple ref usage

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

- ~~Multi-block files~~ **Resolved** (2026-03-20): the apparent multi-block failure in `client_local_English.dat` was a localization parser bug, not a block-reading issue. `decode_localization_entry` now handles both 0x200 (DID present) and 0x400 (DID stripped) formats. The 61,738 gamelogic entries previously flagged as multi-block may have a similar offset issue, or may genuinely span blocks — needs re-evaluation.
- Exact purpose of `unknown2` and `timestamp` in B-tree entries (unknown1 = generation counter; timestamp = NOT Unix, likely patch sequence; unknown2 = small per-archive integer)
- What determines the actual stat identity (e.g. "Strength", "Dexterity", "Spot") for entry_type=17 bonus effects? The stat_def_id field in effect entries is a bonus-mechanism classifier (not per-stat), bonus_type_code is always 0x0000 for entry_type=17, and there is no magnitude. Type-167 entries have stat_def_id=0 at the container level but contain sub-effect blocks at byte 0xB0+ that may encode the actual stat identity. Census (2026-03-19): 201K effects total; type=17 has 88K entries (560 unique stat_def_ids), type=167 has 45K (sub-effect containers, partially decoded), type=53 has 34K (only 8 unique stat_def_ids, dominated by sid=376 at 93.6%). The per-stat discriminator likely lives in type-167 sub-effect blocks, type-59/173/503 entries, or a property on the parent 0x79XXXXXX item entry.
- Property type system for complex type-0x02/0x01 entries (LOTRO uses a registry at DID 0x34000000; DDO lacks it)
- Meaning of remaining 0x10XXXXXX keys (442 keys in DISCOVERED_KEYS as of this writing; coverage extends to keys appearing on 19+ of 236 named wiki items; ~560 lower-frequency unknowns remain, predominantly zero-constant schema placeholders for specific item sub-types)
- Spell school source: slot 1 is a variant/type ID (NOT school code); template codes (0x0147XXXX) encode delivery mechanism not school; only 9/166 templates exist in archives; school remains wiki-only
- Compound entry structure (ref_count=19, ref_count=46 groups): purpose of the large ref lists and keys 0x10000882, 0x10006392
- 0x07XXXXXX DID=2 spell scripts (16.5K entries): dense dup-triple property streams with 128M total key hits; may encode spell damage formulas, save DCs, targeting logic

**Resolved:**
- 0x144 field: confirmed NOT block_size. Values 0x200 (gamelogic) / 0x400 (english, general) are version codes.
- minimum_level: stored directly as key 0x10001C5D in dup-triple items (not computed at runtime)
- 0x47XXXXXX spell format: two DIDs (0x028B/0x008B) split 50/50; body 0-1832B (88% under 4B); ref list contains stat_def_id dup-triples (compact and extended formats); stat 553/554 encode SP cost as floats; stat 946 encodes damage scaling; 15 stat_def_ids mapped
- 0x0CXXXXXX: physics/particle/animation data — float-filled bodies, exotic DIDs
- 0x78XXXXXX: NPC stat definitions using dup-triple format with 0x10XXXXXX keys
- 0x70XXXXXX effect entry layout: variable-size, determined by entry_type at bytes[5..8]. Magnitude stored at type-specific offset (byte 68 for entry_type=53/0x35). entry_type=26 (37B): all copies identical, stat_def_id=1207, flag=1 — secondary augment marker. entry_type=175 (186B): stat_def_id=0, flag=3, contains 16-element magnitude-table starting at byte 64.
- Enchantment magnitude encoding: for entry_type=53 (0x35) effects, the u32 at byte 68 IS the bonus value. Multiple effect FIDs can be byte-identical copies sharing the same stat+type+magnitude specification.
- Non-0x10 dup-pairs: a second class of property records with key=stat_def_id (< 0x10000000), value=float32 or reference. Key repeated twice like standard dup-triples. Confirmed in feat/spell entries (keys 946, 947, 950 with float values).
- Multiple effect_ref keys: 10+ distinct keys all store 0x70XXXXXX values; different item types use different slots.
- 0x10XXXXXX FIDs in B-tree: these are property key declarations, NOT readable file content. Their B-tree metadata (data_offset, size) contains internal cross-references, not a valid block offset. Reading 0x10XXXXXX as archive content will always fail with "Missing block header."
- Non-0x10 dup-pair key=686 (0x2AE) value=0x10000B22: 0x10000B22 is a "property meta-key" reference, not a file content entry. It functions as a type/bonus-category identifier used in augment gem entries.
- Wiki enchantment field name: DDO Wiki {{Named item}} template uses field `enhancements` (not `enchantments`). Fixed 2026-03-19. Wiki enchantments use template syntax (e.g., `{{Stat|STR|7|Insightful}}`) not plain text — requires template-aware parser.
- Localization entry DID prefix: version 0x400 archives (English, general) strip the file_id+type prefix in `read_entry_data`, so `decode_localization_entry` content does NOT start with the DID. Fixed 2026-03-20; string table now loads 128,982 strings (was ~800). This was mislabeled as a "multi-block file support" issue.
- 0x0AXXXXXX namespace: Ogg Vorbis audio files (3,194 entries in English archive, ~4KB each). NOT supplementary localization text.
- 0x0147XXXX spell template codes: 166 unique values. Encode delivery mechanism (targeting, AoE shape, range), NOT spell school. Same code spans multiple schools (e.g., 0x0147005A across Abjuration, Enchantment, Evocation). Only 9/166 exist as entries in archives.
- Float-valued property keys: 190 keys identified with IEEE 754 float values. Key mappings: 0x10000907=duration(s), 0x10000B7A=cooldown(s), 0x10001B29=feat_cooldown(30s), 0x10000B60=tier/rank multiplier, 0x10000B5C=sign multiplier, 0x10000867/868/869=difficulty tier fractions (0.25/0.5/0.75), 0x10000742=internal level. See `docs/binary-reverse-engineering.md` for full table.
- Type-167 effect entry header: first ~0xB0 bytes are identical across all 45,094 entries (engine boilerplate). Three sub-type discriminator values at bytes 23-24: 0x0499 (98.8%), 0x01E8 (1.0%), 0x09D4 (0.1%). Variable sub-effect data in tail at byte 0xB0+.
- English archive namespace distribution: 138,797 entries across 0x00-0xFF. 0x25=132,783 (localization text, dominant), 0x0A=3,194 (audio), 0x00=591, 0x22=236, all others 1-64 entries.
- Type-167 sub-effect block format: ALL 37,013 720-byte entries are completely identical behavior script templates. Byte 0xB1=5 (sub-effect count) but all sub-effects are the same across entries. Dead end for per-entry stat extraction. Actual stat identity comes from sibling type-17/type-53 effects.
- Effect types 59 (1,811), 173 (1,545), 503 (417): ALL identical system templates with stat_def_id=0. Dead end.
- Pseudo-float file references: ~30K values across 6+ property keys reading as ~8.0 floats are actually 0x41XXXXXX file ID pointers to client_general.dat. Should be read as u32 pointers, not floats.
- 0x07XXXXXX game objects: 34,884 entries with 3 DID types. DID=2 (16,532): spell/ability behavior scripts. DID=4 (11,250): simple ability definitions. DID=1 (6,838): quest/dungeon scripts with embedded UTF-16LE quest text. Refs are mostly self-referential (35K of 36K+ refs point to other 0x07 entries).
- client_general.dat 0x01 namespace: 577 entries, mostly 3D scene definitions. 4.2 MB mega-entry (0x01000000) is a sparse world/scene definition, NOT a stat lookup table. 0x02 namespace (489 entries): purely visual/material data.
- 0x79XXXXXX preamble semantics: the 2-byte preamble at `prop_start = 5 + ref_count * 4` is a schema version code (81 distinct values). NOT a category discriminator — all item types appear under preamble 0x0010 (most common, 68K entries). Separate from ref_count: entries with ref_count=0 have preamble at bytes[5..6]; ref_count=19 entries have preamble at bytes[81..82] = always 0x3264; ref_count=46 entries have preamble at bytes[189..190] = always 0x6CD2.

## Implementation Status

### Archive parsing
- [x] Header parsing (all fields 0x140-0x1A4)
- [x] Brute-force file table scanner (flat page detection)
- [x] B-tree directory traversal (depth-first from root_offset)
- [x] Decompression (zlib with length prefix + raw deflate fallback)
- [x] File extraction with magic-byte type detection (OGG, DDS, XML, WAV, BMP)
- [x] Multi-block file support — **resolved**: the apparent multi-block failure was a localization parser bug. `decode_localization_entry` expected DID at byte 0, but version 0x400 archives strip the file_id prefix. Fixed 2026-03-20; string table now loads 128,982 strings (was ~800), binary items jump from 258 to 32,659.

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
- [x] 0x70XXXXXX effect entry layout (variable-size by entry_type; stat_def_id at data[16..17]; magnitude at byte 68 for entry_type=53; 7 stat_def_ids partially mapped; type-167 partially decoded as sub-effect containers)
- [x] 0x70XXXXXX type-59/173/503 effect entries (3,773 entries probed -- ALL identical system templates with stat_def_id=0; dead end for per-stat data)
- [x] Float-valued property key survey (190 keys identified: duration, cooldown, tier multiplier, difficulty fractions, mount speeds; pseudo-float 0x41XXXXXX file refs distinguished from real floats)
- [x] 0x70XXXXXX stat_def_id lookup table (5 confirmed mappings in STAT_DEF_IDS: Haggle/376, MRR/450, Saving Throws vs Traps/1572, Well Rounded/1692, Spell Points/1941; 5 candidates with 1 confirmation each and 0 conflicts: Spell Focus Mastery/1269, Charisma/1362, Constitution/1524, Strength/1730, Dodge/1827; decode_effect_entry() pipeline operational)
- [x] 0x47XXXXXX spell entry format (two DIDs 0x028B/0x008B; stat_def_id dup-triples in ref list; compact and extended encodings; 15 stat_def_ids mapped; SP cost in stat 553/554 as floats; damage scaling in stat 946; **school discovered at slot 15-16**: 88-91% confidence, values are large u32 hashes not small enums — each value consistently maps to one school. DID 0x028B: slot 15 (89.3%), DID 0x008B: slot 16 (90.9%). spell_points/level NOT in fixed slots — encoded in dup-triple stats only)
- [x] Property key census (`dat-registry` command -- empirical statistics)
- [x] Property ID name mapping (442 keys in DISCOVERED_KEYS; 28+ effect_ref slot variants; coverage down to keys appearing on ~19/236 named wiki items)
  - **Naming convention:** confirmed keys use descriptive names (`minimum_level`, `effect_ref`). Unconfirmed keys use `unknown_<context>_<hex4>` (e.g. `unknown_compound_0882`, `unknown_cluster_1C60`). Do not assign descriptive names to fields whose purpose is unverified.
  - **New pattern types discovered:** multi-occurrence array keys (same key repeating N times per item, encoding N list elements); non-dup-triple-visible keys (e.g. 0x10004C3A — 2262 occurrences in non-wiki 0x79 entries, 0 in wiki items); item sub-schema clusters (Sheet Music ~40+ zero-constant slots, Raging Torrent zeros, runearm cluster, Bolt/enchanted-item cluster); key-selector chains (keys whose values are other property key IDs); float~8.0 triplet (0x1000000E/1D36/242D); 0x0D88XXXX packed refs (runearm-specific).
- [x] Non-0x10 dup-pair records (stat_def_id keys with float/ref values; confirmed in feat/spell entries)
- [x] 0x79 dup-triple entry decoder (item definitions with [key][key][value] encoding)
- [x] Structured localization entry decoder (0x25XXXXXX with VLE string lengths, sub-entry refs)
- [ ] Nested/recursive property sets

### Game data extraction
- [x] Items parser (0x79 dup-triple decoding, enum resolution, wiki merge)
- [x] Effect entry decoding pipeline (Pass A: binary effects; Pass B: wiki enchantment templates parsed into structured bonuses via parse_enchantment_string, weapon/armor effects via parse_effect_template routed to item_effects table, metadata skipped; 9,313 stat-resolved bonuses, 12,822 item effects, 55% of items with stat bonuses, 71% with effects)
- [x] Equipment slot enum-to-seed alignment (EQUIPMENT_SLOTS labels renamed to match seed names; seed updated: Finger 1→Ring, Finger 2→Goggles, added Runearm; Legs slot removed; "Saving Throws vs Traps" stat seed row added at id=62)
- [x] slot_id FK resolution in insert_items() (_lookup_id via equipment_slot name; binary items will get slot_id populated on next extract run)
- [ ] Expand STAT_DEF_IDS beyond 10 entries — **largely blocked**. Correlation with 1,850 matched items confirmed sid 1692→"Well Rounded" (6 conf). Most sids are mechanism classifiers (sid 1254 appears with 172 stats). Effect file_ids ARE reused across items (0x700027E1 on 1,086 items) but 1:1 mapping yielded only 2 confirmed. Effect_ref property keys don't encode stat categories (all keys appear with 25-132 different stats). The stat identity is resolved at runtime, not stored in static files. Wiki remains necessary for stat bonus names. **Next step:** run dat-effect-map against full wiki catalog (~8,600 items) to discover more mappings via magnitude correlation.
- [x] Effect census (`dat-effect-census` command — 201K effects scanned: type=17 44.2% 560 unique stat_def_ids, type=167 22.4% undecoded, type=53 16.9% only 8 unique stat_def_ids and 1 bonus_type_code)
- [x] Wiki enchantment template parser (parse_enchantment_string handles {{Stat}}, {{Sheltering}}, {{SpellPower}}, {{Seeker}}, {{Deadly}}, {{Fortification}}, {{Save}} templates)
- [x] Wiki-to-binary effect correlation framework (`dat-effect-map` command — matches wiki enchantment strings to binary effect entries by magnitude + 1:1 type-17 fallback; 8,600 wiki items scraped, 35 matched binary entries, 13 correlations. **Confirmed:** type-17 stat_def_ids are mechanism classifiers, NOT stat identifiers — sid 1251 appears on Strength/Constitution/Intelligence items, sid 1440 on Well Rounded/Constitution/Wisdom. Stat identity must come from type-167 entries or a parent item property.)
- [x] Feats parser (parse_feats() + _merge_wiki_feats(); dat_id populated on binary-matched feats; damage_dice_notation decoded; build-db overlays dat_id + cooldown_seconds, duration_seconds, damage_dice_notation, scales_with_difficulty, tooltip from binary before insert)
- [x] Item dat_id overlay (148 wiki items matched with binary file IDs; name matching limited by binary string table coverage)
- [x] Classes seed data (15 classes with hit die, BAB, saves, caster type)
- [x] Races seed data (29 races — 17 standard + 12 iconic)
- [x] Set bonus effects (111 sets with 366 piece-count bonus effect rows from Named_item_sets wiki page)
- [x] Set membership linking (254 sets, 1,712 items linked via set_name + Named item sets templates)
- [x] Duration/cooldown extraction from binary
- [x] Internal level and tier multiplier extraction (float keys 0x10000742 and 0x10000B60 into items table)
- [x] 0x07XXXXXX game object structure survey (3 DID types: spells, abilities, quests; streaming probe completed) (float keys 0x10000907=duration, 0x10000B7A=cooldown; cooldown_seconds REAL and duration_seconds REAL columns on feats/spells/items tables)
- [ ] Enhancement rank bonuses from binary (type-167 sub-effect decoding at byte 0xB0+; 37K entries with 5 sub-effects each; would provide exact stat values per rank that wiki descriptions often omit)
- [x] Enhancements binary parser — deferred (game_data/enhancements.py stub removed from priority; wiki scraper provides full tree coverage with 88 class + 27 racial + 6 universal + 84 reaper = 205 trees)
- [x] Augments parser (778 augments scraped from wiki {{Item Augment}} template; 535 structured bonuses with source_type='augment')
- [x] Spells parser (497 spells scraped from wiki {{Infobox-spell}} template; class spell levels, schools, damage types, metamagic flags)
- [ ] Epic destinies parser (wiki pages don't use Enhancement table templates — different format, needs custom parser)
- [x] Filigrees parser (~380 filigrees scraped from Sentient Weapon/Filigrees wiki page; name, set_name, rare_bonus, bonus)
- [x] Past lives parser (58 past life feats detected and annotated with past_life_type/class during scraping)
- [x] Reaper enhancements parser (84 enhancements from Reaper enhancements wiki page via direct tree fetch)
- [x] JSON export pipeline (`ddo-data extract` command -- items)
- [x] Wire feat binary fields through overlay (cooldown_seconds, duration_seconds, damage_dice_notation, scales_with_difficulty, tooltip, description — _overlay_feat_binary_data now overlays all schema-backed fields where wiki has None)
- [x] Run dat-effect-map against full wiki item catalog (8,600 items, 1,850 matched binary entries, 411/5,178 correlations). **Result:** Only 1 confirmed stat mapping above threshold (Well Rounded/1692). 5 candidates with 1 conf, 0 conflicts already added. Mechanism classifier problem confirmed — sid 1254 has 172 conflicts across 22 stats. No new bonus_type_codes discovered. Stat identity resolved at runtime, not in binary.
- [x] Item numeric field correlation — ran dat-namemap with full 8,600-item wiki catalog (6,895 matched). **Result:** 0 new mappings. enhancement_bonus, armor_bonus, max_dex_bonus, hardness, weight, base_value confirmed NOT in dup-triple property keys. _WIKI_ONLY_FIELDS is correct.
- [x] Item enum field correlation — material, binding, handedness, proficiency, weapon_type also not found as simple property keys. Confirmed wiki-only or encoded in complex sub-structures inaccessible via current decoder.
- [x] Wire spell school from binary — 114-entry hash-to-school lookup table built from 178 wiki-matched spells. DID 0x028B slot 15 (89.3%), DID 0x008B slot 16 (90.9%). Wired into _overlay_spell_binary_data; overlays school where wiki has None. Covers all 8 schools including Divination.
- [x] Spell field correlation — extended spells_correlate.py with range/saving_throw/spell_resistance correlators. **Results:** range at slot 27 (100%, 12/12), slot 10 (93%, 28/30); saving_throw at slot 15 (90.5%, 105/116); spell_resistance at slot 29 (94.5%, 52/55). **Key finding:** slots 15-16 and 29 show high correlation for MULTIPLE fields (school + saving_throw + spell_resistance), indicating the u32 ref values are **packed composite fields** encoding several attributes per slot. Decoding the bit layout is needed before wiring range/save/SR into the overlay.

### Binary architecture: template instancing

DDO uses a **slot-driven template instancing** architecture for item effects. A small number of shared template entries are referenced by many game objects via effect_ref slots. Per-instance meaning comes from context, not data in the template:

- **Type-17**: 88,866 entries but ALL copies per stat_def_id are byte-identical. One template per stat type, shared across thousands of items.
- **Type-26**: 2,373 entries, 11 unique templates. Per-stat marker.
- **Type-53**: 31,886 entries, 78/84 bytes constant. Only stat_def_id, bonus_type, and magnitude vary.
- **Type-62**: 188 entries, only 3 unique patterns.
- **Type-167**: 45,094 entries, 37,013 are completely identical.
- **Type-59/173/503**: ALL entries per type are byte-identical.

This means stat identity, augment configuration, weapon damage, etc. are NOT in the effect entries. They're resolved at runtime by: (1) which effect_ref slot points to the template (slot position = semantic meaning), (2) the parent item's dup-triple properties, (3) runtime game state. The effect_ref slot-to-type mapping is deterministic (effect_ref=type-17, effect_ref_2=type-414, effect_ref_18=type-53, etc.).

**Template content vs. template FID identity:** The template CONTENT is identical across stats (all type-17 sid=1254 entries are byte-identical). But the template FID is stat-specific — different stats reference DIFFERENT FIDs. This means the stat identity IS in the binary, encoded as **which specific effect FID is referenced**, not what's in that FID's bytes.

**Proof via discriminant analysis:** effect_ref FIDs are 87% stat-discriminating (74 stat-unique vs 11 shared across 85 FIDs). Built 89-entry effect_fid→stat lookup table with 0 conflicts from wiki cross-reference (e.g., 0x70002A03→CON with 30 confirmations). 7% initial coverage (2,112/27,835 items) — expands as more wiki items are matched.

**Implication for the build planner:** Stat names CAN be resolved from binary via effect_fid→stat lookup tables built from wiki cross-reference. Binary provides magnitudes (type-53), stat identity (via FID lookup), feat chains (type-414), and structural metadata. Wiki remains needed for FIDs not yet in the lookup table.

### Binary reverse-engineering (complete before pre-frontend gates)

**Completed investigations:**
- [x] Packed spell ref slot bit layout — **DISPROVEN**: byte-level decomposition shows opaque template pointers, not bitfields. Save/SR/range correlations were spurious (school predicts save type). Only school independently decodable.
- [x] Spell ref-slot field correlation for remaining fields — components, target, duration, damage_types, metamagics NOT found in ref slots. Confirmed wiki-only for ref-slot encoding.
- [x] Set membership discovery — group_ref (0x10000A48) is NOT set membership. 16,400 entries across 17 values mixing quests/NPCs/items. Confirmed wiki-only.
- [x] Per-field data provenance — cleaned up _WIKI_ONLY_FIELDS: removed minimum_level (now from binary). Pipeline tracks provenance implicitly.

**Requires further reverse-engineering (DO NOT mark complete without implementation):**
- [x] Build and wire effect_fid → (stat, bonus_type) collapsed lookup — 97 entries mapping FID to (stat_name, bonus_type) tuples in EFFECT_FID_LOOKUP. FID lookup is PRIMARY resolution path (more reliable than content-based STAT_DEF_IDS: 97 entries vs 10, 0 conflicts). decode_effect_entry provides magnitude; FID lookup provides stat identity. Expand coverage beyond 7% by: (a) including multi-stat items with magnitude matching, (b) using effect_ref_18 (type-53) FIDs which are also stat-discriminating (6 stat-unique out of 9), (c) cascading — once an FID is confirmed, use it to resolve other items sharing that FID. Wire the lookup into the items parser to populate stat_id on binary bonuses.
- [ ] Apply FID-identity approach to ALL template-blocked tasks — the stat discovery showed that template CONTENT is shared but template FID is context-specific. Every previous "dead end" where we found identical template content should be re-examined via FID discriminant analysis:
  - **(a) bonus_type resolution** — **CONFIRMED**: effect_ref FIDs are 95% bonus-type-discriminating (113/119 unique). effect_ref_18 is 92% (11/12). Different bonus types use different FIDs. Lookup table buildable via same wiki cross-ref approach as stat names.
  - **(b) augment slot detection** — **CONFIRMED**: effect_ref FIDs are 95% augment-count-discriminating (618/649). effect_ref_26 is 100% (34/34 — perfect discriminator). Items with different augment counts use different FIDs.
  - **(c) weapon damage/crit** — **CONFIRMED**: effect_ref FIDs are 89% damage-discriminating (355/398). effect_ref_26 is 100% (32/32 — perfect). Different damage dice map to different FIDs.
  - **(d) mechanism classifier FIDs** — effect_ref_23 is 50% discriminating (5/10). Shared slots (effect_ref_shared) are NOT discriminating (1 FID each). Moderate supplementary signal only.
  - **(e) type-26 augment marker FIDs** — no type-26 entries found in matched items' effect chains. Not referenced through standard effect_ref slots. Dead end.
  - **(f) type-167 sub-effect FIDs** — 73-74% stat-unique across slots 11/12/13. Moderate discrimination — useful as supplementary lookup alongside primary effect_ref.
  - **(g) type-62 pattern FIDs** — only 2 FIDs across 7 matched items. Too small to be useful.
  - **(h) type-414 sub-chain FIDs** — 43% stat-unique (3/7). Weak — type-414 FIDs are shared across stats.
- [x] Spell body stat decoding — wired body dup-triple scanning into _overlay_spell_binary_data. Now scans both ref list AND body bytes for stats 553/554 (SP cost), 946 (damage scaling), and 731 (tick/effect count). Stat 731 values 1-8 encode tick count (Focusing Chant=1, Cometfall=3, Cloudkill=5, Energy Drain=8). Other body stats (708=mechanism code, 943=boolean flag, 950/947/1368=config refs) are engine internals, not player-facing.
- [ ] Class/race body decoding — **extensively investigated, partially decoded**:
  - 7-byte header: `01 01 1B 00 00 00 XX` (XX=class index, constant 0x1B=27)
  - 128-byte shared preamble: identical across all classes. Contains VLE Pascal strings "on"/"off" (toggle states). Uses DDO-extended VLE type tags (type 8193 = 0x2001) that the Turbine decoder doesn't support.
  - Class-specific section: varies wildly (18B Rogue, 190B Sorcerer/Wizard, 5218B Ranger). Sorcerer vs Wizard differ in only 8 bytes (4 pairs of class-specific IDs). Contains floats 40.0/60.0 (level thresholds?).
  - Ranger ability blocks: 50 blocks at 92 bytes each, mirrored in two halves (blocks 0-24 = blocks 25-49). Per block: circle assignment (0-4), level threshold float, flags. Circle distribution matches wiki Ranger spell counts.
  - **Blocked on:** (a) DDO extended VLE type tags (8193+) prevent full preamble decode, (b) 0x07XXXXXX values in blocks are packed parameters not file IDs (not in archive), (c) cannot map blocks to specific spells without runtime data.
  - **Decodable now:** class index, ability block count, per-block circle/level/flags. **Not decodable:** specific spell-to-block mapping, base class stats (hit die, BAB, saves) in the opaque preamble.
- [ ] Feat flag discovery — **found separate property keys encoding feat types** (562 matched feats). Active: keys 0x10000829 (100%, N=7) and 0x10002878 (100%, N=10) appear only on active feats. Stance: key 0x100024D1 (90%, N=10) and 0x10000771 (85%, N=26). Free: key 0x100040FB (100%, N=7). Epic destiny: key 0x100033C9 (50%, N=8). Metamagic: wiki only has 1 metamagic feat ("Empower Healing Spell") — wiki `metamagic=yes` flag is barely populated, but binary has 100+ metamagic-related entries ("Efficient Metamagic: Empower", "Improved Empower Spell", etc.). **Needs:** (a) verify flag keys with more examples, (b) wire presence/absence of these keys into feat parser to set is_active/is_stance/is_free from binary, (c) fix wiki metamagic flag scraping (base feats "Empower Spell", "Maximize Spell", etc. should have metamagic=yes), (d) the original bitmask key 0x1000088E may encode a different taxonomy (ability type/category).
- [x] Feat bonus_classes discovery — **no class-specific keys found**. 223 feats with bonus_classes matched. Keys appearing on barbarian/warlock bonus feats (0x10000B2E, 0x10000566) have only 37-42% rates and appear on non-bonus feats too. Bonus class eligibility is NOT encoded in binary properties. Confirmed wiki-only.
- [x] Augment slot format investigation — **wiki parser fixed**: augment slots are `{{Augment|Color}}` templates embedded in the enhancements field (not a separate augmentslot= field). Parser now extracts them: 5,748/8,600 items have slots. Correlated 2,238 matched binary items against slot count — **no property key encodes slot count or color**. Key 0x10000A1D not present on matched items. Augment slots are confirmed NOT in dup-triple properties. Likely encoded in effect_ref chain or complex sub-structure. Confirmed wiki-only.
- [x] Effect mechanism classifier decomposition — **DEFINITIVE DEAD END**: ALL entries for each stat_def_id are byte-for-byte identical (31,750 identical entries for sid 1254, 12,350 for 1440, 11,333 for 551, 8,266 for 2114). These are template entries, not per-item data. Stat identity is determined by which effect_ref slot in the parent item references the effect — a runtime lookup, not stored in the binary.

**Requires deeper binary investigation (DO NOT mark complete without implementation):**
- [x] Item effect_ref chain decoding — **traced full chains for known weapons/armor with augments**. Most items have 1-4 refs populated (not 28+). Chain encodes enchantment bonuses (type-17 mechanism classifiers, type-53 magnitude bonuses) and special properties. Weapon damage, critical range, and augment slots are NOT in the chain. Shared effect 0x700027E1 (Sprint Boost, stat 2053) on 1,086 items.
- [x] Effect type 414 decoding — 46 entries, 425B, 20 unique. Body contains chains of 0x70 effect FID refs with float 1.0 multipliers (pattern: `[fid:u32][00 00 80 3F]` repeated). These encode **which sub-effects a feat grants** — a feat-to-effect mapping table. The sub-effect FIDs could be decoded further to extract feat bonus values. 289/425 bytes constant.
- [x] Effect_ref slot-to-property mapping — **slots have CONSISTENT entry_types**: effect_ref=type-17 (100%, 2,008 items), effect_ref_2=type-414 (100%, 1,383), effect_ref_18=type-53 (100%, 424 = magnitude bonuses we decode), effect_ref_11/12/13=type-167 (sub-effects), effect_ref_28=type-95/175 (augment-related). **Slot 28 references type-175 magnitude tables.** Slot mapping is deterministic — each slot always points to the same effect type.
- [x] Effect_ref slot 28 investigation — 526 items reference slot 28, but only 23 (4.4%) have wiki augment slots. **NOT augment-related.** Slot 28 references type-95 (spell damage config, 376 items) and type-175 (tier scaling, 96 items). No augment correlation.
- [x] Effect type 95 decoding — 6 entries, 106B, 94/106 constant. Named "Meteor Swarm", "Combustion". Bytes 72-83 contain 3 pairs of effect FID refs. **Spell damage configuration entries** — encode spell damage parameters, not augments.
- [x] Effect type 62 decoding — 188 entries, 93B, **only 3 unique patterns** (89/93 bytes constant). Named entries include "Colorless Augment Crystal" (coincidental name sharing). Bytes 16-17/49-50 vary between 2 states. Shared templates like type-26 — dead end for per-item data.
- [x] Item complex sub-structure decoding — **DEAD END**: items do NOT use DID=2. They have non-standard DIDs (0x92100013, 0x42811000, etc.) and the dup-triple decoder already extracts ALL their properties. There is no hidden VLE body beyond dup-triple. Weapon damage, critical range, augment slots, and material are definitively NOT in the binary (not in dup-triple properties, not in effect_ref chain, no complex body exists). Confirmed wiki-only.
- [x] 0x70 type-26 augment marker decoding — **all entries per stat_def_id are byte-identical templates** (1/2038 unique for stat 1207). 37 bytes: stat_def_id at bytes 16-17 and 30-31 with fixed padding. No augment slot color data. Dead end.
- [x] 0x70 type-175 magnitude table decoding — only 17 unique entries. "Magnitude table" at byte 64 is tier scaling: paired values 1,1,2,2,...8,8 (tier-to-multiplier map). Shared templates, not per-item. Low build-planner value.
- [x] Linked chain property structure — **decoded: engine infrastructure, not build data**. 6,372 entries but 95% (6,045) are chain_type=18 sharing the SAME chain_head (0x1000A084) and chain_start (0x10730300). chain_count is always 1-2. Only 86 items vs 6,286 feats/abilities. chain_type categorizes game system (18=general, 15=spells, 16=augment-related, 19=quests) but chain values are shared property-system pointers, not per-entity relationships. Dead end for build planner.
- [x] 0x70 type-53 effect unexplored bytes — **78/84 bytes are constant**. Only 6 vary beyond known fields: byte 63 (3 unique), byte 67 (boolean), byte 72 (mostly 99, possibly stacking cap), byte 76 (boolean flag), byte 82 (3 unique). Almost no additional data. Dead end.
- [x] Item unknown property keys — **surveyed 4,830 unconsumed keys on items**. Top 15 by frequency (24K-32K each) are all engine metadata: constants (0x100018AA), schema refs (0x10001C58), format signatures (0x10000002), template refs (0x10000DE2). All classified "low" confidence in DISCOVERED_KEYS. No build-relevant fields found among high-frequency unconsumed keys.
- [x] Feat flag key wiring — wired 9 active-feat keys, 2 stance keys, and 1 free-feat key into feats.py `_decode_feat_entry()`. Sets `is_active_binary`, `is_stance_binary`, `is_free_binary` flags. Overlay in cli.py maps these to `active`, `stance`, `free` fields where wiki doesn't have them.
- [x] Spell ref slots 3-14 and 17+ — **surveyed value ranges across 23K entries**. ALL non-stat slots span the full u32 range (min~0, max~4B), with <10% having small values (<1000). These are opaque template/config pointers, NOT numeric parameters like AoE radius or range. No build-relevant data in non-stat ref slots.
- [x] Localization sub-entry types — **scanned 4,209 entries**. 2,176 potential new refs found but most are VLE length/count prefixes (0x02000000-0x0F000000 are round numbers). Only 1 known ref matched. No evidence of major missing sub-entry types beyond the 13 already cataloged.
- [x] DDO extended VLE type tags — **DISPROVEN: not VLE at all**. Tested 5 alternative VLE interpretations for type tag 8193 (base_type masking, flag stripping, tsize at different offsets). ALL produce garbage values. The class body after the 7-byte header uses a **fixed template-specific format** (template ID 27 from bytes 2-5), NOT VLE property streams. The strings "on"/"off" at fixed offsets (43, 83) confirm position-based layout. Decoding requires template-27 field documentation (not available from static analysis — needs game client RE or community docs).
- [x] Type-1 behavior script investigation — **6,838 entries, sizes 11-9,598B typically**. Named entries include feat scripts ("Improved Critical: Throwing Hammer" 442B, "Greater Weapon Specialization: Maul" 787B) with embedded localization text. Bodies use same VLE format as class entries (blocked on DDO VLE type tags). Quest scripts dominate. Feat/ability scripts contain description text but numeric parameters (damage values, DCs) are in the VLE body that we can't parse yet.
- [x] Runearm sub-schema — **FALSE POSITIVE**: keys 0x1000076B, 0x10000C90, 0x1000278E appear on trap parts, shard deconstruction, NPCs — NOT runearms. They're generic tier/rate keys across game systems. Real runearms (e.g., "Toven's Prototype") have equipment_slot=17 but don't carry these keys. Runearm-specific binary data (charge level, max charge) not found in dup-triple properties. May be in effect_ref chain or not in binary at all.

### Wiki parser improvements (complete before pre-frontend gates)
- [x] Fix augment slot extraction — augment slots were `{{Augment|Color}}` templates embedded in the enhancements field. Parser now extracts them (5,748/8,600 items). Also handles legacy `augmentslot=` field format.
- [x] Fix `_parse_bool` for HTML comments — wiki templates have `metamagic=yes\n<!--class-->` which silently failed. All 9 metamagic feats (Empower, Maximize, Quicken, Heighten, Enlarge, Extend, Accelerate, Intensify, Empower Healing) now parse correctly. Also fixes `active=yes` with comments.
- [x] Re-probe binary after wiki improvements — metamagic: 11 feats now parsed (was 1), but **no metamagic-correlating binary keys** (metamagic feat names like "Empower Spell" don't match binary entries). Active: 198 feats (was 191). Active flag keys confirmed: 0x10000D81, 0x10000829, 0x10002878 all 100% (N=7-10), plus 0x100008E2, 0x100020D0/D1, 0x100059F6, 0x10006F7C/7D — a cluster of ~10 keys that ALL appear only on active feats.

### Pre-frontend gates
- [ ] **PRE-FRONTEND GATE:** Opaque binary audit — catalog all sections of binary data that remain undecoded or partially understood. For each: (a) what data is there, (b) how large is it, (c) what format does it use, (d) what would decoding yield for the build planner, (e) estimated effort. Known opaque sections: Type-2 complex-partial VLE bodies (class entries, ~35K entries total), Type-1 behavior scripts (6,838 entries), 0x70 type-167 sub-effect containers (45K entries), effect mechanism classifiers (stat_def_ids 1254/1440/551/2114 covering 64K entries). Goal: ensure we have a complete inventory of undecoded data before frontend work begins, so we can prioritize what to decode later without missing anything.
- [x] **PRE-FRONTEND GATE:** Binary coverage audit (2026-03-22) — systematically ran all correlators against full wiki catalogs. Results by entity:
  - **Items:** 0 new property key mappings from 6,895 matched entries. _WIKI_ONLY_FIELDS confirmed correct for enhancement_bonus, armor_bonus, max_dex_bonus, hardness, weight, base_value, material, binding, handedness, proficiency, weapon_type, damage, critical, augment_slots, set_name, quest.
  - **Feats:** bitmask key 0x1000088E (144 unique values) does NOT map to is_passive/is_active/is_stance/is_metamagic. 61-feat sample too small for conclusive results. Wiki flags remain wiki-only.
  - **Spells:** school NOW from binary (114-entry hash lookup). range/saving_throw/spell_resistance discoverable but blocked on packed bit-layout decoding. Components/target/duration/metamagics not yet investigated.
  - **Effects:** STAT_DEF_IDS wall confirmed — only 1 mapping (Well Rounded/1692) above 3-confirmation threshold from 8,600 items. 5 candidates with 1 conf added. stat identity resolved at runtime. BONUS_TYPE_CODES: 0 new confirmed.
  - **Enhancements/augments/sets/filigrees:** wiki-only (no binary parser).
- [ ] **PRE-FRONTEND GATE:** Unimplemented discoveries audit — review all findings from binary RE that were discovered but not yet wired into the parser/overlay/DB pipeline. For each: (a) is the data build-relevant, (b) what code changes are needed, (c) are there new DB columns required. Known unimplemented: feat active/stance/free flags (wired but not yet in DB as dedicated columns vs wiki booleans), spell school hash lookup (wired), tick_count (wired), runearm keys (false positive — no action), effect_ref slot mapping (documented, not consumed).
- [x] **PRE-FRONTEND GATE:** Normalize bonuses schema — replace polymorphic `source_type`/`source_id` design with proper M2M junctions. Current `bonuses` table uses a polymorphic FK that can't enforce referential integrity. New design: `bonuses` table holds unique bonus definitions (stat_id, bonus_type_id, value), with separate junction tables (`item_bonuses`, `feat_bonuses`, `augment_bonuses`, `enhancement_bonuses`, `set_bonus_effects`) using proper FKs. All junctions include `data_source TEXT CHECK (data_source IN ('binary', 'wiki'))` for provenance tracking. This naturally deduplicates ("+7 Enhancement Strength" is one row linked to many items), mirrors binary template architecture, and solves the binary/wiki Pass A/B dedup problem. Must complete before frontend builds queries against the schema.
- [ ] **PRE-FRONTEND GATE:** Schema alignment audit — comprehensive review producing a report for the user. Checks:
  1. **Field coverage**: verify all binary-decoded fields have corresponding DB columns and correct types
  2. **Enum alignment**: verify enum code-to-seed ID mappings are consistent
  3. **Writer field-flow**: verify every parser dict key is consumed by insert_* (no silently dropped data)
  4. **CHECK constraints**: verify all observed binary values pass schema constraints
  5. **Normalization**: review all tables for row duplication patterns (like the old bonuses table had) — check if effects, item_effects, spells, enhancements, or other tables should be normalized with shared definitions + M2M junctions
  6. **Column usage audit**: for every column across all tables, check population rate (% of rows with non-NULL values). Flag columns that are never or rarely populated (<5%). For each flagged column: determine if it should be eliminated (dead code), kept (intentionally sparse for future use), or investigated (should be populated but isn't due to a bug)
  7. **Output**: present a structured report to the user with findings grouped by severity (critical/warning/info) before making any changes

### Wiki data population (complete before pre-frontend gates)
- [ ] Populate feat_prereq_* tables from wiki (feat_prereq_feats, feat_prereq_stats, feat_prereq_classes, feat_prereq_races, feat_prereq_skills)
- [ ] Populate class progression tables from wiki or binary (class_bonus_feat_slots, class_spell_slots, class_spells_known, class_skills, class_auto_feats)
- [ ] Populate race tables from wiki (race_ability_bonuses, race_feats)
- [ ] Populate enhancement prerequisite tables from wiki (enhancement_tree_ap_thresholds, enhancement_prereqs, enhancement_prereq_classes, enhancement_prereq_races, enhancement_feat_links)

### Asset extraction
- [x] DDS texture extraction from client_general.dat
- [x] DDS to PNG conversion (Pillow)
- [x] Icon pipeline (`ddo-data icons` command)

### Supplementary data
- [x] DDO Wiki scraper — items (`ddo-data build-db --type items`)
- [x] DDO Wiki scraper — feats (`ddo-data build-db --type feats`)
- [x] DDO Wiki scraper — enhancements (`ddo-data build-db --type enhancements`)
- [ ] DDO Wiki scraper — quests
- [x] DDO Wiki scraper — augments (`ddo-data build-db --type augments`)
- [x] DDO Wiki scraper — spells (`ddo-data build-db --type spells`)
- [ ] DDO Wiki scraper — epic destinies
- [x] Data merging (game files + wiki data -- items via `_merge_wiki_data`)

### CLI
- [x] `parse`, `list`, `dat-extract`, `dat-peek`, `dat-stats`
- [x] `dat-dump`, `dat-compare`, `dat-survey`, `dat-compare-entries`, `dat-validate`, `dat-probe`, `dat-registry`
- [x] `extract` (JSON export -- items with `--wiki-items` merge)
- [x] `icons` (DDS to PNG)
- [x] `dat-namemap` (property key name mapping via wiki cross-reference)
- [x] `dat-identify` (entity category inventory via B-tree + localization cross-reference)
- [x] `dat-effect-census` (stat_def_id and bonus_type_code histograms from 0x70 effect entries)
- [x] `dat-effect-map` (wiki enchantment → binary effect correlation mapper)
- [x] `build-db` (wiki scraping + SQLite database creation; items, feats, enhancements)

### Frontend
- [x] `useDatabase` React hook (sql.js WASM, singleton promise pattern, queries `public/data/ddo.db`)

## Credits

See [README.md](../README.md#credits) for the full list of references and acknowledgments.

Our implementation was independently reverse-engineered from actual DDO game files, with corrections from community LOTRO/DDO tools.
