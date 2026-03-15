"""Tests for the Turbine .dat archive parser.

All tests use synthetic .dat files built by the `build_dat` fixture —
no dependency on a DDO installation.
"""

import struct
import zlib
from pathlib import Path

import pytest

from ddo_data.dat_parser.archive import DatArchive, DatHeader, FileEntry
from ddo_data.dat_parser.btree import read_btree_node, traverse_btree
from ddo_data.dat_parser.compare import compare_entries_by_type, format_compare_result
from ddo_data.dat_parser.decompress import decompress_entry
from ddo_data.dat_parser.extract import extract_entry, read_entry_data, scan_file_table
from ddo_data.dat_parser.survey import format_survey, survey_entries
from ddo_data.dat_parser.tagged import (
    format_tlv_result,
    parse_entry_header,
    scan_all_hypotheses,
    scan_tlv,
    validate_file_refs,
)

# -- Header parsing tests --


def test_header_valid(build_dat) -> None:
    """Parse a valid synthetic .dat header."""
    dat_path = build_dat([
        (0x07000001, b"hello"),
        (0x07000002, b"world"),
    ])
    archive = DatArchive(dat_path)
    header = archive.read_header()

    assert isinstance(header, DatHeader)
    assert header.bt_magic == 0x5442
    assert header.file_size == dat_path.stat().st_size
    assert header.file_count == 2
    assert header.block_size == 2460
    assert header.version == 0x200


def test_header_bad_magic(tmp_path: Path) -> None:
    """File with wrong BT magic raises ValueError."""
    buf = bytearray(2048)
    struct.pack_into("<I", buf, 0x140, 0xDEAD)  # wrong magic
    struct.pack_into("<I", buf, 0x148, 2048)     # file size
    dat_path = tmp_path / "bad_magic.dat"
    dat_path.write_bytes(bytes(buf))

    archive = DatArchive(dat_path)
    with pytest.raises(ValueError, match="Missing BT magic"):
        archive.read_header()


def test_header_size_mismatch(tmp_path: Path) -> None:
    """File size != header value raises ValueError."""
    buf = bytearray(2048)
    struct.pack_into("<I", buf, 0x140, 0x5442)   # correct magic
    struct.pack_into("<I", buf, 0x148, 9999)      # wrong size
    dat_path = tmp_path / "bad_size.dat"
    dat_path.write_bytes(bytes(buf))

    archive = DatArchive(dat_path)
    with pytest.raises(ValueError, match="file size mismatch"):
        archive.read_header()


def test_header_too_small(tmp_path: Path) -> None:
    """File too small to contain a header raises ValueError."""
    dat_path = tmp_path / "tiny.dat"
    dat_path.write_bytes(b"\x00" * 100)

    archive = DatArchive(dat_path)
    with pytest.raises(ValueError, match="too small"):
        archive.read_header()


def test_header_info(build_dat) -> None:
    """header_info() returns a human-readable summary."""
    dat_path = build_dat([(0x07000001, b"x" * 100)])
    archive = DatArchive(dat_path)
    archive.read_header()

    info = archive.header_info()
    assert "test.dat" in info
    assert "File count: 1" in info
    assert "Block size: 2460" in info
    assert "Root offset:" in info


def test_header_info_before_read(tmp_path: Path) -> None:
    """header_info() before read_header() returns a prompt message."""
    dat_path = tmp_path / "x.dat"
    dat_path.write_bytes(b"\x00" * 512)
    archive = DatArchive(dat_path)
    assert "not read yet" in archive.header_info()


def test_header_new_fields(build_dat) -> None:
    """New header fields (file_version, free block info) are populated."""
    dat_path = build_dat([(0x07000001, b"test")])
    archive = DatArchive(dat_path)
    header = archive.read_header()

    # These are zero in synthetic archives (build_dat doesn't set them)
    assert header.file_version == 0
    assert header.last_free_block == 0
    assert header.free_block_count == 0
    # Direct field access (no longer aliases)
    assert header.root_offset == 0
    assert header.first_free_block == 0


def test_header_dump_format(build_dat) -> None:
    """header_dump() returns all raw uint32 values with offsets."""
    dat_path = build_dat([(0x07000001, b"test")])
    archive = DatArchive(dat_path)

    dump = archive.header_dump()
    # Should contain the BT magic at 0x140
    assert "0x140:" in dump
    assert "0x00005442" in dump
    # Should contain file_count at 0x1A0
    assert "0x1A0:" in dump
    # Should contain block_size at 0x1A4
    assert "0x1A4:" in dump


# -- File table scanning tests --


def test_scan_single_page(build_dat) -> None:
    """Scan a file table with entries in a single page."""
    files = [
        (0x07000001, b"alpha"),
        (0x07000002, b"bravo"),
        (0x07000003, b"charlie"),
        (0x07000004, b"delta"),
        (0x07000005, b"echo"),
    ]
    dat_path = build_dat(files)
    archive = DatArchive(dat_path)

    entries = scan_file_table(archive)
    assert len(entries) == 5
    for file_id, content in files:
        assert file_id in entries
        assert entries[file_id].size == len(content) + 8  # size includes id + type prefix


def test_scan_multi_page(build_dat) -> None:
    """Scan entries spread across two file table pages."""
    page1 = [
        (0x0A000001, b"page1_a"),
        (0x0A000002, b"page1_b"),
    ]
    page2 = [
        (0x0A000003, b"page2_a"),
        (0x0A000004, b"page2_b"),
        (0x0A000005, b"page2_c"),
    ]
    dat_path = build_dat(page1, extra_pages=[page2])
    archive = DatArchive(dat_path)

    entries = scan_file_table(archive)
    assert len(entries) == 5
    assert 0x0A000001 in entries
    assert 0x0A000005 in entries


def test_scan_empty_archive(build_dat) -> None:
    """Scanning an archive with no entries returns empty dict."""
    dat_path = build_dat([])
    archive = DatArchive(dat_path)
    archive.read_header()

    entries = scan_file_table(archive)
    assert entries == {}


def test_scan_auto_reads_header(build_dat) -> None:
    """scan_file_table reads the header automatically if not already read."""
    dat_path = build_dat([(0x01000001, b"data")])
    archive = DatArchive(dat_path)
    assert archive.header is None

    entries = scan_file_table(archive)
    assert archive.header is not None
    assert len(entries) == 1


# -- Data reading tests --


def test_read_entry_data(build_dat) -> None:
    """Read back content bytes from a file entry."""
    content = b"The quick brown fox jumps over the lazy dog"
    dat_path = build_dat([(0x07001234, content)])
    archive = DatArchive(dat_path)

    entries = scan_file_table(archive)
    data = read_entry_data(archive, entries[0x07001234])
    assert data == content


def test_read_entry_data_binary(build_dat) -> None:
    """Read back binary content with null bytes."""
    content = b"\x00\x01\x02\xff" * 64
    dat_path = build_dat([(0x07000099, content)])
    archive = DatArchive(dat_path)

    entries = scan_file_table(archive)
    data = read_entry_data(archive, entries[0x07000099])
    assert data == content


def test_read_multiple_entries(build_dat) -> None:
    """Read back content from multiple file entries."""
    files = [
        (0x01000001, b"first file content"),
        (0x01000002, b"second file has different data"),
        (0x01000003, b"\x89PNG\r\n\x1a\nfake png data"),
    ]
    dat_path = build_dat(files)
    archive = DatArchive(dat_path)

    entries = scan_file_table(archive)
    for file_id, expected in files:
        actual = read_entry_data(archive, entries[file_id])
        assert actual == expected


def test_read_entry_data_too_small(build_dat) -> None:
    """Reading from a truncated block raises ValueError."""
    dat_path = build_dat([(0x07000001, b"data")])
    archive = DatArchive(dat_path)
    archive.read_header()
    # Craft a fake entry pointing near the end of the file so the read is too small
    bad_entry = FileEntry(
        file_id=0x07000001,
        data_offset=archive.header.file_size - 4,
        size=100,
        disk_size=100,
        flags=0,
    )
    with pytest.raises(ValueError, match="too small"):
        read_entry_data(archive, bad_entry)


def test_read_entry_data_bad_header(build_dat, tmp_path: Path) -> None:
    """Block without 8-zero header raises ValueError."""
    dat_path = build_dat([(0x07000001, b"data")])
    archive = DatArchive(dat_path)
    entries = scan_file_table(archive)
    entry = entries[0x07000001]

    # Corrupt the block header by writing non-zero bytes
    buf = bytearray(dat_path.read_bytes())
    buf[entry.data_offset] = 0xFF
    dat_path.write_bytes(bytes(buf))

    with pytest.raises(ValueError, match="Missing block header"):
        read_entry_data(archive, entry)


def test_read_entry_data_v0200_fallback(build_dat) -> None:
    """When file_id at +8 doesn't match entry, v0x200 path reads from +8."""
    dat_path = build_dat([(0x07000001, b"data")])
    archive = DatArchive(dat_path)
    entries = scan_file_table(archive)
    entry = entries[0x07000001]

    # Craft entry with wrong file_id — auto-detect takes v0x200 path
    # since uint32 at +8 (0x07000001) won't match 0x07FFFFFF
    wrong_entry = FileEntry(
        file_id=0x07FFFFFF,
        data_offset=entry.data_offset,
        size=entry.size,
        disk_size=entry.disk_size,
        flags=entry.flags,
    )
    # v0x200 path: reads entry.size bytes starting at +8
    # Block: [8 zeros][0x07000001:4][0x00000000:4][b"data":4] → 12 bytes from +8
    result = read_entry_data(archive, wrong_entry)
    assert len(result) == entry.size  # 12 bytes
    assert result[8:] == b"data"  # original content at offset +8 within result


# -- Extraction tests --


@pytest.mark.parametrize("content,expected_ext", [
    (b"OggS" + b"\x00" * 100, ".ogg"),
    (b"DDS " + b"\x7c" + b"\x00" * 99, ".dds"),
    (b"<?xml version='1.0'?><root/>", ".xml"),
    (b"RIFF" + b"\x00" * 100, ".wav"),
    (b"BM" + b"\x00" * 100, ".bmp"),
    (b"\xDE\xAD\xBE\xEF" * 10, ".bin"),
    (b"", ".bin"),
])
def test_extract_detects_extension(build_dat, tmp_path: Path, content: bytes, expected_ext: str) -> None:
    """Extract files and verify extension detection from magic bytes."""
    dat_path = build_dat([(0x07000001, content)])
    archive = DatArchive(dat_path)

    entries = scan_file_table(archive)
    out_dir = tmp_path / "output"
    out_path = extract_entry(archive, entries[0x07000001], out_dir)

    assert out_path.suffix == expected_ext
    assert out_path.read_bytes() == content


def test_extract_creates_output_dir(build_dat, tmp_path: Path) -> None:
    """extract_entry creates the output directory if it doesn't exist."""
    dat_path = build_dat([(0x07000001, b"data")])
    archive = DatArchive(dat_path)

    entries = scan_file_table(archive)
    out_dir = tmp_path / "nested" / "deep" / "output"
    assert not out_dir.exists()

    extract_entry(archive, entries[0x07000001], out_dir)
    assert out_dir.exists()


# -- Decompression tests --


def test_decompress_with_length_prefix() -> None:
    """Round-trip: compress content, prepend length prefix, decompress."""
    original = b"The quick brown fox jumps over the lazy dog" * 10
    compressed = zlib.compress(original)
    payload = struct.pack("<I", len(original)) + compressed

    result = decompress_entry(payload)
    assert result == original


def test_decompress_raw_deflate_fallback() -> None:
    """Raw deflate (no zlib header) is decompressed via wbits=-15 fallback."""
    original = b"Hello, DDO world!" * 5
    # compressobj with wbits=-15 produces raw deflate (no zlib header)
    compressor = zlib.compressobj(level=6, wbits=-15)
    raw_deflate = compressor.compress(original) + compressor.flush()
    payload = struct.pack("<I", len(original)) + raw_deflate

    result = decompress_entry(payload)
    assert result == original


def test_decompress_uncompressed_passthrough() -> None:
    """Non-compressed data (that fails zlib) is returned as-is."""
    data = b"\x00\x01\x02\x03\x04\x05\x06\x07"
    result = decompress_entry(data)
    assert result == data


def test_decompress_too_short_passthrough() -> None:
    """Data shorter than 5 bytes is returned as-is (can't have length + payload)."""
    data = b"\x01\x02\x03\x04"
    result = decompress_entry(data)
    assert result == data


def test_is_compressed_heuristic() -> None:
    """FileEntry.is_compressed uses disk_size vs size heuristic."""
    # Uncompressed: disk_size == size + 8 (block header)
    uncompressed = FileEntry(file_id=1, data_offset=0, size=100, disk_size=108, flags=0)
    assert not uncompressed.is_compressed

    # Compressed: disk_size < size + 8
    compressed = FileEntry(file_id=2, data_offset=0, size=100, disk_size=60, flags=0)
    assert compressed.is_compressed

    # Edge case: disk_size == 0 (shouldn't happen but guard against it)
    zero_disk = FileEntry(file_id=3, data_offset=0, size=100, disk_size=0, flags=0)
    assert not zero_disk.is_compressed


def test_read_entry_data_compressed(build_dat) -> None:
    """End-to-end: compressed entry in archive is decompressed by read_entry_data."""
    content = b"Compressed content for DDO testing!" * 20
    dat_path = build_dat(
        [(0x07000001, content)],
        compressed_ids={0x07000001},
    )
    archive = DatArchive(dat_path)

    entries = scan_file_table(archive)
    entry = entries[0x07000001]
    assert entry.is_compressed

    data = read_entry_data(archive, entry)
    assert data == content


def test_read_mixed_compressed_uncompressed(build_dat) -> None:
    """Archive with both compressed and uncompressed entries reads correctly."""
    plain_content = b"I am not compressed"
    compressed_content = b"I am compressed!" * 30

    dat_path = build_dat(
        [
            (0x07000001, plain_content),
            (0x07000002, compressed_content),
        ],
        compressed_ids={0x07000002},
    )
    archive = DatArchive(dat_path)
    entries = scan_file_table(archive)

    assert not entries[0x07000001].is_compressed
    assert entries[0x07000002].is_compressed

    assert read_entry_data(archive, entries[0x07000001]) == plain_content
    assert read_entry_data(archive, entries[0x07000002]) == compressed_content


# -- B-tree traversal tests --


def test_read_btree_single_node(build_dat_with_btree) -> None:
    """Single B-tree node with a few entries, verify all found."""
    files = [
        (0x07000001, b"alpha"),
        (0x07000002, b"bravo"),
        (0x07000003, b"charlie"),
    ]
    dat_path = build_dat_with_btree(
        btree_nodes=[{"file_ids": [0x07000001, 0x07000002, 0x07000003]}],
        files=files,
    )
    archive = DatArchive(dat_path)

    entries = traverse_btree(archive)
    assert len(entries) == 3
    assert 0x07000001 in entries
    assert 0x07000002 in entries
    assert 0x07000003 in entries


def test_read_btree_two_levels(build_dat_with_btree) -> None:
    """Root with two child nodes, verify depth-first finds all entries."""
    files = [
        (0x07000001, b"root_file"),
        (0x07000002, b"child1_file_a"),
        (0x07000003, b"child1_file_b"),
        (0x07000004, b"child2_file"),
    ]
    dat_path = build_dat_with_btree(
        btree_nodes=[
            # Node 0 (root): has one file and two children
            {"file_ids": [0x07000001], "children": [1, 2]},
            # Node 1 (child): has two files
            {"file_ids": [0x07000002, 0x07000003]},
            # Node 2 (child): has one file
            {"file_ids": [0x07000004]},
        ],
        files=files,
    )
    archive = DatArchive(dat_path)

    entries = traverse_btree(archive)
    assert len(entries) == 4
    for fid, _ in files:
        assert fid in entries


def test_btree_sentinel_stops(build_dat_with_btree) -> None:
    """B-tree traversal doesn't follow sentinel (zero) child offsets."""
    files = [
        (0x07000001, b"only_file"),
    ]
    dat_path = build_dat_with_btree(
        btree_nodes=[
            # Root with one file, no children (default — empty children list)
            {"file_ids": [0x07000001]},
        ],
        files=files,
    )
    archive = DatArchive(dat_path)

    entries = traverse_btree(archive)
    assert len(entries) == 1
    assert 0x07000001 in entries


def test_traverse_btree_auto_reads_header(build_dat_with_btree) -> None:
    """traverse_btree reads the header automatically if not already read."""
    files = [(0x07000001, b"auto")]
    dat_path = build_dat_with_btree(
        btree_nodes=[{"file_ids": [0x07000001]}],
        files=files,
    )
    archive = DatArchive(dat_path)
    assert archive.header is None

    entries = traverse_btree(archive)
    assert archive.header is not None
    assert len(entries) == 1


def test_read_btree_node_too_small(tmp_path: Path) -> None:
    """read_btree_node raises ValueError on a truncated node."""
    buf = bytearray(2048)  # big enough for header, but node at end will be truncated
    struct.pack_into("<I", buf, 0x140, 0x5442)
    struct.pack_into("<I", buf, 0x148, len(buf))
    struct.pack_into("<I", buf, 0x1A0, 0)
    struct.pack_into("<I", buf, 0x1A4, 2460)
    dat_path = tmp_path / "small_node.dat"
    dat_path.write_bytes(bytes(buf))

    archive = DatArchive(dat_path)
    with pytest.raises(ValueError, match="too small"):
        read_btree_node(archive, 0)


def test_read_btree_node_bad_header(build_dat_with_btree) -> None:
    """read_btree_node raises ValueError when block header is not 8 zero bytes."""
    files = [(0x07000001, b"data")]
    dat_path = build_dat_with_btree(
        btree_nodes=[{"file_ids": [0x07000001]}],
        files=files,
    )
    archive = DatArchive(dat_path)
    archive.read_header()

    # Corrupt the block header of the B-tree root node
    node_offset = archive.header.root_offset
    raw = bytearray(dat_path.read_bytes())
    raw[node_offset] = 0xFF
    dat_path.write_bytes(bytes(raw))

    with pytest.raises(ValueError, match="Invalid block header"):
        read_btree_node(archive, node_offset)


def test_btree_cycle_detection(build_dat_with_btree) -> None:
    """traverse_btree stops on cycles (child pointing back to parent)."""
    files = [
        (0x07000001, b"root_file"),
        (0x07000002, b"child_file"),
    ]
    dat_path = build_dat_with_btree(
        btree_nodes=[
            # Node 0 (root): has one file and points to child node 1
            {"file_ids": [0x07000001], "children": [1]},
            # Node 1 (child): has one file and points BACK to root (node 0) — cycle!
            {"file_ids": [0x07000002], "children": [0]},
        ],
        files=files,
    )
    archive = DatArchive(dat_path)

    # Should complete without infinite loop, finding both files
    entries = traverse_btree(archive)
    assert len(entries) == 2
    assert 0x07000001 in entries
    assert 0x07000002 in entries


def test_traverse_btree_no_root() -> None:
    """traverse_btree returns empty dict when root_offset is 0."""
    import struct
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        buf = bytearray(2048)
        struct.pack_into("<I", buf, 0x140, 0x5442)  # BT magic
        struct.pack_into("<I", buf, 0x148, 2048)     # file_size
        struct.pack_into("<I", buf, 0x160, 0)        # root_offset = 0
        struct.pack_into("<I", buf, 0x1A0, 0)        # file_count
        struct.pack_into("<I", buf, 0x1A4, 2460)     # block_size
        dat_path = Path(td) / "empty.dat"
        dat_path.write_bytes(bytes(buf))

        archive = DatArchive(dat_path)
        entries = traverse_btree(archive)
        assert entries == {}


# -- Decompression edge case tests --


def test_decompress_size_mismatch_warning() -> None:
    """decompress_entry emits a warning when decompressed size doesn't match prefix."""
    original = b"Hello, World!"
    compressed = zlib.compress(original)
    # Lie about the expected length (say 999 instead of actual length)
    payload = struct.pack("<I", 999) + compressed

    with pytest.warns(UserWarning, match="Decompressed size mismatch"):
        result = decompress_entry(payload)
    assert result == original


# -- identify_content_type tests --


def test_identify_content_type_all_types() -> None:
    """identify_content_type recognizes all known magic byte patterns."""
    from ddo_data.dat_parser.extract import identify_content_type

    assert identify_content_type(b"OggS\x00\x00\x00\x00") == "OGG Vorbis"
    assert identify_content_type(b"DDS \x7c\x00\x00\x00") == "DDS texture"
    assert identify_content_type(b"<?xml version='1.0'?>") == "XML"
    assert identify_content_type(b"RIFF\x00\x00\x00\x00") == "RIFF/WAV"
    assert identify_content_type(b"BM\x00\x00\x00\x00") == "BMP image"
    assert identify_content_type(b"\xff\xfe\x00\x00") == "UTF-16LE text"
    assert identify_content_type(b"\xDE\xAD\xBE\xEF") == "binary (0xDEAD)"
    assert identify_content_type(b"\x01") == "unknown"
    assert identify_content_type(b"") == "unknown"


# -- Survey tests --


def _build_tagged_content(type_code: int, body: bytes) -> bytes:
    """Build a synthetic entry with a type code header + body."""
    return struct.pack("<I", type_code) + body


def test_survey_type_histogram(build_dat) -> None:
    """survey_entries groups entries by their first uint32."""
    files = [
        (0x07000001, _build_tagged_content(0x00000001, b"\x00" * 20)),
        (0x07000002, _build_tagged_content(0x00000001, b"\x00" * 30)),
        (0x07000003, _build_tagged_content(0x00000002, b"\x00" * 40)),
    ]
    dat_path = build_dat(files)
    archive = DatArchive(dat_path)

    result = survey_entries(archive)
    assert result.total_entries == 3
    assert 0x00000001 in result.type_histogram
    assert result.type_histogram[0x00000001].count == 2
    assert 0x00000002 in result.type_histogram
    assert result.type_histogram[0x00000002].count == 1


def test_survey_size_distribution(build_dat) -> None:
    """survey_entries buckets entries by size correctly."""
    files = [
        (0x07000001, b"\x00" * 10),    # tiny (<64)
        (0x07000002, b"\x00" * 100),   # small (64-512)
        (0x07000003, b"\x00" * 1000),  # medium (512-4096)
    ]
    dat_path = build_dat(files)
    archive = DatArchive(dat_path)

    result = survey_entries(archive)
    # Size is in the file entry (content + 8), but the bucket is based on entry.size
    assert result.size_distribution["tiny"] >= 1
    assert result.size_distribution["small"] >= 1
    assert result.size_distribution["medium"] >= 1


def test_survey_limit(build_dat) -> None:
    """survey_entries respects the limit parameter."""
    files = [
        (0x07000001, b"\x00" * 10),
        (0x07000002, b"\x00" * 10),
        (0x07000003, b"\x00" * 10),
    ]
    dat_path = build_dat(files)
    archive = DatArchive(dat_path)

    result = survey_entries(archive, limit=2)
    assert result.total_entries == 2


def test_survey_string_density(build_dat) -> None:
    """survey_entries detects string-heavy entries."""
    # Build an entry that is mostly UTF-16LE text
    text = "Hello World Testing"
    utf16_bytes = text.encode("utf-16-le") + b"\x00\x00"
    files = [
        (0x07000001, utf16_bytes),
    ]
    dat_path = build_dat(files)
    archive = DatArchive(dat_path)

    result = survey_entries(archive)
    # Entry is mostly UTF-16LE text, should not land in "none" density bucket
    assert result.string_density.get("none", 0) == 0


def test_survey_format_output(build_dat) -> None:
    """format_survey produces human-readable output."""
    files = [
        (0x07000001, _build_tagged_content(0x00000001, b"\x00" * 20)),
    ]
    dat_path = build_dat(files)
    archive = DatArchive(dat_path)

    result = survey_entries(archive)
    output = format_survey(result)
    assert "Entries surveyed:" in output
    assert "Size distribution:" in output
    assert "type codes" in output


def test_survey_empty_archive(build_dat) -> None:
    """survey_entries handles an archive with no entries."""
    dat_path = build_dat([])
    archive = DatArchive(dat_path)

    result = survey_entries(archive)
    assert result.total_entries == 0
    assert result.errors == 0
    assert result.type_histogram == {}


# -- TLV scanner tests --


def _build_tlv_a_entry(props: list[tuple[int, int, bytes]]) -> bytes:
    """Build a synthetic entry for hypothesis A: [header][prop_id:u32][type:u8][value]."""
    buf = bytearray()
    # 8-byte header
    buf.extend(struct.pack("<II", 0xAAAA0001, 3))  # type_code, field2
    for prop_id, type_tag, value in props:
        buf.extend(struct.pack("<I", prop_id))
        buf.append(type_tag)
        buf.extend(value)
    return bytes(buf)


def _build_tlv_b_entry(props: list[tuple[int, bytes]]) -> bytes:
    """Build a synthetic entry for hypothesis B: [header][prop_id:u32][len:u32][value]."""
    buf = bytearray()
    buf.extend(struct.pack("<II", 0xBBBB0001, 3))
    for prop_id, value in props:
        buf.extend(struct.pack("<II", prop_id, len(value)))
        buf.extend(value)
    return bytes(buf)


def _build_tlv_c_entry(props: list[tuple[int, int, bytes]]) -> bytes:
    """Build a synthetic entry for hypothesis C: [header][type:u8][prop_id:u32][value]."""
    buf = bytearray()
    buf.extend(struct.pack("<II", 0xCCCC0001, 3))
    for type_tag, prop_id, value in props:
        buf.append(type_tag)
        buf.extend(struct.pack("<I", prop_id))
        buf.extend(value)
    return bytes(buf)


def test_tlv_hypothesis_a() -> None:
    """Hypothesis A parses [prop_id:u32][type:u8][value:4bytes] correctly."""
    data = _build_tlv_a_entry([
        (1, 0, struct.pack("<I", 42)),     # prop 1, type int, value 42
        (2, 0, struct.pack("<I", 100)),    # prop 2, type int, value 100
    ])
    result = scan_tlv(data, "A")

    assert result.header is not None
    assert result.header.type_code == 0xAAAA0001
    assert len(result.properties) == 2
    assert result.properties[0].id == 1
    assert result.properties[0].as_uint32 == 42
    assert result.properties[1].id == 2
    assert result.properties[1].as_uint32 == 100
    assert result.coverage == 1.0
    assert result.errors == 0


def test_property_as_float() -> None:
    """Property.as_float decodes a 4-byte IEEE 754 float value."""
    data = _build_tlv_a_entry([
        (1, 1, struct.pack("<f", 3.14)),  # type 1 = float
    ])
    result = scan_tlv(data, "A")

    assert len(result.properties) == 1
    prop = result.properties[0]
    assert prop.as_float is not None
    assert abs(prop.as_float - 3.14) < 0.001
    # 8-byte values should return None for as_float
    data_8 = _build_tlv_a_entry([(1, 5, b"\x00" * 8)])  # type 5 = 8 bytes
    result_8 = scan_tlv(data_8, "A")
    assert result_8.properties[0].as_float is None


def test_tlv_hypothesis_b() -> None:
    """Hypothesis B parses [prop_id:u32][length:u32][value] correctly."""
    data = _build_tlv_b_entry([
        (10, b"\x01\x02\x03\x04"),
        (20, b"\xAA\xBB"),
    ])
    result = scan_tlv(data, "B")

    assert result.header is not None
    assert len(result.properties) == 2
    assert result.properties[0].id == 10
    assert result.properties[0].raw_value == b"\x01\x02\x03\x04"
    assert result.properties[1].id == 20
    assert result.properties[1].raw_value == b"\xAA\xBB"
    assert result.coverage == 1.0


def test_tlv_hypothesis_c() -> None:
    """Hypothesis C parses [type:u8][prop_id:u32][value] correctly."""
    data = _build_tlv_c_entry([
        (0, 5, struct.pack("<I", 77)),
        (1, 6, struct.pack("<I", 0)),  # type 1 = float-sized
    ])
    result = scan_tlv(data, "C")

    assert result.header is not None
    assert len(result.properties) == 2
    assert result.properties[0].id == 5
    assert result.properties[0].type_tag == 0
    assert result.properties[1].id == 6
    assert result.coverage == 1.0


def test_tlv_stops_on_invalid_prop_id() -> None:
    """TLV scanner stops when prop_id is 0 or too large."""
    # First property is valid, then garbage
    data = _build_tlv_a_entry([(1, 0, struct.pack("<I", 42))])
    data += b"\x00" * 20  # trailing zeros -- prop_id=0 should stop scan
    result = scan_tlv(data, "A")

    assert len(result.properties) == 1
    assert result.coverage < 1.0


def test_tlv_stops_on_unknown_type_tag() -> None:
    """TLV scanner stops on an unrecognized type tag."""
    buf = bytearray()
    buf.extend(struct.pack("<II", 0x00010001, 2))  # header
    buf.extend(struct.pack("<I", 1))  # prop_id = 1
    buf.append(0xFF)  # unknown type tag
    buf.extend(b"\x00" * 4)
    result = scan_tlv(bytes(buf), "A")

    assert len(result.properties) == 0
    assert result.errors == 1


def test_scan_all_hypotheses_ranked() -> None:
    """scan_all_hypotheses returns results sorted by coverage."""
    # Build data for hypothesis A -- only A should parse cleanly
    data = _build_tlv_a_entry([
        (1, 0, struct.pack("<I", 42)),
        (2, 1, struct.pack("<f", 3.14)),
    ])
    results = scan_all_hypotheses(data)

    assert len(results) == 3
    # Best result should have highest coverage
    assert results[0].coverage >= results[1].coverage
    assert results[1].coverage >= results[2].coverage


def test_parse_entry_header() -> None:
    """parse_entry_header extracts the first two uint32s."""
    data = struct.pack("<II", 0x12345678, 42) + b"\x00" * 20
    header = parse_entry_header(data)

    assert header is not None
    assert header.type_code == 0x12345678
    assert header.field2 == 42


def test_parse_entry_header_too_short() -> None:
    """parse_entry_header returns None for data < 8 bytes."""
    assert parse_entry_header(b"\x00\x01\x02\x03") is None


def test_format_tlv_result() -> None:
    """format_tlv_result produces readable output."""
    data = _build_tlv_a_entry([(1, 0, struct.pack("<I", 42))])
    result = scan_tlv(data, "A")
    output = format_tlv_result(result)

    assert "Hypothesis A" in output
    assert "coverage=" in output
    assert "id=1" in output


def test_tlv_detects_file_ref_in_value() -> None:
    """TLV format output annotates values that look like file references."""
    file_ref = struct.pack("<I", 0x07001234)
    data = _build_tlv_a_entry([(1, 3, file_ref)])  # type 3 = file ref
    result = scan_tlv(data, "A")

    assert len(result.properties) == 1
    assert result.properties[0].as_uint32 == 0x07001234
    output = format_tlv_result(result)
    assert "file ref" in output


def test_tlv_annotates_string_ref() -> None:
    """TLV format output labels 0x0A refs as string refs, not file refs."""
    string_ref = struct.pack("<I", 0x0A005678)
    data = _build_tlv_a_entry([(1, 2, string_ref)])  # type 2 = string ref
    result = scan_tlv(data, "A")

    output = format_tlv_result(result)
    assert "string ref" in output
    assert "file ref" not in output


# -- Cross-reference validation tests --


def test_validate_file_refs_with_known_ids() -> None:
    """validate_file_refs marks matching IDs as valid."""
    data = struct.pack("<III", 0x07001234, 0x0A005678, 0x00000042)
    known = {0x07001234}

    results = validate_file_refs(data, known)
    # Should find 0x07001234 (valid) and 0x0A005678 (not in known set)
    valid_refs = [(off, val) for off, val, is_valid in results if is_valid]
    invalid_refs = [(off, val) for off, val, is_valid in results if not is_valid]

    assert len(valid_refs) == 1
    assert valid_refs[0][1] == 0x07001234
    assert len(invalid_refs) >= 1  # 0x0A005678


def test_validate_file_refs_no_matches() -> None:
    """validate_file_refs returns empty for data with no file ID patterns."""
    data = struct.pack("<III", 0x00000001, 0x00000002, 0x00000003)
    results = validate_file_refs(data, set())
    assert results == []


# -- Entry comparison tests --


def test_compare_entries_finds_constant_fields(build_dat) -> None:
    """compare_entries_by_type identifies constant fields across entries."""
    # All entries share type code 0x00000001, with a constant field at offset 4
    files = [
        (0x07000001, struct.pack("<IIII", 1, 0xDEAD, 100, 42)),
        (0x07000002, struct.pack("<IIII", 1, 0xDEAD, 200, 99)),
        (0x07000003, struct.pack("<IIII", 1, 0xDEAD, 300, 7)),
    ]
    dat_path = build_dat(files)
    archive = DatArchive(dat_path)

    result = compare_entries_by_type(archive, 0x00000001)

    assert result.entry_count == 3
    assert result.type_code == 0x00000001

    # Field at offset 0 (type code) should be constant
    assert result.fields[0].category == "constant"
    assert result.fields[0].unique_count == 1

    # Field at offset 4 (0xDEAD) should be constant
    assert result.fields[1].category == "constant"

    # Fields at offset 8 and 12 should be variable
    assert result.fields[2].category != "constant"
    assert result.fields[3].category != "constant"


def test_compare_entries_no_matches(build_dat) -> None:
    """compare_entries_by_type returns empty result for nonexistent type."""
    files = [(0x07000001, struct.pack("<II", 0x00000001, 42))]
    dat_path = build_dat(files)
    archive = DatArchive(dat_path)

    result = compare_entries_by_type(archive, 0xFFFFFFFF)
    assert result.entry_count == 0


def test_compare_entries_bounded_field(build_dat) -> None:
    """compare_entries_by_type identifies bounded (enum-like) fields."""
    # Field at offset 4 has only 3 distinct values = bounded
    files = [
        (0x07000001, struct.pack("<III", 5, 1, 100)),
        (0x07000002, struct.pack("<III", 5, 2, 200)),
        (0x07000003, struct.pack("<III", 5, 3, 300)),
        (0x07000004, struct.pack("<III", 5, 1, 400)),
        (0x07000005, struct.pack("<III", 5, 2, 500)),
    ]
    dat_path = build_dat(files)
    archive = DatArchive(dat_path)

    result = compare_entries_by_type(archive, 5)
    # offset 4 has 3 unique values -> bounded
    assert result.fields[1].category == "bounded"
    assert result.fields[1].unique_count == 3


def test_compare_entries_format_output(build_dat) -> None:
    """format_compare_result produces human-readable output."""
    files = [
        (0x07000001, struct.pack("<II", 1, 42)),
        (0x07000002, struct.pack("<II", 1, 99)),
    ]
    dat_path = build_dat(files)
    archive = DatArchive(dat_path)

    result = compare_entries_by_type(archive, 1)
    output = format_compare_result(result)

    assert "2 entries" in output
    assert "constant" in output
    assert "Fields:" in output
