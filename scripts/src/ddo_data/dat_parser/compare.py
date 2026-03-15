"""Compare entries sharing the same type code to find field patterns.

Reads multiple entries of the same first-uint32 type code and analyzes
them byte-by-byte to identify constant regions (format markers),
bounded-range fields (enums/flags), and highly variable fields (IDs/data).
"""

import struct
from dataclasses import dataclass, field

from .archive import DatArchive, FileEntry
from .extract import read_entry_data, scan_file_table


@dataclass
class FieldAnalysis:
    """Analysis of a 4-byte aligned field across multiple entries."""

    offset: int
    min_val: int = 0
    max_val: int = 0
    unique_count: int = 0
    sample_values: list[int] = field(default_factory=list)

    @property
    def category(self) -> str:
        """Classify the field based on value distribution."""
        if self.unique_count == 1:
            return "constant"
        elif self.unique_count <= 10:
            return "bounded"
        else:
            return "variable"


@dataclass
class CompareResult:
    """Result of comparing entries with the same type code."""

    type_code: int
    entry_count: int
    min_size: int
    max_size: int
    fields: list[FieldAnalysis] = field(default_factory=list)
    errors: int = 0


def compare_entries_by_type(
    archive: DatArchive,
    type_code: int,
    entries: dict[int, FileEntry] | None = None,
    limit: int = 50,
) -> CompareResult:
    """Compare entries sharing the same first-uint32 type code.

    Reads up to `limit` entries whose decompressed content starts with
    `type_code`, then analyzes each 4-byte-aligned field position.

    Args:
        archive: Opened archive with header already read.
        type_code: The first-uint32 value to filter by.
        entries: Pre-scanned file table (scanned if not provided).
        limit: Max entries to compare.

    Returns:
        CompareResult with per-field analysis.
    """
    if entries is None:
        entries = scan_file_table(archive)

    # Collect entries matching the type code
    matching: list[bytes] = []
    errors = 0

    for entry in sorted(entries.values(), key=lambda e: e.file_id):
        if len(matching) >= limit:
            break
        try:
            data = read_entry_data(archive, entry)
        except (ValueError, OSError):
            errors += 1
            continue

        if len(data) < 4:
            continue

        first_u32 = struct.unpack_from("<I", data, 0)[0]
        if first_u32 == type_code:
            matching.append(data)

    if not matching:
        return CompareResult(
            type_code=type_code,
            entry_count=0,
            min_size=0,
            max_size=0,
            errors=errors,
        )

    min_size = min(len(d) for d in matching)
    max_size = max(len(d) for d in matching)

    # Analyze each 4-byte-aligned field up to the shortest entry
    fields: list[FieldAnalysis] = []
    for offset in range(0, min_size - 3, 4):
        values: list[int] = []
        for entry_data in matching:
            field_value = struct.unpack_from("<I", entry_data, offset)[0]
            values.append(field_value)

        unique = set(values)
        samples = sorted(unique)[:5]

        fields.append(FieldAnalysis(
            offset=offset,
            min_val=min(values),
            max_val=max(values),
            unique_count=len(unique),
            sample_values=samples,
        ))

    return CompareResult(
        type_code=type_code,
        entry_count=len(matching),
        min_size=min_size,
        max_size=max_size,
        fields=fields,
        errors=errors,
    )


def format_compare_result(result: CompareResult) -> str:
    """Format a CompareResult as a human-readable report."""
    lines: list[str] = []

    lines.append(
        f"Type 0x{result.type_code:08X}:  "
        f"{result.entry_count} entries  "
        f"size={result.min_size}-{result.max_size} bytes"
    )
    if result.errors:
        lines.append(f"  ({result.errors} read errors)")
    lines.append("")

    lines.append(f"  {'Offset':<10s}  {'Category':<10s}  {'Unique':>6s}  "
                 f"{'Min':>12s}  {'Max':>12s}  Samples")
    lines.append(f"  {'-' * 10}  {'-' * 10}  {'-' * 6}  "
                 f"{'-' * 12}  {'-' * 12}  {'-' * 30}")

    for field_info in result.fields:
        samples_str = ", ".join(f"0x{v:08X}" for v in field_info.sample_values[:3])
        marker = ""
        if field_info.category == "constant":
            marker = " <--"
        lines.append(
            f"  0x{field_info.offset:06X}    {field_info.category:<10s}  {field_info.unique_count:>6d}  "
            f"0x{field_info.min_val:08X}  0x{field_info.max_val:08X}  {samples_str}{marker}"
        )

    # Summary
    constant = sum(1 for f in result.fields if f.category == "constant")
    bounded = sum(1 for f in result.fields if f.category == "bounded")
    variable = sum(1 for f in result.fields if f.category == "variable")
    lines.append("")
    lines.append(
        f"  Fields: {len(result.fields)} total  "
        f"({constant} constant, {bounded} bounded, {variable} variable)"
    )

    return "\n".join(lines)
