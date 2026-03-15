"""Tests for the ddo-data CLI commands.

Uses Click's CliRunner to invoke commands against synthetic .dat archives.
"""

import struct

from click.testing import CliRunner

from ddo_data.cli import cli
from ddo_data.dat_parser.tagged import hex_dump, scan_tagged_entry

# -- info tests --


def test_info_shows_dat_files(tmp_path) -> None:
    """info command lists .dat files found at the DDO path."""
    (tmp_path / "client_gamelogic.dat").write_bytes(b"\x00" * 100)
    (tmp_path / "client_general.dat").write_bytes(b"\x00" * 200)

    runner = CliRunner()
    result = runner.invoke(cli, ["--ddo-path", str(tmp_path), "info"])

    assert result.exit_code == 0
    assert "2 .dat files" in result.output
    assert "client_gamelogic.dat" in result.output
    assert "client_general.dat" in result.output


def test_info_warns_missing_path(tmp_path) -> None:
    """info command warns when the DDO path doesn't exist."""
    missing = tmp_path / "nonexistent"
    runner = CliRunner()
    result = runner.invoke(cli, ["--ddo-path", str(missing), "info"])

    assert result.exit_code == 0
    assert "WARNING" in result.output


# -- parse tests --


def test_parse_shows_header(build_dat) -> None:
    """parse command displays header info for a .dat archive."""
    dat_path = build_dat([(0x07000001, b"test data")])
    runner = CliRunner()
    result = runner.invoke(cli, ["parse", str(dat_path)])

    assert result.exit_code == 0
    assert "File:" in result.output
    assert "File count:" in result.output
    assert "Block size:" in result.output


# -- list tests --


def test_list_shows_entries(build_dat) -> None:
    """list command displays file entries from the archive."""
    files = [
        (0x07000001, b"alpha"),
        (0x07000002, b"bravo"),
        (0x07000003, b"charlie"),
    ]
    dat_path = build_dat(files)
    runner = CliRunner()
    result = runner.invoke(cli, ["list", str(dat_path)])

    assert result.exit_code == 0
    assert "3 entries" in result.output
    assert "0x07000001" in result.output
    assert "0x07000003" in result.output


def test_list_respects_limit(build_dat) -> None:
    """list command respects the --limit flag."""
    files = [
        (0x07000001, b"alpha"),
        (0x07000002, b"bravo"),
        (0x07000003, b"charlie"),
    ]
    dat_path = build_dat(files)
    runner = CliRunner()
    result = runner.invoke(cli, ["list", str(dat_path), "-n", "1"])

    assert result.exit_code == 0
    assert "showing first 1 of 3" in result.output


# -- dat-extract tests --


def test_dat_extract_single_file(build_dat, tmp_path) -> None:
    """dat-extract extracts a specific file by ID."""
    content = b"Hello, DDO!"
    dat_path = build_dat([(0x07000001, content)])
    output_dir = tmp_path / "extracted"

    runner = CliRunner()
    result = runner.invoke(cli, [
        "dat-extract", str(dat_path),
        "--id", "0x07000001",
        "-o", str(output_dir),
    ])

    assert result.exit_code == 0
    assert "Extracted:" in result.output
    extracted_files = list(output_dir.iterdir())
    assert len(extracted_files) == 1
    assert extracted_files[0].read_bytes() == content


def test_dat_extract_not_found(build_dat, tmp_path) -> None:
    """dat-extract reports when the requested file ID is not in the archive."""
    dat_path = build_dat([(0x07000001, b"data")])
    runner = CliRunner()
    result = runner.invoke(cli, [
        "dat-extract", str(dat_path),
        "--id", "0x07FFFFFF",
        "-o", str(tmp_path / "out"),
    ])

    assert result.exit_code == 0
    assert "not found" in result.output


# -- dat-survey tests --


def test_dat_survey_output(build_dat) -> None:
    """dat-survey produces a survey report with type histogram."""
    files = [
        (0x07000001, struct.pack("<I", 0x00000001) + b"\x00" * 20),
        (0x07000002, struct.pack("<I", 0x00000001) + b"\x00" * 30),
        (0x07000003, struct.pack("<I", 0x00000002) + b"\x00" * 40),
    ]
    dat_path = build_dat(files)
    runner = CliRunner()
    result = runner.invoke(cli, ["dat-survey", str(dat_path)])

    assert result.exit_code == 0
    assert "Entries surveyed:" in result.output
    assert "Size distribution:" in result.output
    assert "type codes" in result.output


def test_dat_survey_with_limit(build_dat) -> None:
    """dat-survey respects --limit flag."""
    files = [
        (0x07000001, b"\x00" * 10),
        (0x07000002, b"\x00" * 10),
        (0x07000003, b"\x00" * 10),
    ]
    dat_path = build_dat(files)
    runner = CliRunner()
    result = runner.invoke(cli, ["dat-survey", str(dat_path), "-n", "2"])

    assert result.exit_code == 0
    assert "Entries surveyed: 2" in result.output


# -- dat-compare-entries tests --


def test_dat_compare_entries_output(build_dat) -> None:
    """dat-compare-entries shows field analysis for matching entries."""
    files = [
        (0x07000001, struct.pack("<III", 1, 0xDEAD, 100)),
        (0x07000002, struct.pack("<III", 1, 0xDEAD, 200)),
    ]
    dat_path = build_dat(files)
    runner = CliRunner()
    result = runner.invoke(cli, ["dat-compare-entries", str(dat_path), "--type", "0x00000001"])

    assert result.exit_code == 0
    assert "2 entries" in result.output
    assert "constant" in result.output


def test_dat_compare_entries_no_matches(build_dat) -> None:
    """dat-compare-entries handles type code with no matches."""
    files = [(0x07000001, struct.pack("<I", 1) + b"\x00" * 8)]
    dat_path = build_dat(files)
    runner = CliRunner()
    result = runner.invoke(cli, ["dat-compare-entries", str(dat_path), "--type", "0xFFFFFFFF"])

    assert result.exit_code == 0
    assert "0 entries" in result.output


# -- dat-peek tests --


def test_dat_peek_shows_hex(build_dat) -> None:
    """dat-peek prints a hex dump with structure annotations."""
    dat_path = build_dat([(0x07000001, b"Hello, World!")])
    runner = CliRunner()
    result = runner.invoke(cli, ["dat-peek", str(dat_path), "--id", "0x07000001"])

    assert result.exit_code == 0
    assert "0x07000001" in result.output
    assert "block hdr + file_id + type" in result.output
    assert "content start" in result.output
    # Should show hex bytes
    assert "48 65 6C 6C 6F" in result.output  # "Hello" in hex


def test_dat_peek_not_found(build_dat) -> None:
    """dat-peek reports when a file ID is not in the archive."""
    dat_path = build_dat([(0x07000001, b"data")])
    runner = CliRunner()
    result = runner.invoke(cli, ["dat-peek", str(dat_path), "--id", "0x07FFFFFF"])

    assert result.exit_code == 0
    assert "not found" in result.output


# -- dat-stats tests --


def test_dat_stats_counts(build_dat) -> None:
    """dat-stats reports correct entry counts and compression stats."""
    files = [
        (0x07000001, b"OggS" + b"\x00" * 50),
        (0x07000002, b"DDS " + b"\x00" * 50),
        (0x07000003, b"<?xml version='1.0'?><r/>"),
    ]
    dat_path = build_dat(files)
    runner = CliRunner()
    result = runner.invoke(cli, ["dat-stats", str(dat_path)])

    assert result.exit_code == 0
    assert "3 entries" in result.output
    assert "Uncompressed:" in result.output
    # All entries are uncompressed in our synthetic archive
    assert "OGG Vorbis" in result.output
    assert "DDS texture" in result.output
    assert "XML" in result.output


# -- dat-dump tests --


def test_dat_dump_output_format(build_dat) -> None:
    """dat-dump shows hex dump with offset/hex/ASCII columns."""
    dat_path = build_dat([(0x07000001, b"ABCDEFGHIJKLMNOP" * 4)])
    runner = CliRunner()
    result = runner.invoke(cli, ["dat-dump", str(dat_path), "--id", "0x07000001"])

    assert result.exit_code == 0
    assert "0x07000001" in result.output
    # Should have hex dump with ASCII sidebar
    assert "41 42 43 44" in result.output  # "ABCD" in hex
    assert "ABCDEFGHIJKLMNOP" in result.output  # ASCII sidebar


# -- dat-probe tests --


def test_dat_probe_type4(build_dat) -> None:
    """dat-probe dispatches to type-4 decoder when DID == 4."""
    # Build a type-4 entry: DID=4, ref_count=0, pad=0, flag=0, prop_count=1,
    # key=0x10000001, value=0
    body = struct.pack("<I", 4)       # DID
    body += b"\x00"                    # ref_count
    body += struct.pack("<I", 0)       # pad
    body += b"\x00"                    # flag
    body += b"\x01"                    # prop_count = 1
    body += struct.pack("<II", 0x10000001, 0)  # key, value
    dat_path = build_dat([(0x07000001, body)])
    runner = CliRunner()
    result = runner.invoke(cli, ["dat-probe", str(dat_path), "--id", "0x07000001"])

    assert result.exit_code == 0
    assert "Type-4" in result.output or "type-4" in result.output or "DID" in result.output
    assert "0x10000001" in result.output


def test_dat_probe_type2_simple(build_dat) -> None:
    """dat-probe dispatches to type-2 decoder for DID=2 entries."""
    # Build a simple type-2 entry: DID=2, ref_count=0, pad=1, flag=0, prop_count=1
    body = struct.pack("<I", 2)       # DID
    body += b"\x00"                    # ref_count
    body += struct.pack("<I", 1)       # pad = 1 (simple variant)
    body += b"\x00"                    # flag
    body += b"\x01"                    # prop_count = 1
    body += struct.pack("<II", 0x10000001, 0)  # key, value
    dat_path = build_dat([(0x07000001, body)])
    runner = CliRunner()
    result = runner.invoke(cli, ["dat-probe", str(dat_path), "--id", "0x07000001"])

    assert result.exit_code == 0
    assert "DID: 2" in result.output
    assert "simple" in result.output
    assert "0x10000001" in result.output


def test_dat_probe_generic(build_dat) -> None:
    """dat-probe uses generic probe for non-type-4 entries."""
    # Build a type-1 entry (DID=1)
    body = struct.pack("<I", 1)       # DID
    body += b"\x00"                    # ref_count
    body += b"\x00" * 20              # some body bytes
    dat_path = build_dat([(0x07000001, body)])
    runner = CliRunner()
    result = runner.invoke(cli, ["dat-probe", str(dat_path), "--id", "0x07000001"])

    assert result.exit_code == 0
    # Generic probe shows "Entry header" or "DID" info
    assert "DID" in result.output or "Entry" in result.output


def test_dat_probe_not_found(build_dat) -> None:
    """dat-probe reports when file ID is not in archive."""
    dat_path = build_dat([(0x07000001, b"data")])
    runner = CliRunner()
    result = runner.invoke(cli, ["dat-probe", str(dat_path), "--id", "0x07FFFFFF"])

    assert result.exit_code == 0
    assert "not found" in result.output


# -- dat-validate tests --


def test_dat_validate_missing_path(tmp_path) -> None:
    """dat-validate reports error when DDO path has no .dat files."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--ddo-path", str(tmp_path), "dat-validate"])

    assert result.exit_code == 0
    assert "ERROR" in result.output
    assert "client_gamelogic.dat not found" in result.output


# -- tagged format tests --


def test_tagged_parse_basic() -> None:
    """Scan a hand-crafted tagged binary blob, verify field extraction."""
    # Build a blob with: a UTF-16LE string + a file ID reference
    blob = bytearray()
    # UTF-16LE string: "Hello" + null terminator = 12 bytes (5*2 + 2)
    for ch in "Hello":
        blob.extend(struct.pack("<H", ord(ch)))
    blob.extend(b"\x00\x00")  # null terminator
    # File ID reference at offset 12 (4-byte aligned: 12 % 4 == 0)
    blob.extend(struct.pack("<I", 0x07001234))

    result = scan_tagged_entry(bytes(blob))
    assert result.raw_size == len(blob)

    # Should find the UTF-16LE string
    assert len(result.strings) == 1
    assert result.strings[0][1] == "Hello"

    # Should find the file ID reference
    assert any(ref_id == 0x07001234 for _, ref_id in result.file_refs)


def test_tagged_scan_empty_data() -> None:
    """scan_tagged_entry handles empty data without error."""
    result = scan_tagged_entry(b"")
    assert result.raw_size == 0
    assert result.strings == []
    assert result.file_refs == []


def test_tagged_scan_short_strings_filtered() -> None:
    """UTF-16LE strings shorter than 3 chars are filtered out."""
    # Build "Hi" in UTF-16LE (only 2 chars) + null terminator
    blob = bytearray()
    for ch in "Hi":
        blob.extend(struct.pack("<H", ord(ch)))
    blob.extend(b"\x00\x00")

    result = scan_tagged_entry(bytes(blob))
    assert result.strings == []  # "Hi" is too short (< 3 chars)


def test_tagged_hex_dump_format() -> None:
    """hex_dump produces offset/hex/ASCII format."""
    data = b"Hello, World!\x00\x01\x02\xff"
    dump = hex_dump(data, offset=0x100)

    assert "00000100" in dump  # offset
    assert "48 65 6C 6C 6F" in dump  # "Hello" hex
    assert "Hello" in dump  # ASCII sidebar
    assert "." in dump  # non-printable replaced with dot


def test_tagged_hex_dump_limit() -> None:
    """hex_dump respects byte limit."""
    data = b"A" * 100
    dump = hex_dump(data, limit=32)

    # Should only have 2 rows (32 bytes / 16 per row)
    lines = [line for line in dump.strip().split("\n") if line.strip()]
    assert len(lines) == 2


# -- dat-compare tests --


def test_dat_compare_output(build_dat_with_btree) -> None:
    """dat-compare runs both scanners and reports results."""
    files = [
        (0x07000001, b"alpha"),
        (0x07000002, b"bravo"),
    ]
    dat_path = build_dat_with_btree(
        btree_nodes=[{"file_ids": [0x07000001, 0x07000002]}],
        files=files,
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["dat-compare", str(dat_path)])

    assert result.exit_code == 0
    assert "Root offset:" in result.output
    assert "brute-force" in result.output.lower() or "Brute" in result.output
    assert "B-tree" in result.output
