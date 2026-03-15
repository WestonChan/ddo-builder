"""Data-driven binary format probe for DDO gamelogic entries.

Implements bottom-up pattern detection and the Turbine property encoding
primitives (VLE, tsize, property streams) discovered from LOTRO community
tools (lulrai/bot-client, based on LotroCompanion/lotro-tools).

DDO entry layout (empirically confirmed):
    [DID:u32] [ref_count:u8] [ref_count x file_id:u32] [property_data...]

The property data uses Turbine's serialized property set format with
variable-length encoded integers and typed values.
"""

import io
import struct
from collections.abc import Callable
from dataclasses import dataclass, field

from .tagged import _KNOWN_ID_HIGH_BYTES

# ---------------------------------------------------------------------------
# VLE (Variable-Length Encoding) primitives — from Turbine engine
# ---------------------------------------------------------------------------


def read_vle(ins: io.BytesIO) -> int:
    """Read a variable-length encoded integer.

    Encoding:
        - If high bit clear (< 0x80): value is the byte itself (0-127)
        - If byte == 0xE0: followed by a full uint32 LE
        - If byte has 0xC0 set: 4-byte value from 3 more bytes
        - Otherwise (0x80 set, 0x40 clear): 2-byte value
    """
    lead_raw = ins.read(1)
    if len(lead_raw) == 0:
        raise ValueError("Unexpected end of stream in VLE")
    lead_byte = lead_raw[0]

    if lead_byte & 0x80 == 0:
        return lead_byte

    if lead_byte == 0xE0:
        raw = ins.read(4)
        if len(raw) < 4:
            raise ValueError("Unexpected end of stream in VLE uint32")
        return struct.unpack("<I", raw)[0]

    second_raw = ins.read(1)
    if len(second_raw) == 0:
        raise ValueError("Unexpected end of stream in VLE byte 2")
    second_byte = second_raw[0]

    if lead_byte & 0x40:
        raw = ins.read(2)
        if len(raw) < 2:
            raise ValueError("Unexpected end of stream in VLE uint16")
        low_word = struct.unpack("<H", raw)[0]
        return (lead_byte & 0x3F) << 24 | second_byte << 16 | low_word

    return second_byte | ((lead_byte & 0x7F) << 8)


def read_tsize(ins: io.BytesIO) -> int:
    """Read a Turbine 'tsize' — skip 1 byte, then read VLE."""
    skip_byte = ins.read(1)
    if len(skip_byte) == 0:
        raise ValueError("Unexpected end of stream in tsize")
    return read_vle(ins)


def read_uint32(ins: io.BytesIO) -> int:
    """Read a little-endian uint32."""
    raw = ins.read(4)
    if len(raw) < 4:
        raise ValueError("Unexpected end of stream reading uint32")
    return struct.unpack("<I", raw)[0]


def read_uint8(ins: io.BytesIO) -> int:
    """Read a single byte."""
    raw = ins.read(1)
    if len(raw) == 0:
        raise ValueError("Unexpected end of stream reading uint8")
    return raw[0]


def read_pascal_string(ins: io.BytesIO) -> str:
    """Read a VLE-length-prefixed Latin-1 string."""
    length = read_vle(ins)
    raw = ins.read(length)
    if len(raw) < length:
        raise ValueError(f"String truncated: expected {length}, got {len(raw)}")
    return raw.decode("latin-1")


# ---------------------------------------------------------------------------
# Known file ID high bytes
# ---------------------------------------------------------------------------

_FILE_ID_LABELS = {0x01: "general", 0x07: "gamelogic", 0x0A: "English"}

# Empirical threshold: values 1-255 in the "val" slot of a greedy pair are
# treated as array counts.  Real scalar property values are either 0 (flag)
# or large (file IDs, def refs, bitfields), so 256 cleanly separates them.
_MAX_ARRAY_COUNT = 256


def _is_file_id(value: int) -> bool:
    """Check if a uint32 looks like a cross-archive file ID."""
    high = (value >> 24) & 0xFF
    return high in _KNOWN_ID_HIGH_BYTES and (value & 0x00FFFFFF) != 0


# ---------------------------------------------------------------------------
# Probe result types
# ---------------------------------------------------------------------------


@dataclass
class GameEntryHeader:
    """Parsed DDO entry header: DID + file ID reference list."""

    did: int
    """Data definition ID (entry type/class)."""

    ref_count: int
    """Number of file ID references following the DID."""

    file_ids: list[int] = field(default_factory=list)
    """Cross-reference file IDs (0x07XXXXXX gamelogic refs)."""

    body_offset: int = 0
    """Byte offset where the property data starts."""


@dataclass
class ProbeResult:
    """Result of probing a binary entry's structure."""

    header: GameEntryHeader
    raw_size: int

    # Pattern detection results
    def_refs: list[tuple[int, int]] = field(default_factory=list)
    """(offset, value) for 0x10XXXXXX definition references."""

    ascii_strings: list[tuple[int, str]] = field(default_factory=list)
    """(offset, text) for length-prefixed ASCII strings."""

    file_id_refs: list[tuple[int, int]] = field(default_factory=list)
    """(offset, value) for cross-archive file ID references in body."""

    float_values: list[tuple[int, float]] = field(default_factory=list)
    """(offset, value) for IEEE 754 LE float values (non-trivial)."""

    parse_coverage: float = 0.0
    """Fraction of body bytes successfully accounted for."""


# ---------------------------------------------------------------------------
# Entry header parsing
# ---------------------------------------------------------------------------


def parse_entry_header(data: bytes) -> GameEntryHeader:
    """Parse the DDO entry header: [DID:u32][ref_count:u8][file_ids...].

    The ref_count byte at position 4 indicates how many uint32 file ID
    references follow. This pattern has been empirically confirmed across
    all three major entry types (DID 1, 2, and 4).
    """
    if len(data) < 5:
        raise ValueError(f"Entry too short ({len(data)} bytes) for header")

    did = struct.unpack_from("<I", data, 0)[0]
    ref_count = data[4]

    file_ids = []
    offset = 5
    for _ in range(ref_count):
        if offset + 4 > len(data):
            break
        fid = struct.unpack_from("<I", data, offset)[0]
        file_ids.append(fid)
        offset += 4

    return GameEntryHeader(
        did=did,
        ref_count=len(file_ids),
        file_ids=file_ids,
        body_offset=offset,
    )


# ---------------------------------------------------------------------------
# Pattern detectors
# ---------------------------------------------------------------------------


def _scan_uint32_pattern(
    data: bytes,
    start: int,
    predicate: Callable[[int], bool],
) -> list[tuple[int, int]]:
    """Scan for uint32 LE values matching a predicate across all 4 alignments.

    Tries alignments 0-3 from start, deduplicates by offset, and returns
    sorted results.
    """
    hits: dict[int, int] = {}
    for align in range(4):
        offset = start + align
        for i in range(offset, len(data) - 3, 4):
            val = struct.unpack_from("<I", data, i)[0]
            if predicate(val) and i not in hits:
                hits[i] = val
    return sorted(hits.items())


def find_definition_refs(data: bytes, start: int = 0) -> list[tuple[int, int]]:
    """Find uint32 values matching the 0x10XXXXXX definition reference pattern.

    These appear throughout DDO gamelogic entries and likely reference
    schema/class definitions within the Turbine engine. Scans all 4
    possible alignments from start to avoid missing unaligned values.
    """
    return _scan_uint32_pattern(
        data, start,
        lambda v: (v >> 24) & 0xFF == 0x10 and (v & 0x00FFFFFF) != 0,
    )


def find_file_id_refs(data: bytes, start: int = 0) -> list[tuple[int, int]]:
    """Find uint32 values that look like cross-archive file ID references.

    Scans all 4 possible alignments from start.
    """
    return _scan_uint32_pattern(data, start, _is_file_id)


def find_length_prefixed_strings(
    data: bytes, start: int = 0
) -> list[tuple[int, str]]:
    """Detect byte-length-prefixed ASCII strings in binary data.

    Looks for a byte N (4 <= N <= 200) followed by N printable ASCII bytes.
    """
    strings = []
    i = start
    while i < len(data) - 4:
        length = data[i]
        if 4 <= length <= 200 and i + 1 + length <= len(data):
            candidate = data[i + 1 : i + 1 + length]
            if all(0x20 <= b < 0x7F for b in candidate):
                strings.append((i, candidate.decode("ascii")))
                i += 1 + length
                continue
        i += 1
    return strings


def find_float_values(
    data: bytes, start: int = 0
) -> list[tuple[int, float]]:
    """Find IEEE 754 LE float values that look meaningful (not 0/NaN/inf).

    Only reports floats with absolute value between 1e-6 and 1e6,
    which covers typical game stats (damage, speed, level, etc.).
    Scans at every byte position for alignment-independent detection.
    """
    floats = []
    i = start
    while i <= len(data) - 4:
        val = struct.unpack_from("<f", data, i)[0]
        abs_val = abs(val)
        if 1e-6 < abs_val < 1e6 and val == val:  # excludes NaN
            floats.append((i, val))
            i += 4  # skip past this match
            continue
        i += 1
    return floats


# ---------------------------------------------------------------------------
# Type-4 entry decoder
# ---------------------------------------------------------------------------


@dataclass
class DecodedProperty:
    """A decoded property from a type-4 entry."""

    key: int
    """Property key — definition ref (0x10XXXXXX) or small integer."""

    value: int | list[int]
    """Scalar uint32 (always 0 for simple props) or list of uint32 array elements."""

    @property
    def is_array(self) -> bool:
        return isinstance(self.value, list)


@dataclass
class Type4Entry:
    """Fully decoded type-4 entry."""

    header: GameEntryHeader
    raw_size: int
    properties: list[DecodedProperty] = field(default_factory=list)
    remaining_bytes: int = 0
    """Bytes left unparsed after the property stream."""


def _try_greedy_pairs(
    body: bytes, start: int, count: int,
) -> tuple[list[DecodedProperty], int] | None:
    """Try reading count greedy [key:u32][val:u32] pairs from body[start:].

    When val > 0 and val < 256, treats it as an array count and reads
    val additional uint32 elements.  Returns (properties, remaining_bytes)
    or None if the body is too short to read all pairs.
    """
    pos = start
    properties: list[DecodedProperty] = []
    for _ in range(count):
        if pos + 8 > len(body):
            return None
        key = struct.unpack_from("<I", body, pos)[0]
        val = struct.unpack_from("<I", body, pos + 4)[0]
        pos += 8

        if 0 < val < _MAX_ARRAY_COUNT and pos + val * 4 <= len(body):
            elements = []
            for _ in range(val):
                elements.append(struct.unpack_from("<I", body, pos)[0])
                pos += 4
            properties.append(DecodedProperty(key=key, value=elements))
        else:
            properties.append(DecodedProperty(key=key, value=val))

    return properties, len(body) - pos


def decode_type4(data: bytes) -> Type4Entry:
    """Decode a type-4 entry: [DID:u32][ref_count:u8][file_ids...][body].

    Body layout: [pad:u32=0][flag:u8][prop_count:u8][properties...]

    Each property is [key:u32][value:u32]. If value > 0 and value < 256,
    it's an array count followed by that many uint32 elements.

    Achieves 99.7% parse rate across all 709 type-4 entries in DDO gamelogic.
    """
    header = parse_entry_header(data)
    body = data[header.body_offset:]
    result = Type4Entry(header=header, raw_size=len(data))

    if len(body) < 6:
        result.remaining_bytes = len(body)
        return result

    prop_count = body[5]
    parsed = _try_greedy_pairs(body, 6, prop_count)
    if parsed is not None:
        result.properties, result.remaining_bytes = parsed
    else:
        result.remaining_bytes = len(body) - 6

    return result


def _format_header(lines: list[str], h: GameEntryHeader, raw_size: int) -> None:
    """Append common header lines (DID, size, file ID refs) to a report."""
    lines.append(f"DID: {h.did}  (0x{h.did:08X})")
    lines.append(f"Size: {raw_size} bytes")
    lines.append(f"File ID refs in header: {h.ref_count}")
    for fid in h.file_ids:
        lines.append(f"  0x{fid:08X}")


def _format_properties(lines: list[str], properties: list[DecodedProperty]) -> None:
    """Append formatted property lines to a report."""
    for prop in properties:
        if prop.is_array:
            elems = " ".join(f"0x{e:08X}" for e in prop.value)
            lines.append(f"  0x{prop.key:08X} = [{elems}]")
        else:
            lines.append(
                f"  0x{prop.key:08X} = {prop.value} (0x{prop.value:08X})"
            )


def format_type4(entry: Type4Entry) -> str:
    """Format a decoded type-4 entry as a human-readable report."""
    lines: list[str] = []
    _format_header(lines, entry.header, entry.raw_size)

    lines.append(f"\nProperties: {len(entry.properties)}")
    _format_properties(lines, entry.properties)

    if entry.remaining_bytes > 0:
        lines.append(f"\nUnparsed: {entry.remaining_bytes} bytes")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Type-2 entry decoder
# ---------------------------------------------------------------------------


@dataclass
class Type2Entry:
    """Decoded type-2 entry (items, feats, enhancements).

    Type-2 entries come in two variants:
    - "simple": body = [u32=1][flag:u8][count:u8][key:u32,val:u32 pairs]
      Same as type-4 except the pad uint32 is 1 instead of 0. ~60% of entries.
    - "complex": body starts with tsize -> property count, followed by a
      Turbine property stream. Without the property definition registry
      (missing from DDO), value types cannot be determined from metadata.
    """

    header: GameEntryHeader
    raw_size: int
    variant: str = "unknown"
    """'simple', 'complex-pairs', or 'complex-partial'."""

    outer_count: int = 0
    """Property count (from pad+count or tsize)."""

    properties: list[DecodedProperty] = field(default_factory=list)
    """Decoded properties (complete for simple/complex-pairs)."""

    remaining_bytes: int = 0
    """Bytes left unparsed after the property stream."""

    # Pattern annotations for complex-partial variant
    body_def_refs: list[tuple[int, int]] = field(default_factory=list)
    body_ascii_strings: list[tuple[int, str]] = field(default_factory=list)
    body_file_refs: list[tuple[int, int]] = field(default_factory=list)
    body_floats: list[tuple[int, float]] = field(default_factory=list)


def decode_type2(data: bytes) -> Type2Entry:
    """Decode a type-2 entry: [DID:u32=2][ref_count:u8][file_ids...][body].

    Tries three strategies in order:

    1. **Simple** (type-4-like): body = [u32=1][flag:u8][count:u8][pairs...]
       Identical to type-4 format except the pad uint32 is 1.

    2. **Complex-pairs**: body starts with tsize -> count, then count greedy
       [key:u32, val:u32] pairs.  Works when all property values fit u32.

    3. **Complex-partial**: tsize -> count, but pairs don't fit cleanly.
       Falls back to pattern detection (def refs, strings, floats, file IDs).

    DDO lacks the property definition registry (DID 0x34000000 not in any
    .dat file), so full type-aware decoding of complex entries is not possible.
    """
    header = parse_entry_header(data)
    body = data[header.body_offset:]
    result = Type2Entry(header=header, raw_size=len(data))

    if len(body) < 2:
        result.remaining_bytes = len(body)
        return result

    # Strategy 1: Simple variant (type-4-like with pad=1)
    if len(body) >= 6:
        pad = struct.unpack_from("<I", body, 0)[0]
        if pad == 0x00000001:
            count = body[5]
            parsed = _try_greedy_pairs(body, 6, count)
            if parsed is not None:
                props, remaining = parsed
                if remaining == 0:
                    result.variant = "simple"
                    result.outer_count = count
                    result.properties = props
                    result.remaining_bytes = 0
                    return result

    # Strategy 2: tsize-based with greedy pairs
    ins = io.BytesIO(body)
    try:
        outer_count = read_tsize(ins)
    except ValueError:
        result.remaining_bytes = len(body)
        return result

    result.outer_count = outer_count
    tsize_end = ins.tell()

    if outer_count == 0:
        result.variant = "complex-pairs"
        result.remaining_bytes = len(body) - tsize_end
        return result

    parsed = _try_greedy_pairs(body, tsize_end, outer_count)
    if parsed is not None:
        props, remaining = parsed
        if remaining == 0:
            result.variant = "complex-pairs"
            result.properties = props
            result.remaining_bytes = 0
            return result

    # Strategy 3: Pattern detection fallback
    result.variant = "complex-partial"
    body_after_tsize = body[tsize_end:]
    result.remaining_bytes = len(body_after_tsize)
    result.body_def_refs = find_definition_refs(body_after_tsize)
    result.body_ascii_strings = find_length_prefixed_strings(body_after_tsize)
    result.body_file_refs = find_file_id_refs(body_after_tsize)
    result.body_floats = find_float_values(body_after_tsize)

    return result


def format_type2(entry: Type2Entry) -> str:
    """Format a decoded type-2 entry as a human-readable report."""
    lines: list[str] = []
    _format_header(lines, entry.header, entry.raw_size)
    lines.append(f"Variant: {entry.variant}")

    lines.append(f"\nProperties: {entry.outer_count}")

    if entry.variant in ("simple", "complex-pairs"):
        _format_properties(lines, entry.properties)

    elif entry.variant == "complex-partial":
        lines.append(
            "  (value types unknown -- property definition registry"
            " not found in DDO)"
        )
        lines.append(f"  Unparsed body: {entry.remaining_bytes} bytes")

        if entry.body_def_refs:
            lines.append(
                f"\n  Definition refs (0x10XXXXXX): {len(entry.body_def_refs)}"
            )
            for off, val in entry.body_def_refs[:10]:
                lines.append(f"    @+0x{off:04X}: 0x{val:08X}")
            if len(entry.body_def_refs) > 10:
                lines.append(
                    f"    ... and {len(entry.body_def_refs) - 10} more"
                )

        if entry.body_ascii_strings:
            lines.append(
                f"\n  ASCII strings: {len(entry.body_ascii_strings)}"
            )
            for off, text in entry.body_ascii_strings[:5]:
                display = text[:60] + ("..." if len(text) > 60 else "")
                lines.append(f'    @+0x{off:04X}: "{display}"')
            if len(entry.body_ascii_strings) > 5:
                lines.append(
                    f"    ... and {len(entry.body_ascii_strings) - 5} more"
                )

        if entry.body_file_refs:
            lines.append(
                f"\n  File ID refs in body: {len(entry.body_file_refs)}"
            )
            for off, val in entry.body_file_refs[:10]:
                high = (val >> 24) & 0xFF
                label = _FILE_ID_LABELS.get(high, f"0x{high:02X}")
                lines.append(f"    @+0x{off:04X}: 0x{val:08X} ({label})")

        if entry.body_floats:
            lines.append(f"\n  Float values: {len(entry.body_floats)}")
            for off, val in entry.body_floats[:10]:
                lines.append(f"    @+0x{off:04X}: {val:.4g}")

    if entry.remaining_bytes > 0 and entry.variant != "complex-partial":
        lines.append(f"\nUnparsed: {entry.remaining_bytes} bytes")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main probe function
# ---------------------------------------------------------------------------


def probe_entry(data: bytes) -> ProbeResult:
    """Probe a binary entry for all recognizable patterns.

    Parses the DDO entry header (DID + file ID refs), then scans the
    remaining body for definition refs, ASCII strings, file ID refs,
    and float values.
    """
    header = parse_entry_header(data)

    result = ProbeResult(
        header=header,
        raw_size=len(data),
    )

    body_start = header.body_offset
    body_size = len(data) - body_start

    # Scan body for patterns
    result.def_refs = find_definition_refs(data, body_start)
    result.file_id_refs = find_file_id_refs(data, body_start)
    result.ascii_strings = find_length_prefixed_strings(data, body_start)
    result.float_values = find_float_values(data, body_start)

    # Compute coverage from detected patterns
    accounted = set()
    for off, val in result.def_refs:
        for b in range(off, off + 4):
            accounted.add(b)
    for off, text in result.ascii_strings:
        for b in range(off, off + 1 + len(text)):
            accounted.add(b)
    for off, val in result.file_id_refs:
        for b in range(off, off + 4):
            accounted.add(b)
    for off, val in result.float_values:
        for b in range(off, off + 4):
            accounted.add(b)

    body_bytes = set(range(body_start, len(data)))
    if body_size > 0:
        result.parse_coverage = len(accounted & body_bytes) / body_size

    return result


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_probe_result(result: ProbeResult) -> str:
    """Format a probe result as a human-readable report."""
    lines: list[str] = []
    _format_header(lines, result.header, result.raw_size)

    header = result.header
    lines.append(f"\nBody starts at offset 0x{header.body_offset:04X} "
                 f"({result.raw_size - header.body_offset} bytes)")
    lines.append(f"Pattern coverage: {result.parse_coverage:.1%}")

    if result.def_refs:
        lines.append(f"\nDefinition refs (0x10XXXXXX): {len(result.def_refs)}")
        for off, val in result.def_refs[:10]:
            lines.append(f"  @0x{off:04X}: 0x{val:08X}")
        if len(result.def_refs) > 10:
            lines.append(f"  ... and {len(result.def_refs) - 10} more")

    if result.ascii_strings:
        lines.append(f"\nASCII strings: {len(result.ascii_strings)}")
        for off, text in result.ascii_strings[:5]:
            display = text[:60] + ("..." if len(text) > 60 else "")
            lines.append(f"  @0x{off:04X}: \"{display}\"")
        if len(result.ascii_strings) > 5:
            lines.append(f"  ... and {len(result.ascii_strings) - 5} more")

    if result.file_id_refs:
        lines.append(f"\nFile ID refs in body: {len(result.file_id_refs)}")
        for off, val in result.file_id_refs[:10]:
            high = (val >> 24) & 0xFF
            label = _FILE_ID_LABELS.get(high, f"0x{high:02X}")
            lines.append(f"  @0x{off:04X}: 0x{val:08X} ({label})")
        if len(result.file_id_refs) > 10:
            lines.append(f"  ... and {len(result.file_id_refs) - 10} more")

    if result.float_values:
        lines.append(f"\nFloat values: {len(result.float_values)}")
        for off, val in result.float_values[:10]:
            lines.append(f"  @0x{off:04X}: {val:.4g}")
        if len(result.float_values) > 10:
            lines.append(f"  ... and {len(result.float_values) - 10} more")

    return "\n".join(lines)
