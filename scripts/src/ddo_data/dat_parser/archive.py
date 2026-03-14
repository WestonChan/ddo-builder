"""Read Turbine .dat archive structure (header, file table).

The .dat archive format is a Turbine proprietary format used by DDO and LOTRO.
Format reverse-engineered from actual DDO game files.
See docs/game-files.md for the full format specification.
"""

import struct
from pathlib import Path
from dataclasses import dataclass

# Header constants
_HEADER_START = 0x100  # First 256 bytes are zero padding
_BT_MAGIC = 0x5442  # "BT" marker at 0x140

# Verified header field offsets (all little-endian uint32)
_OFF_BT_MAGIC = 0x140
_OFF_VERSION = 0x144
_OFF_FILE_SIZE = 0x148
_OFF_BTREE_OFFSET = 0x154
_OFF_FREE_LIST = 0x160
_OFF_FILE_COUNT = 0x1A0
_OFF_BLOCK_SIZE = 0x1A4

# File table constants
FILE_TABLE_START = 0x5F0  # First page always starts here (8-byte block header)
FILE_TABLE_ENTRIES_START = 0x600  # Entries begin after the 8+8 byte page header
ENTRY_SIZE = 32  # Each file table entry is 32 bytes


@dataclass
class DatHeader:
    """Header information from a Turbine .dat archive."""

    file_size: int
    version: int
    file_count: int
    block_size: int
    bt_magic: int
    btree_offset: int
    free_list_offset: int


@dataclass
class FileEntry:
    """A single file entry from the archive's file table."""

    file_id: int
    data_offset: int
    size: int  # data size (field at byte 8)
    disk_size: int  # on-disk size including 8-byte block header (field at byte 20)
    flags: int


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
            btree_offset=struct.unpack_from("<I", raw, _OFF_BTREE_OFFSET)[0],
            free_list_offset=struct.unpack_from("<I", raw, _OFF_FREE_LIST)[0],
        )
        return self.header

    def header_info(self) -> str:
        """Return a human-readable summary of the header."""
        if self.header is None:
            return "Header not read yet. Call read_header() first."

        size_mb = self.header.file_size / (1024 * 1024)
        return "\n".join([
            f"File: {self.path.name}",
            f"Size: {size_mb:.1f} MB",
            f"Version: 0x{self.header.version:X}",
            f"File count: {self.header.file_count:,}",
            f"Block size: {self.header.block_size}",
            f"B-tree offset: 0x{self.header.btree_offset:08X}",
        ])
