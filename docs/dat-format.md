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
| 0x144 | Version | `0x200` (gamelogic), `0x400` (english/general). DATExplorer calls this "block_size" -- needs verification against DDO. |
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

| Bytes | Type | Field |
|-------|------|-------|
| 0-3 | uint32 | unknown1 |
| 4-7 | uint32 | file_type (low byte = compression type) |
| 8-11 | uint32 | file_id |
| 12-15 | uint32 | data_offset |
| 16-19 | uint32 | size (uncompressed) |
| 20-23 | uint32 | timestamp |
| 24-27 | uint32 | unknown2 |
| 28-31 | uint32 | disk_size (compressed/on-disk size) |

Note: The field ordering differs between flat pages and B-tree nodes. Both formats have been validated independently.

### File IDs

File IDs encode the entity namespace in their high byte. The B-tree in `client_gamelogic.dat` contains 490,001 entries across the following namespaces (confirmed via `dat-identify`):

| High byte | Count | Entity type |
|-----------|-------|-------------|
| `0x79` | 201,272 | **Item definitions** — dup-triple encoded property sets |
| `0x70` | 201,105 | **Effect/enchantment definitions** — 28-byte binary format (see below) |
| `0x07` | 34,884 | **Game objects** — quests, NPCs, behavior scripts, trigger logic |
| `0x47` | 24,008 | **Spells / active abilities** — DID=0x028B, many cross-archive refs |
| `0x0C` | 20,943 | Mixed (includes map/zone data) |
| `0x78` | 1,078 | Unknown |
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
| `0x0CXXXXXX` | varies | Zone/map data and mixed content |

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

#### Effect entries — 0x70XXXXXX namespace (28-byte binary format)

201,105 effect/enchantment definitions, nearly 1:1 with item entries (201,272). Each item enchantment in a `0x79XXXXXX` entry holds an `effect_ref` property (key `0x10000919`) pointing to a `0x70XXXXXX` effect entry.

Effect entries have DID=0x02 but do **not** use the standard type-2 property stream. Instead they use a fixed-width binary layout:

```
[DID:u32=2] [ref_count:u8=0] [body: 23 bytes]
```

**Body layout (23 bytes, most common variant):**
```
+00: u32  -- fixed preamble (constant across most entries)
+04: u32  -- fixed preamble (constant across most entries)
+08: u16  -- property definition ID (e.g. 0x04E3 = stat type 1251)
+0A: u32  -- fixed preamble continued
+0E: u16  -- property definition ID (duplicated)
+10: ...  -- additional fixed bytes
```

The 2-byte property definition ID appears twice (offset +8 and +14 in the body). This ID encodes the type of stat bonus (strength, hit points, spell power, etc.) and likely indexes into the definition table referenced by `0x10XXXXXX` keys.

A 37-byte variant adds extra fields (numeric value, bonus type qualifier) at the end. The extra bytes are variable across entries.

To decode: use `ddo-data dat-dump --id 0x70XXXXXX` to hex-inspect a specific effect entry. The property definition ID is the primary data field — look up its value against known stat IDs to determine what the effect modifies.

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

Body structure not yet decoded — the high ref-count (10–41) suggests each spell references multiple effect, animation, and sound assets.

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

- Multi-block files (entries where data may span multiple blocks)
- Whether 0x144 is "version" (our interpretation) or "block_size" (DATExplorer)
- Exact semantics of unknown fields in B-tree file entries
- Property type system for complex type-0x02/0x01 entries (LOTRO uses a registry at DID 0x34000000 to map property IDs to types; DDO lacks this registry in all 3 .dat files, so value types cannot be determined from metadata)
- Meaning of remaining 0x10XXXXXX definition reference values (7 keys identified via distribution analysis in `DISCOVERED_KEYS`; ~200+ remain unmapped)
- The 2-byte property definition ID in 0x70XXXXXX effect entries: how to map values (e.g. 0x04E3) to stat names (Strength bonus, spell power, etc.)
- 0x79XXXXXX "dup-triple" entry format: preamble semantics, section break rules, relationship between lone-pair and dup-triple records
- Whether minimum_level is always computed from effects or sometimes stored directly
- 0x47XXXXXX spell entry body format (high ref-count but body not yet decoded)
- 0x0CXXXXXX namespace: zone/map data structure unknown

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
- [ ] 0x70XXXXXX effect entry decoder (2-byte property definition ID identified; stat ID lookup table needed)
- [ ] 0x47XXXXXX spell entry decoder (DID=0x028B confirmed; body format unknown)
- [x] Property key census (`dat-registry` command -- empirical statistics)
- [x] Property ID name mapping (7 keys via distribution analysis: level, rarity, durability, equipment_slot, item_category, effect_value, effect_ref)
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
