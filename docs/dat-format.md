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

File IDs encode the archive type in their high byte:
- `0x01XXXXXX` -- general assets (`client_general.dat`)
- `0x07XXXXXX` -- game logic (`client_gamelogic.dat`)
- `0x0AXXXXXX` -- localization (`client_local_English.dat`)

Additional high bytes seen in cross-references within game data:
- `0x40XXXXXX`, `0x41XXXXXX`, `0x78XXXXXX` -- purpose unknown
- `0x70XXXXXX` -- common in type 0x04 array properties (quest/effect/trigger refs?)
- `0x05XXXXXX`, `0x20XXXXXX`, `0x2AXXXXXX`, `0x39XXXXXX`, `0x47XXXXXX` -- rare, seen in type 0x04 arrays

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

**Entry type distribution** (from `dat-survey` of ~2,270 entries):

| DID | Count | Avg Size | Notes |
|-----|-------|----------|-------|
| 0x02 | 1,304 (57%) | 2,172 B | Items, feats, enhancements -- dominant type |
| 0x04 | 709 (31%) | 36 B | Cross-reference/link entries -- **fully decoded** |
| 0x01 | 137 (6%) | 8,874 B | Complex objects with ASCII strings |
| 0x8B | 12 | 285 B | |
| Other (53 codes) | 108 | varies | |

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

#### Type 0x02 entries (partially decoded, ~60% exact parse rate)

Type-2 entries have two sub-populations:

**Simple variant** (~785/1304, 60%): identical to type-4 format except `pad=1`:
```
[DID:u32=2] [ref_count:u8] [file_ids:u32[]] [pad:u32=1] [flag:u8] [prop_count:u8] [properties...]
```
Properties use the same `[key:u32][value:u32]` greedy encoding as type-4 (where non-zero value < 256 is an array count). Parses exactly with 0 bytes remaining.

**Complex variant** (~519/1304, 40%): body starts with a `tsize` (skip byte + VLE) giving a property count, followed by a Turbine property stream:
```
[DID:u32=2] [ref_count:u8] [file_ids:u32[]] [tsize -> prop_count] [property_stream...]
```
The property stream uses typed values (int, float, string, struct, array) determined by a **property definition registry** (DID 0x34000000 in LOTRO). This registry does **not exist** in any DDO `.dat` file, preventing full type-aware decoding. Pattern detection identifies definition refs, ASCII strings, floats, and file ID cross-references within the body.

Use `ddo-data dat-probe <file> --id <hex>` to decode type-2 entries.

#### Type 0x01 entries (under investigation)

Pattern detection shows:
- **Definition references** (0x10XXXXXX) throughout, likely serving as property keys or schema pointers
- **Length-prefixed ASCII strings** (byte count + ASCII text)
- **IEEE 754 floats** (commonly 1.0)
- **Cross-archive file ID references** (0x07, 0x0A, 0x01 high bytes)

Likely uses the same Turbine property stream format as complex type-2, blocked by the same missing registry.

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
- `probe.py` -- data-driven format probe: entry header parsing, pattern detection, type-4 and type-2 decoders
- `survey.py` -- statistical survey: type code histogram, size distribution, string density
- `tagged.py` -- legacy TLV scanner (superseded by probe.py for structured decoding)
- `compare.py` -- byte-by-byte comparison of same-type entries

Use `ddo-data dat-probe`, `ddo-data dat-survey`, `ddo-data dat-dump --id <hex>`, and `ddo-data dat-compare-entries --type <hex>` for exploration.

### Open Questions

- Multi-block files (entries where data may span multiple blocks)
- Whether 0x144 is "version" (our interpretation) or "block_size" (DATExplorer)
- Exact semantics of unknown fields in B-tree file entries
- Property type system for complex type-0x02/0x01 entries (LOTRO uses a registry at DID 0x34000000 to map property IDs to types; DDO lacks this registry in all 3 .dat files, so value types cannot be determined from metadata)
- Meaning of the 0x10XXXXXX definition reference values (property name registry -- may be embedded in client executable rather than .dat files)
- Purpose of 0x70XXXXXX reference values in type 0x04 arrays

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
- [x] Type 0x02 entry decoder (~60% exact parse, pattern detection fallback)
- [ ] Type 0x01 entry decoder (complex objects with strings)
- [x] Property key census (`dat-registry` command -- empirical statistics)
- [x] Property ID name mapping (0x10XXXXXX definition refs to human-readable names via wiki cross-reference)
- [ ] Nested/recursive property sets

### Game data extraction
- [ ] Items parser (binary tagged format to structured data)
- [ ] Feats parser
- [ ] Enhancements parser
- [ ] Classes parser
- [ ] Races parser
- [ ] JSON export pipeline (`ddo-data extract` command)

### Asset extraction
- [x] DDS texture extraction from client_general.dat
- [x] DDS to PNG conversion (Pillow)
- [x] Icon pipeline (`ddo-data icons` command)

### Supplementary data
- [x] DDO Wiki scraper — items (`ddo-data scrape --type items`)
- [ ] Data merging (game files + wiki data)

### CLI
- [x] `parse`, `list`, `dat-extract`, `dat-peek`, `dat-stats`
- [x] `dat-dump`, `dat-compare`, `dat-survey`, `dat-compare-entries`, `dat-validate`, `dat-probe`, `dat-registry`
- [ ] `extract` (JSON export)
- [x] `icons` (DDS to PNG)
- [x] `dat-namemap` (property key name mapping via wiki cross-reference)
- [x] `scrape` (wiki items; feats/enhancements stubbed)

## Credits

See [README.md](../README.md#credits) for the full list of references and acknowledgments.

Our implementation was independently reverse-engineered from actual DDO game files, with corrections from community LOTRO/DDO tools.
