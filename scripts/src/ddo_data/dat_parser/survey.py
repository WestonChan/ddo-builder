"""Statistical survey of binary entries in Turbine .dat archives.

Scans all entries and builds a profile of the binary content:
type code histograms, size distributions, and string density analysis.
Used to guide reverse-engineering of the binary tagged format.
"""

import struct
from dataclasses import dataclass, field

from .archive import DatArchive, FileEntry
from .extract import read_entry_data, scan_file_table
from .tagged import TaggedStructure, _find_utf16_strings

# Size distribution bucket boundaries
_SIZE_BUCKETS = [
    ("tiny", 0, 64),
    ("small", 64, 512),
    ("medium", 512, 4096),
    ("large", 4096, 65536),
    ("huge", 65536, float("inf")),
]

# String density buckets (ratio of bytes in UTF-16LE strings vs total)
_DENSITY_BUCKETS = [
    ("none", 0.0, 0.01),
    ("low", 0.01, 0.1),
    ("moderate", 0.1, 0.4),
    ("high", 0.4, 0.7),
    ("text-heavy", 0.7, 1.01),
]


@dataclass
class TypeGroup:
    """Entries sharing the same first-uint32 type code."""

    code: int
    count: int = 0
    sample_ids: list[int] = field(default_factory=list)
    total_size: int = 0

    @property
    def avg_size(self) -> float:
        return self.total_size / max(self.count, 1)


@dataclass
class SurveyResult:
    """Aggregated statistics from scanning an archive's entries."""

    type_histogram: dict[int, TypeGroup] = field(default_factory=dict)
    size_distribution: dict[str, int] = field(default_factory=dict)
    string_density: dict[str, int] = field(default_factory=dict)
    total_entries: int = 0
    errors: int = 0


def survey_entries(
    archive: DatArchive,
    entries: dict[int, FileEntry] | None = None,
    limit: int = 0,
) -> SurveyResult:
    """Scan archive entries and build a statistical profile.

    Args:
        archive: Opened archive with header already read.
        entries: Pre-scanned file table (scanned if not provided).
        limit: Max entries to survey (0 = all).

    Returns:
        SurveyResult with type histogram, size distribution, and string density.
    """
    if entries is None:
        entries = scan_file_table(archive)

    result = SurveyResult()
    result.size_distribution = {name: 0 for name, _, _ in _SIZE_BUCKETS}
    result.string_density = {name: 0 for name, _, _ in _DENSITY_BUCKETS}

    sorted_entries = sorted(entries.values(), key=lambda e: e.file_id)
    if limit > 0:
        sorted_entries = sorted_entries[:limit]

    for entry in sorted_entries:
        result.total_entries += 1

        # Size distribution
        for bucket_name, lo, hi in _SIZE_BUCKETS:
            if lo <= entry.size < hi:
                result.size_distribution[bucket_name] += 1
                break

        # Read and analyze content
        try:
            data = read_entry_data(archive, entry)
        except (ValueError, OSError):
            result.errors += 1
            continue

        if len(data) < 4:
            result.errors += 1
            continue

        # First-uint32 type code histogram
        type_code = struct.unpack_from("<I", data, 0)[0]
        if type_code not in result.type_histogram:
            result.type_histogram[type_code] = TypeGroup(code=type_code)

        group = result.type_histogram[type_code]
        group.count += 1
        group.total_size += len(data)
        if len(group.sample_ids) < 5:
            group.sample_ids.append(entry.file_id)

        # String density
        string_bytes = _count_string_bytes(data)
        density = string_bytes / max(len(data), 1)
        for bucket_name, lo, hi in _DENSITY_BUCKETS:
            if lo <= density < hi:
                result.string_density[bucket_name] += 1
                break

    return result


def _count_string_bytes(data: bytes) -> int:
    """Count total bytes covered by detected UTF-16LE strings."""
    tag = TaggedStructure(raw_size=len(data))
    _find_utf16_strings(data, tag)
    total = 0
    for offset, text in tag.strings:
        # Each char is 2 bytes + 2-byte null terminator
        total += len(text) * 2 + 2
    return total


def format_survey(result: SurveyResult) -> str:
    """Format a SurveyResult as a human-readable report."""
    lines: list[str] = []

    lines.append(f"Entries surveyed: {result.total_entries:,}  (errors: {result.errors})")
    lines.append("")

    # Size distribution
    lines.append("Size distribution:")
    for bucket_name, _, _ in _SIZE_BUCKETS:
        count = result.size_distribution.get(bucket_name, 0)
        pct = 100 * count / max(result.total_entries, 1)
        lines.append(f"  {bucket_name:<12s} {count:>8,}  ({pct:5.1f}%)")
    lines.append("")

    # String density
    lines.append("String density (UTF-16LE bytes / total):")
    for bucket_name, _, _ in _DENSITY_BUCKETS:
        count = result.string_density.get(bucket_name, 0)
        pct = 100 * count / max(result.total_entries, 1)
        lines.append(f"  {bucket_name:<12s} {count:>8,}  ({pct:5.1f}%)")
    lines.append("")

    # Type histogram (top 30 by count)
    sorted_types = sorted(
        result.type_histogram.values(), key=lambda g: g.count, reverse=True
    )
    lines.append(f"First-uint32 type codes ({len(sorted_types)} unique):")
    lines.append(f"  {'Code':>12s}  {'Count':>8s}  {'Avg Size':>10s}  Sample IDs")
    lines.append(f"  {'-' * 12}  {'-' * 8}  {'-' * 10}  {'-' * 40}")
    for group in sorted_types[:30]:
        samples = ", ".join(f"0x{fid:08X}" for fid in group.sample_ids[:3])
        lines.append(
            f"  0x{group.code:08X}  {group.count:>8,}  {group.avg_size:>10,.0f}  {samples}"
        )
    if len(sorted_types) > 30:
        lines.append(f"  ... and {len(sorted_types) - 30} more type codes")

    return "\n".join(lines)
