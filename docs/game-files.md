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

The `.dat` files use Turbine's proprietary archive format (shared with LOTRO). Format reverse-engineered from actual DDO game files.

### Header (0x100 - 0x1A8)

Bytes 0x000-0x0FF are zero padding. All fields little-endian uint32.

| Offset | Field | Notes |
|--------|-------|-------|
| 0x140 | BT magic | Always `0x5442` ("BT" — B-tree marker) |
| 0x144 | Version | `0x200` (gamelogic), `0x400` (english/general) |
| 0x148 | File size | Exact match to actual file size on disk |
| 0x154 | B-tree offset | Points to page index / journal |
| 0x160 | Free list offset | Free block list |
| 0x1A0 | File count | Number of file entries in the archive |
| 0x1A4 | Block size | Always `2460` across all observed files |

### Data Blocks

Every content block in the archive uses this wrapper:

```
[8 zero bytes] [content...]
```

For file content blocks, the content starts with the file ID:

```
00 00 00 00 00 00 00 00  <file_id_le32>  <actual_data...>
```

### File Table

Stored in pages scattered throughout the archive. The first page always starts at offset `0x5F0`.

**Page structure:**

```
[8 zero bytes]                    block header
[uint32 count] [uint32 flags]     page header
[32-byte entry] * N               file entries
```

Known page flags: `0x00030000`, `0x00040000`, `0x00060000`, `0x00080000`, `0x000A0000`, `0x000E0000`.

**32-byte file table entry:**

| Bytes | Type | Field |
|-------|------|-------|
| 0-3 | uint32 | file_id — unique identifier |
| 4-7 | uint32 | data_offset — absolute offset to data block |
| 8-11 | uint32 | size — data size |
| 12-15 | uint32 | (varies — timestamp or hash) |
| 16-19 | uint32 | (varies) |
| 20-23 | uint32 | disk_size — on-disk block size (= size + 8 when uncompressed) |
| 24-27 | uint32 | reserved (always 0) |
| 28-31 | uint32 | flags |

File IDs encode the archive type in their high byte:
- `0x01XXXXXX` — general assets (`client_general.dat`)
- `0x07XXXXXX` — game logic (`client_gamelogic.dat`)
- `0x0AXXXXXX` — localization (`client_local_English.dat`)

### Content Types

| Source file | Content types found |
|-------------|-------------------|
| `client_local_English.dat` | OGG Vorbis audio (voiceovers), UTF-16LE text strings |
| `client_general.dat` | 3D mesh data (vertex/index buffers), DDS textures |
| `client_gamelogic.dat` | Binary tagged format, game rules data |

### Open Questions

- Compression mechanism for entries where `disk_size << size` (zlib didn't work)
- Whether the B-tree journal at 0x154 can be used for faster page discovery
- Multi-block files (entries where data may span multiple blocks)

## Credits

- [DATUnpacker](https://github.com/Middle-earth-Revenge/DATUnpacker) (Middle-earth-Revenge) — C#/.NET reference that identified this as a Turbine B-tree archive format. Our implementation was independently reverse-engineered from actual DDO game files.
