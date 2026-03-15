"""Explore and probe the binary tagged format used in client_gamelogic.dat entries.

This module provides both heuristic pattern detection (UTF-16LE strings,
file ID cross-references) and structured TLV (type-length-value) scanning
for reverse-engineering the serialized property set format.

The format is hypothesized to be a serialized property set (based on LOTRO
research via LotroCompanion/lotro-tools) where entries contain typed
properties keyed by numeric IDs. Entry header patterns informed by
jtauber/lotro (James Tauber).
"""

import struct
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Heuristic pattern detection (original exploratory tooling)
# ---------------------------------------------------------------------------


@dataclass
class TaggedStructure:
    """Result of scanning a binary blob for tagged structures."""

    raw_size: int
    strings: list[tuple[int, str]] = field(default_factory=list)  # (offset, text)
    file_refs: list[tuple[int, int]] = field(default_factory=list)  # (offset, file_id)


def scan_tagged_entry(data: bytes) -> TaggedStructure:
    """Scan a binary blob for recognizable structures.

    Detects:
    - UTF-16LE strings (sequences of printable 2-byte chars followed by null terminator)
    - File ID references (uint32 values matching known high-byte patterns)
    - uint32 values at 4-byte-aligned offsets
    """
    result = TaggedStructure(raw_size=len(data))

    # Scan for UTF-16LE strings
    _find_utf16_strings(data, result)

    # Scan for file ID references
    _find_file_refs(data, result)

    return result


# Known file ID high bytes from DDO archives
_KNOWN_ID_HIGH_BYTES = {0x01, 0x07, 0x0A, 0x40, 0x41, 0x78}


def _scan_file_id_refs(data: bytes) -> list[tuple[int, int]]:
    """Yield (offset, value) for uint32s that match known file ID high-byte patterns."""
    refs: list[tuple[int, int]] = []
    for i in range(0, len(data) - 3, 4):
        val = struct.unpack_from("<I", data, i)[0]
        high_byte = (val >> 24) & 0xFF
        if high_byte in _KNOWN_ID_HIGH_BYTES and (val & 0x00FFFFFF) != 0:
            refs.append((i, val))
    return refs


def _find_file_refs(data: bytes, result: TaggedStructure) -> None:
    """Find uint32 values that look like file ID cross-references."""
    result.file_refs.extend(_scan_file_id_refs(data))


def _find_utf16_strings(data: bytes, result: TaggedStructure) -> None:
    """Find UTF-16LE encoded strings (common in DDO game data)."""
    i = 0
    while i < len(data) - 3:
        # Look for sequences of printable UTF-16LE characters
        # (ASCII 0x20-0x7E in the low byte, 0x00 in the high byte)
        if data[i + 1] == 0x00 and 0x20 <= data[i] <= 0x7E:
            start = i
            chars = []
            j = i
            while j < len(data) - 1:
                low, high = data[j], data[j + 1]
                if high == 0x00 and 0x20 <= low <= 0x7E:
                    chars.append(chr(low))
                    j += 2
                elif low == 0x00 and high == 0x00:
                    # Null terminator
                    j += 2
                    break
                else:
                    break

            text = "".join(chars)
            if len(text) >= 3:  # Minimum 3 chars to be interesting
                result.strings.append((start, text))
            i = j
        else:
            i += 1


def hex_dump(data: bytes, offset: int = 0, limit: int = 0) -> str:
    """Format binary data as a hex dump with ASCII sidebar.

    Args:
        data: Bytes to dump.
        offset: Base offset for display (cosmetic, for file-relative addresses).
        limit: Max bytes to show (0 = all).

    Returns:
        Formatted hex dump string.
    """
    if limit > 0:
        data = data[:limit]

    lines = []
    for row_off in range(0, len(data), 16):
        chunk = data[row_off : row_off + 16]
        hex_part = " ".join(f"{b:02X}" for b in chunk)
        ascii_part = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in chunk)
        lines.append(f"  {offset + row_off:08X}  {hex_part:<48s}  {ascii_part}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Structured TLV probing
# ---------------------------------------------------------------------------


@dataclass
class Property:
    """A single property parsed from a TLV scan."""

    id: int
    type_tag: int
    offset: int
    raw_value: bytes

    @property
    def as_uint32(self) -> int | None:
        if len(self.raw_value) == 4:
            return struct.unpack_from("<I", self.raw_value, 0)[0]
        return None

    @property
    def as_float(self) -> float | None:
        if len(self.raw_value) == 4:
            return struct.unpack_from("<f", self.raw_value, 0)[0]
        return None


@dataclass
class EntryHeader:
    """Parsed header from the start of a binary entry."""

    type_code: int  # First uint32 -- likely a type/category identifier
    field2: int  # Second uint32 -- could be property count, size, or version


@dataclass
class TLVResult:
    """Result of scanning an entry with a specific TLV hypothesis."""

    hypothesis: str
    header: EntryHeader | None = None
    properties: list[Property] = field(default_factory=list)
    bytes_parsed: int = 0
    bytes_total: int = 0
    errors: int = 0

    @property
    def coverage(self) -> float:
        """Fraction of bytes successfully parsed (0.0 - 1.0)."""
        if self.bytes_total == 0:
            return 0.0
        return self.bytes_parsed / self.bytes_total


def parse_entry_header(data: bytes) -> EntryHeader | None:
    """Parse the common header from the start of a binary entry.

    Hypothesis: entries begin with [type_code:u32][field2:u32].
    Returns None if data is too short.
    """
    if len(data) < 8:
        return None
    type_code, field2 = struct.unpack_from("<II", data, 0)
    return EntryHeader(type_code=type_code, field2=field2)


def scan_tlv(data: bytes, hypothesis: str = "A") -> TLVResult:
    """Scan binary data using a TLV hypothesis.

    Hypotheses:
        A: [prop_id:u32][type_tag:u8][value:variable]
           - type_tag determines value size: 0-5 = 4 bytes, others = skip
        B: [prop_id:u32][length:u32][value:length bytes]
           - explicit length field
        C: [type_tag:u8][prop_id:u32][value:variable]
           - type tag comes first

    All hypotheses skip the first 8 bytes (treated as entry header).

    Returns TLVResult with parsed properties and coverage score.
    """
    result = TLVResult(hypothesis=hypothesis, bytes_total=len(data))

    # Parse header (first 8 bytes)
    result.header = parse_entry_header(data)
    if result.header is None:
        return result

    pos = 8  # Skip header
    result.bytes_parsed = 8

    if hypothesis == "A":
        pos = _scan_hypothesis_a(data, pos, result)
    elif hypothesis == "B":
        pos = _scan_hypothesis_b(data, pos, result)
    elif hypothesis == "C":
        pos = _scan_hypothesis_c(data, pos, result)

    result.bytes_parsed = pos
    return result


# Type tag -> value size mapping for hypothesis A and C.
# Based on common serialization patterns: small tags = fixed-size values.
_TYPE_VALUE_SIZES = {
    0: 4,   # int32
    1: 4,   # float
    2: 4,   # string ref (uint32 -> English.dat)
    3: 4,   # file ref (uint32 -> archive entry)
    4: 4,   # bool (stored as uint32)
    5: 8,   # int64 or double
}

# Reasonable property ID range -- IDs shouldn't be excessively large
_MAX_REASONABLE_PROP_ID = 0x0000FFFF


def _scan_hypothesis_a(data: bytes, pos: int, result: TLVResult) -> int:
    """Hypothesis A: [prop_id:u32][type_tag:u8][value:variable]."""
    while pos + 5 <= len(data):
        prop_id = struct.unpack_from("<I", data, pos)[0]
        type_tag = data[pos + 4]

        # Sanity check: prop_id should be in a reasonable range
        if prop_id > _MAX_REASONABLE_PROP_ID or prop_id == 0:
            break

        value_size = _TYPE_VALUE_SIZES.get(type_tag)
        if value_size is None:
            result.errors += 1
            break

        value_start = pos + 5
        value_end = value_start + value_size
        if value_end > len(data):
            result.errors += 1
            break

        result.properties.append(Property(
            id=prop_id,
            type_tag=type_tag,
            offset=pos,
            raw_value=data[value_start:value_end],
        ))
        pos = value_end

    return pos


def _scan_hypothesis_b(data: bytes, pos: int, result: TLVResult) -> int:
    """Hypothesis B: [prop_id:u32][length:u32][value:length bytes]."""
    while pos + 8 <= len(data):
        prop_id, length = struct.unpack_from("<II", data, pos)

        if prop_id > _MAX_REASONABLE_PROP_ID or prop_id == 0:
            break
        if length > len(data) - pos - 8 or length > 0x10000:
            result.errors += 1
            break

        value_start = pos + 8
        value_end = value_start + length
        if value_end > len(data):
            result.errors += 1
            break

        result.properties.append(Property(
            id=prop_id,
            type_tag=0,
            offset=pos,
            raw_value=data[value_start:value_end],
        ))
        pos = value_end

    return pos


def _scan_hypothesis_c(data: bytes, pos: int, result: TLVResult) -> int:
    """Hypothesis C: [type_tag:u8][prop_id:u32][value:variable]."""
    while pos + 5 <= len(data):
        type_tag = data[pos]
        prop_id = struct.unpack_from("<I", data, pos + 1)[0]

        if prop_id > _MAX_REASONABLE_PROP_ID or prop_id == 0:
            break

        value_size = _TYPE_VALUE_SIZES.get(type_tag)
        if value_size is None:
            result.errors += 1
            break

        value_start = pos + 5
        value_end = value_start + value_size
        if value_end > len(data):
            result.errors += 1
            break

        result.properties.append(Property(
            id=prop_id,
            type_tag=type_tag,
            offset=pos,
            raw_value=data[value_start:value_end],
        ))
        pos = value_end

    return pos


def scan_all_hypotheses(data: bytes) -> list[TLVResult]:
    """Run all TLV hypotheses and return results sorted by coverage (best first)."""
    results = [scan_tlv(data, h) for h in ("A", "B", "C")]
    results.sort(key=lambda r: (r.coverage, -r.errors), reverse=True)
    return results


def format_tlv_result(result: TLVResult) -> str:
    """Format a TLV scan result as a human-readable report."""
    lines: list[str] = []

    lines.append(f"Hypothesis {result.hypothesis}:  "
                 f"coverage={result.coverage:.1%}  "
                 f"properties={len(result.properties)}  "
                 f"errors={result.errors}")

    if result.header:
        lines.append(f"  Header: type=0x{result.header.type_code:08X}  "
                     f"field2=0x{result.header.field2:08X} ({result.header.field2})")

    for prop in result.properties[:20]:
        val_hex = prop.raw_value.hex()
        val_int = prop.as_uint32
        extra = ""
        if val_int is not None:
            high_byte = (val_int >> 24) & 0xFF
            if high_byte == 0x0A:
                extra = f"  (string ref 0x{val_int:08X})"
            elif high_byte in _KNOWN_ID_HIGH_BYTES:
                extra = f"  (file ref 0x{val_int:08X})"
        lines.append(f"  @0x{prop.offset:04X}  id={prop.id:<6d}  "
                     f"type={prop.type_tag}  val={val_hex}{extra}")

    if len(result.properties) > 20:
        lines.append(f"  ... and {len(result.properties) - 20} more properties")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cross-reference validation
# ---------------------------------------------------------------------------


def validate_file_refs(
    data: bytes,
    known_ids: set[int],
) -> list[tuple[int, int, bool]]:
    """Check uint32 values in data against a set of known file IDs.

    Returns list of (offset, value, is_valid) tuples for each potential
    file ID reference found. A reference is "valid" if it exists in known_ids.
    """
    return [(off, val, val in known_ids) for off, val in _scan_file_id_refs(data)]
