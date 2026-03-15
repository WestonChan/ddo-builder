"""Tests for cross-archive TLV hypothesis validation."""

import struct

from ddo_data.dat_parser.archive import DatArchive
from ddo_data.dat_parser.extract import scan_file_table
from ddo_data.dat_parser.validate import (
    ValidationResult,
    _flat_known_ids,
    build_known_id_set,
    format_validation_result,
    validate_hypothesis,
)


def _build_hyp_a_entry(properties: list[tuple[int, int, bytes]]) -> bytes:
    """Build a binary entry matching hypothesis A: [header:8][prop_id:u32][type:u8][val]...

    properties: list of (prop_id, type_tag, raw_value) tuples.
    """
    buf = bytearray()
    # Header: type_code + field2
    buf.extend(struct.pack("<II", 0x00000001, len(properties)))
    for prop_id, type_tag, raw_value in properties:
        buf.extend(struct.pack("<I", prop_id))
        buf.append(type_tag)
        buf.extend(raw_value)
    return bytes(buf)


def test_validate_hypothesis_scores_refs(build_dat) -> None:
    """Hypothesis that produces valid cross-references scores higher."""
    # Build entry with hypothesis-A layout containing a known cross-reference.
    # The "known" file ID we embed: 0x0A001000
    ref_value = struct.pack("<I", 0x0A001000)
    entry_data = _build_hyp_a_entry([
        (1, 0, struct.pack("<I", 42)),       # int property
        (2, 2, ref_value),                    # string ref (type 2)
        (3, 0, struct.pack("<I", 99)),        # another int
    ])

    dat_path = build_dat([(0x07000001, entry_data)])
    archive = DatArchive(dat_path)
    archive.read_header()
    entries = scan_file_table(archive)

    # known_ids includes the ref we embedded
    known_ids = {0x0A001000, 0x07000001}

    result_a = validate_hypothesis(archive, entries, known_ids, "A")
    validate_hypothesis(archive, entries, known_ids, "B")   # smoke test: ensure B doesn't raise
    validate_hypothesis(archive, entries, known_ids, "C")   # smoke test: ensure C doesn't raise

    # Hypothesis A should find the valid cross-reference
    assert result_a.entries_tested == 1
    assert result_a.entries_parsed == 1
    assert result_a.ref_candidates >= 1
    assert result_a.ref_valid >= 1
    assert result_a.ref_accuracy > 0


def test_validate_hypothesis_coverage(build_dat) -> None:
    """Hypothesis matching the entry layout should have higher coverage."""
    entry_data = _build_hyp_a_entry([
        (1, 0, struct.pack("<I", 100)),
        (2, 0, struct.pack("<I", 200)),
        (3, 0, struct.pack("<I", 300)),
        (4, 1, struct.pack("<f", 1.5)),
    ])

    dat_path = build_dat([(0x07000001, entry_data)])
    archive = DatArchive(dat_path)
    archive.read_header()
    entries = scan_file_table(archive)

    result_a = validate_hypothesis(archive, entries, set(), "A")

    assert result_a.entries_tested == 1
    assert result_a.entries_parsed == 1
    assert result_a.total_properties == 4
    assert result_a.avg_coverage > 0.8


def test_validate_empty_archive(build_dat) -> None:
    """Validation handles entries too small for TLV parsing."""
    dat_path = build_dat([(0x07000001, b"\x00\x00")])
    archive = DatArchive(dat_path)
    archive.read_header()
    entries = scan_file_table(archive)

    result = validate_hypothesis(archive, entries, set(), "A")

    # Entry is only 2 bytes, too small for header
    assert result.entries_tested == 0
    assert result.entries_parsed == 0


def test_validate_sample_size(build_dat) -> None:
    """Sample size limits the number of entries tested."""
    files = [
        (0x07000001 + i, struct.pack("<II", 1, 0) + b"\x00" * 20)
        for i in range(10)
    ]
    dat_path = build_dat(files)
    archive = DatArchive(dat_path)
    archive.read_header()
    entries = scan_file_table(archive)

    result = validate_hypothesis(archive, entries, set(), "A", sample_size=3)

    assert result.entries_tested == 3


def test_validation_result_properties() -> None:
    """ValidationResult computed properties work correctly."""
    r = ValidationResult(
        hypothesis="A",
        entries_tested=10,
        entries_parsed=8,
        ref_candidates=20,
        ref_valid=15,
    )
    assert r.parse_rate == 0.8
    assert r.ref_accuracy == 0.75

    empty = ValidationResult(hypothesis="B")
    assert empty.parse_rate == 0.0
    assert empty.ref_accuracy == 0.0


def test_format_validation_result() -> None:
    """format_validation_result produces readable output."""
    r = ValidationResult(
        hypothesis="A",
        entries_tested=100,
        entries_parsed=90,
        total_properties=500,
        avg_coverage=0.85,
        total_errors=5,
        ref_candidates=50,
        ref_valid=40,
    )
    output = format_validation_result(r)

    assert "Hypothesis A" in output
    assert "90.0%" in output  # parse rate
    assert "85.0%" in output  # coverage
    assert "500" in output    # properties
    assert "80.0%" in output  # ref accuracy


def test_build_known_id_set(tmp_path, build_dat) -> None:
    """build_known_id_set collects IDs from archives in a directory."""
    # Create a fake "gamelogic" archive in a DDO-like directory
    ddo_dir = tmp_path / "ddo"
    ddo_dir.mkdir()

    # We need to create a .dat file named client_gamelogic.dat
    # Use the build_dat helper but copy to the expected location
    dat_path = build_dat([(0x07000001, b"data"), (0x07000002, b"more")])
    import shutil
    shutil.copy(dat_path, ddo_dir / "client_gamelogic.dat")

    known = build_known_id_set(ddo_dir)

    assert 0x07 in known
    assert 0x07000001 in known[0x07]
    assert 0x07000002 in known[0x07]


def test_flat_known_ids() -> None:
    """_flat_known_ids merges all sets into one."""
    known = {
        0x01: {0x01000001, 0x01000002},
        0x0A: {0x0A001000},
    }
    flat = _flat_known_ids(known)

    assert flat == {0x01000001, 0x01000002, 0x0A001000}
