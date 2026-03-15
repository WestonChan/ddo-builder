"""Scan file tables and extract data from Turbine .dat archives."""

import struct
import typing
from pathlib import Path

from .archive import (
    ENTRY_SIZE,
    FILE_TABLE_ENTRIES_START,
    DatArchive,
    FileEntry,
)
from .decompress import decompress_entry

# Page header flags observed across DDO .dat files
_KNOWN_PAGE_FLAGS = {0x00030000, 0x00040000, 0x00060000, 0x00080000, 0x000A0000, 0x000E0000}

# Block header: 8 zero bytes before every data block and file table page
_BLOCK_HDR_SIZE = 8
_BLOCK_HEADER = b"\x00" * _BLOCK_HDR_SIZE


def _parse_entry(data: bytes, offset: int = 0) -> FileEntry:
    """Parse a single 32-byte file table entry."""
    file_id, data_offset, size, _f12, _f16, disk_size, _reserved, flags = (
        struct.unpack_from("<IIIIIIII", data, offset)
    )
    return FileEntry(
        file_id=file_id,
        data_offset=data_offset,
        size=size,
        disk_size=disk_size,
        flags=flags,
    )


def scan_file_table(archive: DatArchive) -> dict[int, FileEntry]:
    """Scan the archive for all file table entries.

    Finds file table pages by:
    1. Reading the first page at the known fixed offset (0x5F0)
    2. Detecting the expected ID high-byte from the first entries
    3. Scanning forward through the file for additional pages

    Returns a dict mapping file_id -> FileEntry.
    """
    if archive.header is None:
        archive.read_header()

    entries: dict[int, FileEntry] = {}

    with open(archive.path, "rb") as f:
        file_size = archive.header.file_size

        # Read the first page to determine the ID high-byte
        f.seek(FILE_TABLE_ENTRIES_START)
        first_entry_data = f.read(ENTRY_SIZE)
        if len(first_entry_data) < ENTRY_SIZE:
            return entries

        first_id = struct.unpack_from("<I", first_entry_data, 0)[0]
        id_high_byte = (first_id >> 24) & 0xFF
        if id_high_byte == 0:
            return entries

        # Read entries from the first page
        f.seek(FILE_TABLE_ENTRIES_START)
        _read_page_entries(f, entries, id_high_byte, file_size)

        # Scan for additional pages throughout the file
        # Pages are data blocks: [8 zeros][uint32 count][uint32 flags][entries...]
        scan_pos = f.tell()
        # Align to 8-byte boundary
        scan_pos = (scan_pos + 7) & ~7

        chunk_size = 4 * 1024 * 1024  # scan in 4MB chunks
        while scan_pos < file_size:
            f.seek(scan_pos)
            chunk = f.read(chunk_size + 48)  # overlap for boundary
            if not chunk:
                break

            i = 0
            while i < len(chunk) - 48:
                # Look for page header: 8 zeros + count(1-500) + known flags
                if chunk[i : i + 8] != _BLOCK_HEADER:
                    i += 8
                    continue

                count = struct.unpack_from("<I", chunk, i + 8)[0]
                flags = struct.unpack_from("<I", chunk, i + 12)[0]

                if not (1 <= count <= 500 and flags in _KNOWN_PAGE_FLAGS):
                    i += 8
                    continue

                # Check that the first entry after the header has a valid ID
                if i + 16 + ENTRY_SIZE > len(chunk):
                    break
                candidate_id = struct.unpack_from("<I", chunk, i + 16)[0]
                if (candidate_id >> 24) & 0xFF != id_high_byte:
                    i += 8
                    continue

                # Found a page - read its entries
                page_offset = scan_pos + i + 16
                f.seek(page_offset)
                _read_page_entries(f, entries, id_high_byte, file_size)

                # Skip past this page
                i += 16 + count * ENTRY_SIZE
                continue

            scan_pos += chunk_size

    return entries


def _read_page_entries(
    f: typing.BinaryIO,
    entries: dict[int, FileEntry],
    id_high_byte: int,
    file_size: int,
) -> None:
    """Read file table entries from the current file position until they stop."""
    while True:
        data = f.read(ENTRY_SIZE)
        if len(data) < ENTRY_SIZE:
            break

        entry = _parse_entry(data)

        # Stop when we hit an entry that doesn't match our expected ID range
        if (entry.file_id >> 24) & 0xFF != id_high_byte:
            break

        # Basic sanity: data_offset should be within the file
        if entry.data_offset >= file_size:
            continue

        # Keep the entry (last-write wins if duplicate IDs across pages)
        entries[entry.file_id] = entry


def read_entry_data(archive: DatArchive, entry: FileEntry) -> bytes:
    """Read the raw content bytes for a file entry.

    Two data block formats exist (determined by whether the file ID is
    embedded after the block header):

    Version 0x400 (English, general):
        [8-byte block header][file_id:u32][type:u32][content]
        size includes the 8-byte file_id+type prefix.

    Version 0x200 (gamelogic):
        [8-byte block header][content]
        size is the content size directly.
    """
    # Determine how many bytes to read
    read_size = entry.disk_size
    if read_size <= 0:
        read_size = entry.size + 8

    with open(archive.path, "rb") as f:
        f.seek(entry.data_offset)
        block = f.read(read_size)

    if len(block) < 12:
        raise ValueError(
            f"Data block too small at offset 0x{entry.data_offset:08X}: "
            f"{len(block)} bytes"
        )

    # Verify block header (8 zero bytes)
    if block[:8] != _BLOCK_HEADER:
        raise ValueError(
            f"Missing block header at offset 0x{entry.data_offset:08X}"
        )

    # Detect format: check if file_id is embedded at +8
    embedded_id = struct.unpack_from("<I", block, 8)[0]
    has_id_prefix = (embedded_id == entry.file_id)

    if has_id_prefix:
        # Version 0x400 format: [block_hdr][file_id][type][content]
        raw_content = block[16:]
        if entry.is_compressed:
            return decompress_entry(raw_content)
        if entry.size < 8:
            raise ValueError(
                f"Entry size too small ({entry.size}) for 0x{entry.file_id:08X}"
            )
        content_size = entry.size - 8
        return raw_content[:content_size]
    else:
        # Version 0x200 format: [block_hdr][content]
        raw_content = block[8:]
        if entry.is_compressed:
            return decompress_entry(raw_content)
        return raw_content[:entry.size]


def extract_entry(
    archive: DatArchive,
    entry: FileEntry,
    output_dir: Path,
) -> Path:
    """Extract a single file entry to disk.

    Detects the file type from magic bytes and uses an appropriate extension.
    Returns the path to the extracted file.
    """
    content = read_entry_data(archive, entry)

    # Detect file type from magic bytes
    ext = _detect_extension(content)

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{entry.file_id:08X}{ext}"
    out_path.write_bytes(content)
    return out_path


# Content type detection: (magic_bytes, human_name, file_extension)
_MAGIC_TYPES: list[tuple[bytes, str, str]] = [
    (b"OggS", "OGG Vorbis", ".ogg"),
    (b"DDS ", "DDS texture", ".dds"),
    (b"<?xml", "XML", ".xml"),
    (b"RIFF", "RIFF/WAV", ".wav"),
    (b"BM", "BMP image", ".bmp"),
    (b"\xff\xfe", "UTF-16LE text", ".txt"),
]


def identify_content_type(data: bytes) -> str:
    """Identify content type name from the first few magic bytes."""
    if len(data) < 2:
        return "unknown"
    for magic, name, _ in _MAGIC_TYPES:
        if data[: len(magic)] == magic:
            return name
    return f"binary (0x{data[0]:02X}{data[1]:02X})"


def _detect_extension(content: bytes) -> str:
    """Detect file extension from content magic bytes."""
    for magic, _, ext in _MAGIC_TYPES:
        if content[: len(magic)] == magic:
            return ext
    return ".bin"
