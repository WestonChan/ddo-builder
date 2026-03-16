"""Shared test fixtures for DDO data pipeline tests."""

import struct
import zlib
from pathlib import Path

import pytest

from ddo_data.dat_parser.archive import (
    ENTRY_SIZE,
    FILE_TABLE_ENTRIES_START,
    FILE_TABLE_START,
)
from ddo_data.dat_parser.btree import (
    _DIR_BLOCK_SIZE,
    _FILE_ENTRY_SIZE,
)
from ddo_data.dat_parser.btree import (
    _NODE_SIZE as _BTREE_NODE_SIZE,
)


def _build_dat(
    tmp_path: Path,
    files: list[tuple[int, bytes]],
    *,
    version: int = 0x200,
    block_size: int = 2460,
    extra_pages: list[list[tuple[int, bytes]]] | None = None,
    compressed_ids: set[int] | None = None,
) -> Path:
    """Build a synthetic .dat archive with the given file entries.

    Args:
        tmp_path: Directory to write the .dat file into.
        files: List of (file_id, content_bytes) for the first file table page.
        version: Header version field.
        block_size: Header block_size field.
        extra_pages: Additional file table pages, each a list of (file_id, content_bytes).
        compressed_ids: Set of file_ids whose content should be stored compressed
            (4-byte LE length prefix + zlib payload).

    Returns:
        Path to the created .dat file.
    """
    # Layout:
    #   0x000-0x0FF: zero padding
    #   0x100-0x1A7: header
    #   0x5F0:       first file table page (block header + page header + entries)
    #   data blocks: after the file table
    #   extra pages: after data blocks (if any)

    if compressed_ids is None:
        compressed_ids = set()

    all_files = list(files)
    if extra_pages:
        for page in extra_pages:
            all_files.extend(page)

    # Pre-compute on-disk payloads (compressed or raw content)
    disk_payloads: dict[int, bytes] = {}
    for file_id, content in all_files:
        if file_id in compressed_ids:
            # Compressed: 4-byte LE decompressed length + zlib data
            compressed = zlib.compress(content)
            disk_payloads[file_id] = struct.pack("<I", len(content)) + compressed
        else:
            disk_payloads[file_id] = content

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
        payload = disk_payloads[file_id]
        # Each data block: 8 zero bytes + 4 byte file_id + 4 byte type + payload
        block_len = 8 + 4 + 4 + len(payload)
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
    struct.pack_into("<I", buf, 0x154, 0)               # first_free_block (unused)
    struct.pack_into("<I", buf, 0x160, 0)               # root_offset (unused)
    struct.pack_into("<I", buf, 0x1A0, len(all_files))  # file_count
    struct.pack_into("<I", buf, 0x1A4, block_size)      # block_size

    def _write_file_table_entry(buf: bytearray, offset: int, file_id: int, content: bytes) -> None:
        """Write a 32-byte file table entry at the given buffer offset."""
        payload = disk_payloads[file_id]
        # size: original content size + 8 (id + type prefix)
        entry_size = len(content) + 8
        # disk_size: block header(8) + id(4) + type(4) + on-disk payload
        disk_size = 8 + 4 + 4 + len(payload)
        struct.pack_into(
            "<IIIIIIII", buf, offset,
            file_id,
            data_offsets[file_id],
            entry_size,
            0,                  # field_12
            0,                  # field_16
            disk_size,
            0,                  # reserved
            0x00000001,         # flags
        )

    # File table page 1 at 0x5F0
    page1_off = FILE_TABLE_START
    # Block header: 8 zero bytes (already zero)
    # Page header: count + flags
    struct.pack_into("<I", buf, page1_off + 8, page1_entries)
    struct.pack_into("<I", buf, page1_off + 12, 0x00060000)  # known flags value

    entry_off = FILE_TABLE_ENTRIES_START
    for file_id, content in files:
        _write_file_table_entry(buf, entry_off, file_id, content)
        entry_off += ENTRY_SIZE

    # Data blocks: [8 zeros][file_id][type_field][payload]
    for file_id, _content in all_files:
        off = data_offsets[file_id]
        payload = disk_payloads[file_id]
        # 8 zero bytes (already zero in buf)
        struct.pack_into("<I", buf, off + 8, file_id)
        struct.pack_into("<I", buf, off + 12, 0)  # type field (0 for tests)
        buf[off + 16 : off + 16 + len(payload)] = payload

    # Extra file table pages
    if extra_pages:
        for page_idx, page in enumerate(extra_pages):
            page_off = extra_page_offsets[page_idx]
            # Block header: 8 zeros (already zero)
            struct.pack_into("<I", buf, page_off + 8, len(page))
            struct.pack_into("<I", buf, page_off + 12, 0x00060000)

            e_off = page_off + 16
            for file_id, content in page:
                _write_file_table_entry(buf, e_off, file_id, content)
                e_off += ENTRY_SIZE

    dat_path = tmp_path / "test.dat"
    dat_path.write_bytes(bytes(buf))
    return dat_path


def _build_btree_node(
    buf: bytearray,
    node_offset: int,
    file_entries: list[tuple[int, int, int, int]],
    child_offsets: list[int] | None = None,
) -> None:
    """Write a B-tree node at the given buffer offset.

    file_entries: list of (file_id, data_offset, size, disk_size) tuples.
    child_offsets: list of child node offsets (up to 62).
    """
    # Block header: 8 zero bytes (already zero in buf)

    # Directory block: child slots
    dir_start = node_offset + 8
    if child_offsets:
        for i, child_off in enumerate(child_offsets):
            slot_off = dir_start + i * 8
            struct.pack_into("<II", buf, slot_off, 0, child_off)

    # File block: entries in DATExplorer order
    # (unknown1, file_type, file_id, file_offset, size1, timestamp, unknown2, size2)
    file_start = node_offset + 8 + _DIR_BLOCK_SIZE
    for i, (file_id, data_offset, size, disk_size) in enumerate(file_entries):
        entry_off = file_start + i * _FILE_ENTRY_SIZE
        struct.pack_into(
            "<IIIIIIII", buf, entry_off,
            0,             # unknown1
            0x00000001,    # file_type (flags)
            file_id,
            data_offset,
            size,
            0,             # timestamp
            0,             # unknown2
            disk_size,
        )


def _build_dat_with_btree(
    tmp_path: Path,
    btree_nodes: list[dict],
    files: list[tuple[int, bytes]],
) -> Path:
    """Build a synthetic .dat archive with a B-tree directory structure.

    Args:
        tmp_path: Directory to write the .dat file into.
        btree_nodes: List of node dicts, each with:
            - "file_ids": list of file_ids in this node
            - "children": list of indices into btree_nodes (optional)
            The first node (index 0) is the root.
        files: List of (file_id, content_bytes) — the actual data.

    Returns:
        Path to the created .dat file.
    """
    # Layout:
    #   0x000-0x0FF: zero padding
    #   0x100-0x1A7: header
    #   0x5F0:       flat file table page (empty, 0 entries) — keeps scanner happy
    #   data blocks: after empty page
    #   B-tree nodes: after data blocks

    # Empty file table page (no entries for brute-force scanner)
    page1_size = 8 + 8  # block header + page header with count=0
    data_start = FILE_TABLE_START + page1_size
    data_start = (data_start + 7) & ~7

    # Compute data block offsets
    data_offsets: dict[int, int] = {}
    current_offset = data_start
    for file_id, content in files:
        data_offsets[file_id] = current_offset
        block_len = 8 + 4 + 4 + len(content)
        block_len = (block_len + 7) & ~7
        current_offset += block_len

    # Compute B-tree node offsets
    node_offsets: list[int] = []
    for _ in btree_nodes:
        node_offsets.append(current_offset)
        current_offset += (_BTREE_NODE_SIZE + 7) & ~7

    total_size = current_offset
    buf = bytearray(total_size)

    # Header
    struct.pack_into("<I", buf, 0x140, 0x5442)          # BT magic
    struct.pack_into("<I", buf, 0x144, 0x200)            # version
    struct.pack_into("<I", buf, 0x148, total_size)       # file_size
    struct.pack_into("<I", buf, 0x160, node_offsets[0])  # root_offset
    struct.pack_into("<I", buf, 0x1A0, len(files))       # file_count
    struct.pack_into("<I", buf, 0x1A4, 2460)             # block_size

    # Empty file table page at 0x5F0
    struct.pack_into("<I", buf, FILE_TABLE_START + 8, 0)           # count = 0
    struct.pack_into("<I", buf, FILE_TABLE_START + 12, 0x00060000) # flags

    # Data blocks
    file_content_map: dict[int, bytes] = dict(files)
    for file_id, content in files:
        off = data_offsets[file_id]
        struct.pack_into("<I", buf, off + 8, file_id)
        struct.pack_into("<I", buf, off + 12, 0)
        buf[off + 16 : off + 16 + len(content)] = content

    # B-tree nodes
    for node_idx, node_def in enumerate(btree_nodes):
        node_off = node_offsets[node_idx]
        node_file_ids = node_def.get("file_ids", [])

        # Build file entry tuples: (file_id, data_offset, size, disk_size)
        file_entries = []
        for fid in node_file_ids:
            content = file_content_map[fid]
            file_entries.append((
                fid,
                data_offsets[fid],
                len(content) + 8,                    # size (includes id+type prefix)
                8 + 4 + 4 + len(content),            # disk_size
            ))

        # Resolve child offsets
        children = node_def.get("children", [])
        child_offsets = [node_offsets[ci] for ci in children]

        _build_btree_node(buf, node_off, file_entries, child_offsets)

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


@pytest.fixture
def build_dat_with_btree(tmp_path: Path):
    """Fixture returning a builder function for synthetic archives with B-tree structure."""
    def builder(
        btree_nodes: list[dict],
        files: list[tuple[int, bytes]],
    ) -> Path:
        return _build_dat_with_btree(tmp_path, btree_nodes, files)
    return builder


def build_type4_content(prop_count: int, props_data: bytes) -> bytes:
    """Build raw bytes for a type-4 entry body.

    Layout: [DID=4:u32][ref_count=0:u8][pad=0:u32][flag=0:u8][count:u8][props]
    """
    buf = struct.pack("<I", 4)  # DID=4
    buf += b"\x00"  # ref_count=0
    buf += struct.pack("<I", 0)  # pad=0
    buf += b"\x00"  # flag=0
    buf += bytes([prop_count])
    buf += props_data
    return buf


def build_simple_type2_content(prop_count: int, props_data: bytes) -> bytes:
    """Build raw bytes for a simple type-2 entry body (pad=1).

    Layout: [DID=2:u32][ref_count=0:u8][pad=1:u32][flag=0:u8][count:u8][props]
    """
    buf = struct.pack("<I", 2)  # DID=2
    buf += b"\x00"  # ref_count=0
    buf += struct.pack("<I", 1)  # pad=1
    buf += b"\x00"  # flag=0
    buf += bytes([prop_count])
    buf += props_data
    return buf


def build_dds_1x1_rgba() -> bytes:
    """Build a minimal 1x1 RGBA uncompressed DDS file (132 bytes).

    DDS format: 4-byte magic + 124-byte header + 4 bytes pixel data (BGRA).
    Usable by Pillow for DDS-to-PNG conversion tests.
    """
    buf = bytearray(b"DDS ")
    header = bytearray(124)
    struct.pack_into("<I", header, 0, 124)          # dwSize
    struct.pack_into("<I", header, 4, 0x1007)       # dwFlags (CAPS|HEIGHT|WIDTH|PIXELFORMAT)
    struct.pack_into("<I", header, 8, 1)            # dwHeight
    struct.pack_into("<I", header, 12, 1)           # dwWidth
    struct.pack_into("<I", header, 16, 4)           # dwPitchOrLinearSize
    pf_off = 72  # DDS_PIXELFORMAT offset within header
    struct.pack_into("<I", header, pf_off, 32)          # pixelformat dwSize
    struct.pack_into("<I", header, pf_off + 4, 0x41)    # DDPF_RGB | DDPF_ALPHAPIXELS
    struct.pack_into("<I", header, pf_off + 12, 32)     # dwRGBBitCount
    struct.pack_into("<I", header, pf_off + 16, 0x00FF0000)  # dwRBitMask
    struct.pack_into("<I", header, pf_off + 20, 0x0000FF00)  # dwGBitMask
    struct.pack_into("<I", header, pf_off + 24, 0x000000FF)  # dwBBitMask
    struct.pack_into("<I", header, pf_off + 28, 0xFF000000)  # dwABitMask
    struct.pack_into("<I", header, 104, 0x1000)     # DDSCAPS_TEXTURE
    buf.extend(header)
    buf.extend(b"\xFF\x00\x00\xFF")                 # 1 pixel BGRA
    return bytes(buf)
