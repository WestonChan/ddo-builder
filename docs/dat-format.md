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
- Meaning of remaining 0x10XXXXXX keys (442 keys in DISCOVERED_KEYS as of this writing; coverage extends to keys appearing on 19+ of 236 named wiki items; ~560 lower-frequency unknowns remain, predominantly zero-constant schema placeholders for specific item sub-types)
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
- [x] Property ID name mapping (442 keys in DISCOVERED_KEYS; 28+ effect_ref slot variants; coverage down to keys appearing on ~19/236 named wiki items)
  - **Naming convention:** confirmed keys use descriptive names (`minimum_level`, `effect_ref`). Unconfirmed keys use `unknown_<context>_<hex4>` (e.g. `unknown_compound_0882`, `unknown_cluster_1C60`). Do not assign descriptive names to fields whose purpose is unverified.
  - **New pattern types discovered:** multi-occurrence array keys (same key repeating N times per item, encoding N list elements); non-dup-triple-visible keys (e.g. 0x10004C3A — 2262 occurrences in non-wiki 0x79 entries, 0 in wiki items); item sub-schema clusters (Sheet Music ~40+ zero-constant slots, Raging Torrent zeros, runearm cluster, Bolt/enchanted-item cluster); key-selector chains (keys whose values are other property key IDs); float~8.0 triplet (0x1000000E/1D36/242D); 0x0D88XXXX packed refs (runearm-specific).
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
- [x] DDO Wiki scraper — items (`ddo-data build-db --type items`)
- [x] DDO Wiki scraper — feats (`ddo-data build-db --type feats`)
- [x] DDO Wiki scraper — enhancements (`ddo-data build-db --type enhancements`)
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
- [x] `build-db` (wiki scraping + SQLite database creation; items, feats, enhancements)

## Credits

See [README.md](../README.md#credits) for the full list of references and acknowledgments.

Our implementation was independently reverse-engineered from actual DDO game files, with corrections from community LOTRO/DDO tools.
