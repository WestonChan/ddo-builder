"""Tests for the property key registry module."""

import json
import struct

from conftest import build_simple_type2_content, build_type4_content

from ddo_data.dat_parser.archive import DatArchive
from ddo_data.dat_parser.extract import scan_file_table
from ddo_data.dat_parser.registry import (
    PropertyKeyInfo,
    RegistryResult,
    build_registry,
    format_registry,
    format_registry_json,
)


# -- build_registry tests --


def test_registry_type4_basic(build_dat) -> None:
    """Type-4 entry with 2 scalar properties is decoded correctly."""
    props = struct.pack("<II", 0x10000001, 0) + struct.pack("<II", 0x10000002, 0)
    content = build_type4_content(2, props)
    dat_path = build_dat([(0x07000001, content)])

    archive = DatArchive(dat_path)
    entries = scan_file_table(archive)
    result = build_registry(archive, entries)

    assert result.total_scanned == 1
    assert result.decoded_type4 == 1
    assert result.decoded_type2 == 0
    assert result.skipped == 0
    assert result.total_properties == 2
    assert 0x10000001 in result.keys
    assert 0x10000002 in result.keys
    assert result.keys[0x10000001].count == 1
    assert result.keys[0x10000001].scalar_count == 1
    assert result.keys[0x10000001].array_count == 0
    assert result.keys[0x10000001].entry_types == {4}


def test_registry_type4_array_property(build_dat) -> None:
    """Type-4 entry with an array property records array statistics."""
    # key=0x10000E79, count=3, then 3 array elements
    props = struct.pack("<II", 0x10000E79, 3)
    props += struct.pack("<III", 0x70000001, 0x70000002, 0x70000003)
    content = build_type4_content(1, props)
    dat_path = build_dat([(0x07000001, content)])

    archive = DatArchive(dat_path)
    entries = scan_file_table(archive)
    result = build_registry(archive, entries)

    assert result.total_properties == 1
    info = result.keys[0x10000E79]
    assert info.array_count == 1
    assert info.scalar_count == 0
    assert info.array_lengths == {3: 1}
    assert info.min_scalar is None


def test_registry_type2_simple(build_dat) -> None:
    """Simple type-2 entry is decoded and counted."""
    props = struct.pack("<II", 0x10000ABC, 0)
    content = build_simple_type2_content(1, props)
    dat_path = build_dat([(0x07000001, content)])

    archive = DatArchive(dat_path)
    entries = scan_file_table(archive)
    result = build_registry(archive, entries)

    assert result.decoded_type2 == 1
    assert result.decoded_type4 == 0
    assert 0x10000ABC in result.keys
    assert result.keys[0x10000ABC].entry_types == {2}


def test_registry_mixed_types(build_dat) -> None:
    """Shared property key across type-4 and type-2 entries merges stats."""
    shared_key = 0x100010B4
    props4 = struct.pack("<II", shared_key, 0)
    content4 = build_type4_content(1, props4)
    props2 = struct.pack("<II", shared_key, 0)
    content2 = build_simple_type2_content(1, props2)
    dat_path = build_dat([
        (0x07000001, content4),
        (0x07000002, content2),
    ])

    archive = DatArchive(dat_path)
    entries = scan_file_table(archive)
    result = build_registry(archive, entries)

    assert result.decoded_type4 == 1
    assert result.decoded_type2 == 1
    info = result.keys[shared_key]
    assert info.count == 2
    assert info.entry_types == {2, 4}


def test_registry_empty_archive(build_dat) -> None:
    """Empty archive produces zeroed result."""
    dat_path = build_dat([])

    archive = DatArchive(dat_path)
    entries = scan_file_table(archive)
    result = build_registry(archive, entries)

    assert result.total_scanned == 0
    assert result.decoded_type4 == 0
    assert result.decoded_type2 == 0
    assert result.skipped == 0
    assert result.keys == {}


def test_registry_non_decodable_skipped(build_dat) -> None:
    """Entry with unsupported DID (type-1) is skipped."""
    # DID=1, ref_count=0, then some body bytes
    content = struct.pack("<I", 1) + b"\x00" + b"\x00" * 20
    dat_path = build_dat([(0x07000001, content)])

    archive = DatArchive(dat_path)
    entries = scan_file_table(archive)
    result = build_registry(archive, entries)

    assert result.total_scanned == 1
    assert result.skipped == 1
    assert result.decoded_type4 == 0
    assert result.decoded_type2 == 0


def test_registry_limit(build_dat) -> None:
    """Limit parameter caps the number of entries scanned."""
    props = struct.pack("<II", 0x10000001, 0)
    content = build_type4_content(1, props)
    dat_path = build_dat([
        (0x07000001, content),
        (0x07000002, content),
        (0x07000003, content),
    ])

    archive = DatArchive(dat_path)
    entries = scan_file_table(archive)
    result = build_registry(archive, entries, limit=1)

    assert result.total_scanned == 1


def test_registry_sample_ids_capped(build_dat) -> None:
    """Sample entry IDs are capped at 5."""
    props = struct.pack("<II", 0x10000001, 0)
    content = build_type4_content(1, props)
    files = [(0x07000000 + i, content) for i in range(1, 11)]
    dat_path = build_dat(files)

    archive = DatArchive(dat_path)
    entries = scan_file_table(archive)
    result = build_registry(archive, entries)

    assert result.keys[0x10000001].count == 10
    assert len(result.keys[0x10000001].sample_entry_ids) == 5


def test_registry_scalar_min_max(build_dat) -> None:
    """Scalar values >= 256 track min/max correctly."""
    # Value >= 256 is treated as a real scalar, not an array count
    props = struct.pack("<II", 0x10000001, 0x00001000)
    content = build_type4_content(1, props)
    dat_path = build_dat([(0x07000001, content)])

    archive = DatArchive(dat_path)
    entries = scan_file_table(archive)
    result = build_registry(archive, entries)

    info = result.keys[0x10000001]
    assert info.scalar_count == 1
    assert info.min_scalar == 0x00001000
    assert info.max_scalar == 0x00001000


# -- format tests --


def test_format_registry_empty_keys() -> None:
    """format_registry with no keys returns summary without table."""
    result = RegistryResult(total_scanned=5, skipped=5)

    output = format_registry(result)

    assert "Property Key Registry" in output
    assert "Unique keys: 0" in output
    assert "Count" not in output  # No table header


def test_format_registry_output() -> None:
    """format_registry produces expected summary text."""
    result = RegistryResult(
        total_scanned=100,
        decoded_type4=60,
        decoded_type2=30,
        skipped=10,
        total_properties=200,
        keys={
            0x10000001: PropertyKeyInfo(
                key=0x10000001,
                count=50,
                entry_types={2, 4},
                scalar_count=40,
                array_count=10,
            ),
        },
    )

    output = format_registry(result)

    assert "Property Key Registry" in output
    assert "100" in output
    assert "type-4: 60" in output
    assert "type-2: 30" in output
    assert "skipped: 10" in output
    assert "0x10000001" in output
    assert "Unique keys: 1" in output


def test_format_registry_json_structure() -> None:
    """format_registry_json returns valid, round-trippable JSON structure."""
    result = RegistryResult(
        total_scanned=10,
        decoded_type4=5,
        decoded_type2=3,
        skipped=2,
        total_properties=20,
        keys={
            0x10000001: PropertyKeyInfo(
                key=0x10000001,
                count=8,
                entry_types={4},
                scalar_count=6,
                array_count=2,
                min_scalar=0,
                max_scalar=100,
                array_lengths={3: 2},
                sample_entry_ids=[0x07000001, 0x07000002],
            ),
        },
    )

    data = format_registry_json(result)

    # Round-trip through JSON serialization
    serialized = json.dumps(data)
    parsed = json.loads(serialized)

    assert parsed["summary"]["total_scanned"] == 10
    assert parsed["summary"]["unique_keys"] == 1
    assert "0x10000001" in parsed["keys"]
    key_data = parsed["keys"]["0x10000001"]
    assert key_data["count"] == 8
    assert key_data["entry_types"] == [4]
    assert key_data["scalar_count"] == 6
    assert key_data["array_count"] == 2
    assert key_data["min_scalar"] == 0
    assert key_data["max_scalar"] == 100
    assert key_data["array_lengths"] == {"3": 2}
    assert len(key_data["sample_entry_ids"]) == 2
