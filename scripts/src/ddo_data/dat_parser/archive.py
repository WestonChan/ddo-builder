"""Read Turbine .dat archive structure (header, file table).

The .dat archive format is a Turbine proprietary format used by DDO and LOTRO.
Format reverse-engineered from actual DDO game files.
See docs/dat-format.md for the full format specification.
"""

import struct
from dataclasses import dataclass
from pathlib import Path

# Header constants
_HEADER_START = 0x100  # First 256 bytes are zero padding
_BT_MAGIC = 0x5442  # "BT" marker at 0x140

# Header field offsets (all little-endian uint32).
# Fields 0x140-0x160 cross-referenced with DATExplorer (Middle-earth-Revenge).
# Fields 0x1A0-0x1A4 empirically verified against DDO .dat files.
_OFF_BT_MAGIC = 0x140
_OFF_VERSION = 0x144       # DATExplorer calls this "block_size" -- needs verification
_OFF_FILE_SIZE = 0x148
_OFF_FILE_VERSION = 0x14C  # DATExplorer: file_version
_OFF_FIRST_FREE = 0x154    # DATExplorer: first_free_block (we previously called btree_offset)
_OFF_LAST_FREE = 0x158     # DATExplorer: last_free_block
_OFF_FREE_COUNT = 0x15C    # DATExplorer: free_block_count
_OFF_ROOT_OFFSET = 0x160   # DATExplorer: root_offset (B-tree root directory)
_OFF_FILE_COUNT = 0x1A0
_OFF_BLOCK_SIZE = 0x1A4

# Range for header_dump: all uint32 fields from 0x140 to 0x1A4 inclusive
_HEADER_DUMP_START = 0x140
_HEADER_DUMP_END = 0x1A8   # exclusive (last field at 0x1A4 is 4 bytes)

# File table constants
FILE_TABLE_START = 0x5F0  # First page always starts here (8-byte block header)
FILE_TABLE_ENTRIES_START = 0x600  # Entries begin after the 8+8 byte page header
ENTRY_SIZE = 32  # Each file table entry is 32 bytes


@dataclass
class DatHeader:
    """Header information from a Turbine .dat archive.

    Field names follow our empirical analysis, with DATExplorer names noted
    where they differ. See docs/dat-format.md for the full format spec.
    """

    file_size: int
    version: int          # 0x144 — DATExplorer calls this "block_size"
    file_count: int       # 0x1A0
    block_size: int       # 0x1A4
    bt_magic: int         # 0x140
    first_free_block: int  # 0x154 — DATExplorer: first_free_block
    root_offset: int       # 0x160 — DATExplorer: root_offset (B-tree root)
    # Additional fields from DATExplorer research
    file_version: int = 0      # 0x14C
    last_free_block: int = 0   # 0x158
    free_block_count: int = 0  # 0x15C


@dataclass
class FileEntry:
    """A single file entry from the archive's file table."""

    file_id: int
    data_offset: int
    size: int  # data size (field at byte 8)
    disk_size: int  # on-disk size including 8-byte block header (field at byte 20)
    flags: int

    @property
    def is_compressed(self) -> bool:
        """Entry is compressed if disk_size is smaller than expected uncompressed size.

        Uncompressed entries have disk_size == size + 8 (content + block header).
        Compressed entries have a smaller disk_size since the payload is deflated.
        """
        return self.disk_size > 0 and self.disk_size < self.size + 8


class DatArchive:
    """Parser for Turbine .dat archive files used by DDO and LOTRO."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.header: DatHeader | None = None

    def read_header(self) -> DatHeader:
        """Read and parse the .dat file header.

        Raises ValueError if the file is too small or the BT magic is missing.
        """
        actual_size = self.path.stat().st_size

        with open(self.path, "rb") as f:
            raw = f.read(_HEADER_START + 0xB0)  # Read through 0x1A8

        if len(raw) < _OFF_BLOCK_SIZE + 4:
            raise ValueError(f"File too small for a Turbine .dat archive: {len(raw)} bytes")

        bt_magic = struct.unpack_from("<I", raw, _OFF_BT_MAGIC)[0]
        if bt_magic != _BT_MAGIC:
            raise ValueError(
                f"Missing BT magic at 0x140: expected 0x{_BT_MAGIC:04X}, "
                f"got 0x{bt_magic:04X}"
            )

        file_size = struct.unpack_from("<I", raw, _OFF_FILE_SIZE)[0]
        if file_size != actual_size:
            raise ValueError(
                f"Header file size mismatch: header says {file_size}, "
                f"actual is {actual_size}"
            )

        self.header = DatHeader(
            file_size=file_size,
            version=struct.unpack_from("<I", raw, _OFF_VERSION)[0],
            file_count=struct.unpack_from("<I", raw, _OFF_FILE_COUNT)[0],
            block_size=struct.unpack_from("<I", raw, _OFF_BLOCK_SIZE)[0],
            bt_magic=bt_magic,
            first_free_block=struct.unpack_from("<I", raw, _OFF_FIRST_FREE)[0],
            root_offset=struct.unpack_from("<I", raw, _OFF_ROOT_OFFSET)[0],
            file_version=struct.unpack_from("<I", raw, _OFF_FILE_VERSION)[0],
            last_free_block=struct.unpack_from("<I", raw, _OFF_LAST_FREE)[0],
            free_block_count=struct.unpack_from("<I", raw, _OFF_FREE_COUNT)[0],
        )
        return self.header

    def header_info(self) -> str:
        """Return a human-readable summary of the header."""
        if self.header is None:
            return "Header not read yet. Call read_header() first."

        h = self.header
        size_mb = h.file_size / (1024 * 1024)
        return "\n".join([
            f"File: {self.path.name}",
            f"Size: {size_mb:.1f} MB",
            f"Version: 0x{h.version:X}",
            f"File count: {h.file_count:,}",
            f"Block size: {h.block_size}",
            f"Root offset: 0x{h.root_offset:08X}",
            f"First free block: 0x{h.first_free_block:08X}",
            f"Free block count: {h.free_block_count:,}",
        ])

    def header_dump(self) -> str:
        """Dump all raw uint32 header fields from 0x140-0x1A4 for manual verification."""
        with open(self.path, "rb") as f:
            f.seek(_HEADER_DUMP_START)
            raw = f.read(_HEADER_DUMP_END - _HEADER_DUMP_START)

        lines = []
        for i in range(0, len(raw), 4):
            offset = _HEADER_DUMP_START + i
            if i + 4 <= len(raw):
                value = struct.unpack_from("<I", raw, i)[0]
                lines.append(f"  0x{offset:03X}: 0x{value:08X}  ({value:>12,})")
        return "\n".join(lines)
