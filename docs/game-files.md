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

For file content blocks, the content starts with the file ID and a type field:

```
00 00 00 00 00 00 00 00  <file_id_le32> <type_le32> <actual_data...>
```

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

### Content Types

| Source file | Content types found |
|-------------|-------------------|
| `client_local_English.dat` | OGG Vorbis audio (voiceovers), UTF-16LE text strings |
| `client_general.dat` | 3D mesh data (vertex/index buffers), DDS textures |
| `client_gamelogic.dat` | Binary tagged format, game rules data |

### Binary Tagged Format (gamelogic entries)

Entries in `client_gamelogic.dat` use a binary tagged format for game data (items, feats, enhancements, classes, races). Based on research into LOTRO community tools (same Turbine engine), the format is hypothesized to be a **serialized property set** -- each entry is a bag of typed key-value pairs keyed by numeric property IDs.

**Hypothesis** (from LotroCompanion/lotro-tools):
- Entries begin with a header: `[type_code:u32][field2:u32]`
- Followed by a sequence of TLV (type-length-value) properties
- Properties reference other archives via file ID cross-references (e.g., `0x0AXXXXXX` for localized strings in `client_local_English.dat`, `0x01XXXXXX` for icons in `client_general.dat`)

**Analysis tooling** (in `dat_parser/`):
- `survey.py` -- statistical survey: type code histogram, size distribution, string density
- `tagged.py` -- TLV scanner testing multiple encoding hypotheses (scored by parse coverage)
- `compare.py` -- byte-by-byte comparison of same-type entries to find constant/bounded/variable fields

Use `ddo-data dat-survey`, `ddo-data dat-dump --id <hex>`, and `ddo-data dat-compare-entries --type <hex>` for interactive exploration.

### Open Questions

- Multi-block files (entries where data may span multiple blocks)
- Exact TLV encoding scheme for gamelogic properties (three hypotheses under test)
- Whether 0x144 is "version" (our interpretation) or "block_size" (DATExplorer)
- Exact semantics of unknown fields in B-tree file entries
- Property ID registry (mapping numeric IDs to human-readable names)

## Implementation Status

**Implemented:**
- Header parsing with all known fields (0x140-0x1A4)
- Brute-force file table scanner (flat page detection via 4MB chunk scanning)
- B-tree directory traversal (depth-first walk from root_offset)
- Decompression (4-byte length prefix + zlib, with raw deflate fallback)
- File extraction with magic-byte type detection (OGG, DDS, XML, WAV, BMP)
- Tagged format explorer (UTF-16LE string detection, file ID cross-references)
- Binary format analysis: statistical survey, TLV hypothesis probing, entry comparison
- CLI: `parse`, `list`, `dat-extract`, `dat-peek`, `dat-stats`, `dat-dump`, `dat-compare`, `dat-survey`, `dat-compare-entries`

**Not yet implemented:**
- Full property-set parser (depends on survey/probing findings)
- Property ID registry (mapping numeric IDs to human-readable names)
- Game data parsers (items, feats, enhancements, classes, races)
- Icon extraction (DDS to PNG conversion)
- Wiki scraper (supplementary data from ddowiki.com)
- JSON export pipeline (`ddo-data extract` command)

## Credits

See [README.md](../README.md#credits) for the full list of references and acknowledgments.

Our implementation was independently reverse-engineered from actual DDO game files, with corrections from community LOTRO/DDO tools.
