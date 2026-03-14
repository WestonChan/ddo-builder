"""Tests for the Turbine .dat archive parser.

All tests use synthetic .dat files built by the `build_dat` fixture —
no dependency on a DDO installation.
"""

import struct
import pytest
from pathlib import Path

from ddo_data.dat_parser.archive import DatArchive, DatHeader, FileEntry
from ddo_data.dat_parser.extract import scan_file_table, read_entry_data, extract_entry


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


def test_header_info_before_read(tmp_path: Path) -> None:
    """header_info() before read_header() returns a prompt message."""
    dat_path = tmp_path / "x.dat"
    dat_path.write_bytes(b"\x00" * 512)
    archive = DatArchive(dat_path)
    assert "not read yet" in archive.header_info()


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


def test_read_entry_data_id_mismatch(build_dat) -> None:
    """Mismatched embedded file ID raises ValueError."""
    dat_path = build_dat([(0x07000001, b"data")])
    archive = DatArchive(dat_path)
    entries = scan_file_table(archive)
    entry = entries[0x07000001]

    # Craft entry with wrong file_id but same offset
    wrong_entry = FileEntry(
        file_id=0x07FFFFFF,
        data_offset=entry.data_offset,
        size=entry.size,
        disk_size=entry.disk_size,
        flags=entry.flags,
    )
    with pytest.raises(ValueError, match="File ID mismatch"):
        read_entry_data(archive, wrong_entry)


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
