"""Shared test fixtures for DDO data pipeline tests."""

import struct
import pytest
from pathlib import Path

from ddo_data.dat_parser.archive import (
    ENTRY_SIZE,
    FILE_TABLE_START,
    FILE_TABLE_ENTRIES_START,
)


def _build_dat(
    tmp_path: Path,
    files: list[tuple[int, bytes]],
    *,
    version: int = 0x200,
    block_size: int = 2460,
    extra_pages: list[list[tuple[int, bytes]]] | None = None,
) -> Path:
    """Build a synthetic .dat archive with the given file entries.

    Args:
        tmp_path: Directory to write the .dat file into.
        files: List of (file_id, content_bytes) for the first file table page.
        version: Header version field.
        block_size: Header block_size field.
        extra_pages: Additional file table pages, each a list of (file_id, content_bytes).

    Returns:
        Path to the created .dat file.
    """
    # Layout:
    #   0x000-0x0FF: zero padding
    #   0x100-0x1A7: header
    #   0x5F0:       first file table page (block header + page header + entries)
    #   data blocks: after the file table
    #   extra pages: after data blocks (if any)

    all_files = list(files)
    if extra_pages:
        for page in extra_pages:
            all_files.extend(page)

    # Calculate file table page 1 size
    page1_entries = len(files)
    page1_size = 8 + 8 + page1_entries * ENTRY_SIZE  # block hdr + page hdr + entries

    # Data blocks start right after page 1
    data_start = FILE_TABLE_START + page1_size
    # Align to 8 bytes
    data_start = (data_start + 7) & ~7

    # Compute data block offsets for ALL files
    data_offsets: dict[int, int] = {}
    current_offset = data_start
    for file_id, content in all_files:
        data_offsets[file_id] = current_offset
        # Each data block: 8 zero bytes + 4 byte file_id + 4 byte type + content
        block_len = 8 + 4 + 4 + len(content)
        block_len = (block_len + 7) & ~7  # align
        current_offset += block_len

    # Extra pages go after all data blocks
    extra_page_offsets: list[int] = []
    if extra_pages:
        for page in extra_pages:
            extra_page_offsets.append(current_offset)
            page_size = 8 + 8 + len(page) * ENTRY_SIZE
            page_size = (page_size + 7) & ~7
            current_offset += page_size

    total_size = current_offset

    # Build the file
    buf = bytearray(total_size)

    # Header at 0x100
    struct.pack_into("<I", buf, 0x140, 0x5442)        # BT magic
    struct.pack_into("<I", buf, 0x144, version)         # version
    struct.pack_into("<I", buf, 0x148, total_size)      # file_size
    struct.pack_into("<I", buf, 0x154, 0)               # btree_offset (unused)
    struct.pack_into("<I", buf, 0x160, 0)               # free_list_offset (unused)
    struct.pack_into("<I", buf, 0x1A0, len(all_files))  # file_count
    struct.pack_into("<I", buf, 0x1A4, block_size)      # block_size

    # File table page 1 at 0x5F0
    page1_off = FILE_TABLE_START
    # Block header: 8 zero bytes (already zero)
    # Page header: count + flags
    struct.pack_into("<I", buf, page1_off + 8, page1_entries)
    struct.pack_into("<I", buf, page1_off + 12, 0x00060000)  # known flags value

    entry_off = FILE_TABLE_ENTRIES_START
    for file_id, content in files:
        struct.pack_into(
            "<IIIIIIII", buf, entry_off,
            file_id,
            data_offsets[file_id],
            len(content) + 8,   # size (id + type + content)
            0,                  # field_12
            0,                  # field_16
            8 + 4 + 4 + len(content),  # disk_size (header + id + type + content)
            0,                  # reserved
            0x00000001,         # flags
        )
        entry_off += ENTRY_SIZE

    # Data blocks: [8 zeros][file_id][type_field][content]
    for file_id, content in all_files:
        off = data_offsets[file_id]
        # 8 zero bytes (already zero in buf)
        struct.pack_into("<I", buf, off + 8, file_id)
        struct.pack_into("<I", buf, off + 12, 0)  # type field (0 for tests)
        buf[off + 16 : off + 16 + len(content)] = content

    # Extra file table pages
    if extra_pages:
        for page_idx, page in enumerate(extra_pages):
            page_off = extra_page_offsets[page_idx]
            # Block header: 8 zeros (already zero)
            struct.pack_into("<I", buf, page_off + 8, len(page))
            struct.pack_into("<I", buf, page_off + 12, 0x00060000)

            e_off = page_off + 16
            for file_id, content in page:
                struct.pack_into(
                    "<IIIIIIII", buf, e_off,
                    file_id,
                    data_offsets[file_id],
                    len(content) + 8,
                    0, 0,
                    8 + 4 + 4 + len(content),
                    0,
                    0x00000001,
                )
                e_off += ENTRY_SIZE

    dat_path = tmp_path / "test.dat"
    dat_path.write_bytes(bytes(buf))
    return dat_path


@pytest.fixture
def build_dat(tmp_path: Path):
    """Fixture returning a builder function for synthetic .dat archives."""
    def builder(
        files: list[tuple[int, bytes]],
        **kwargs,
    ) -> Path:
        return _build_dat(tmp_path, files, **kwargs)
    return builder
