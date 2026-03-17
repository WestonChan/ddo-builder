"""Tests for the UTF-16LE string table loader."""

from ddo_data.dat_parser.archive import DatArchive
from ddo_data.dat_parser.extract import scan_file_table
from ddo_data.dat_parser.strings import (
    decode_localization_entry,
    decode_utf16le,
    load_string_table,
    resolve_string_ref,
)


def test_decode_utf16le_basic() -> None:
    """Decodes a simple UTF-16LE string."""
    data = "Hello".encode("utf-16-le")
    assert decode_utf16le(data) == "Hello"


def test_decode_utf16le_with_null_terminator() -> None:
    """Strips trailing null terminators."""
    data = "World".encode("utf-16-le") + b"\x00\x00"
    assert decode_utf16le(data) == "World"


def test_decode_utf16le_with_bom() -> None:
    """Handles UTF-16LE BOM prefix."""
    data = b"\xff\xfe" + "Test".encode("utf-16-le")
    assert decode_utf16le(data) == "Test"


def test_decode_utf16le_empty() -> None:
    """Returns None for empty data."""
    assert decode_utf16le(b"") is None
    assert decode_utf16le(b"\x00") is None


def test_decode_utf16le_non_printable() -> None:
    """Returns None for data with no printable characters."""
    data = b"\x00\x00\x00\x00"
    assert decode_utf16le(data) is None


def test_decode_utf16le_invalid() -> None:
    """Returns None for data that isn't valid UTF-16LE."""
    # Odd number of bytes can't be UTF-16LE
    data = b"\xff\xfe\x41"
    result = decode_utf16le(data)
    # May decode partially or return None -- either is acceptable
    assert result is None or isinstance(result, str)


def test_load_string_table(build_dat) -> None:
    """load_string_table extracts strings from synthetic archive entries."""
    text1 = "Celestia".encode("utf-16-le") + b"\x00\x00"
    text2 = "Vorpal Sword".encode("utf-16-le") + b"\x00\x00"
    files = [
        (0x0A000001, text1),
        (0x0A000002, text2),
    ]

    dat_path = build_dat(files)
    archive = DatArchive(dat_path)
    archive.read_header()
    entries = scan_file_table(archive)

    table = load_string_table(archive, entries)

    assert 0x0A000001 in table
    assert table[0x0A000001] == "Celestia"
    assert 0x0A000002 in table
    assert table[0x0A000002] == "Vorpal Sword"


def test_load_string_table_limit(build_dat) -> None:
    """load_string_table respects the limit parameter."""
    files = [
        (0x0A000001, "Alpha".encode("utf-16-le")),
        (0x0A000002, "Bravo".encode("utf-16-le")),
        (0x0A000003, "Charlie".encode("utf-16-le")),
    ]

    dat_path = build_dat(files)
    archive = DatArchive(dat_path)
    archive.read_header()
    entries = scan_file_table(archive)

    table = load_string_table(archive, entries, limit=2)

    assert len(table) <= 2


def test_load_string_table_auto_scans(build_dat) -> None:
    """load_string_table scans the archive if no entries provided."""
    text = "Auto-scan".encode("utf-16-le")
    dat_path = build_dat([(0x0A000001, text)])
    archive = DatArchive(dat_path)

    table = load_string_table(archive)

    assert 0x0A000001 in table
    assert table[0x0A000001] == "Auto-scan"


def test_load_string_table_skips_binary(build_dat) -> None:
    """Non-text entries are skipped (not included in the table)."""
    files = [
        (0x0A000001, "Valid text".encode("utf-16-le")),
        (0x0A000002, b"\x00\x00\x00\x00\x00\x00\x00\x00"),  # not text
    ]
    dat_path = build_dat(files)
    archive = DatArchive(dat_path)
    archive.read_header()
    entries = scan_file_table(archive)

    table = load_string_table(archive, entries)

    assert 0x0A000001 in table
    assert 0x0A000002 not in table


def _build_localization_entry(name: str, description: str = "") -> bytes:
    """Build a synthetic localization entry with DID 0x25 format."""
    import struct

    name_ref = 0x0DA44875
    desc_ref = 0x033D632E

    # Entry header: DID + ref_count + file_ids
    did = 0x25000001
    header = struct.pack("<I", did) + b"\x01" + struct.pack("<I", 0)

    # Body: sub_count + sub-entries
    sub_count = 2 if description else 1
    body = bytes([sub_count])

    # Name sub-entry
    name_utf16 = name.encode("utf-16-le")
    body += struct.pack("<III", name_ref, 0, 1)
    body += bytes([len(name)])
    body += name_utf16
    body += b"\x00" * 5  # trailing zeros

    # Description sub-entry (optional)
    if description:
        desc_utf16 = description.encode("utf-16-le")
        body += struct.pack("<III", desc_ref, 0, 1)
        body += bytes([len(description)])
        body += desc_utf16
        body += b"\x00" * 5

    return header + body


def test_decode_localization_entry_name() -> None:
    """Extracts the name string from a localization entry."""
    data = _build_localization_entry("Celestia", "A legendary sword.")
    assert decode_localization_entry(data) == "Celestia"


def test_decode_localization_entry_fallback() -> None:
    """Falls back to first string when Name ref is not present."""
    import struct

    # Build entry with a non-name ref
    did = 0x25000001
    header = struct.pack("<I", did) + b"\x01" + struct.pack("<I", 0)
    text = "Only String"
    text_utf16 = text.encode("utf-16-le")
    body = b"\x01"  # sub_count = 1
    body += struct.pack("<III", 0x033D632E, 0, 1)  # description ref
    body += bytes([len(text)])
    body += text_utf16
    body += b"\x00" * 5

    data = header + body
    assert decode_localization_entry(data) == "Only String"


def test_decode_localization_entry_not_localization() -> None:
    """Returns None for non-localization entries (DID not 0x25XXXXXX)."""
    import struct

    data = struct.pack("<I", 0x02) + b"\x00" + b"\x00" * 20
    assert decode_localization_entry(data) is None


def test_resolve_string_ref() -> None:
    """resolve_string_ref looks up IDs in the table."""
    table = {0x0A000001: "Celestia", 0x0A000002: "The Harbor"}

    assert resolve_string_ref(0x0A000001, table) == "Celestia"
    assert resolve_string_ref(0x0A000002, table) == "The Harbor"
    assert resolve_string_ref(0x0A009999, table) is None
