"""Empirical property key registry for DDO gamelogic entries.

Scans decoded type-4 and type-2 entries to collect all property keys
(typically 0x10XXXXXX definition references) and build per-key statistics.
This census is the foundation for future name mapping -- DDO lacks the
property definition registry that LOTRO has at DID 0x34000000.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field

from .archive import DatArchive
from .extract import FileEntry, read_entry_data
from .probe import (
    DecodedProperty,
    decode_type2,
    decode_type4,
    parse_entry_header,
)

logger = logging.getLogger(__name__)

_MAX_SAMPLE_IDS = 5


@dataclass
class PropertyKeyInfo:
    """Statistics for a single property key observed across decoded entries."""

    key: int
    count: int = 0
    entry_types: set[int] = field(default_factory=set)
    scalar_count: int = 0
    array_count: int = 0
    min_scalar: int | None = None
    max_scalar: int | None = None
    array_lengths: dict[int, int] = field(default_factory=dict)
    sample_entry_ids: list[int] = field(default_factory=list)


@dataclass
class RegistryResult:
    """Aggregate results from scanning an archive for property keys."""

    total_scanned: int = 0
    decoded_type4: int = 0
    decoded_type2: int = 0
    skipped: int = 0
    total_properties: int = 0
    keys: dict[int, PropertyKeyInfo] = field(default_factory=dict)


def build_registry(
    archive: DatArchive,
    entries: dict[int, FileEntry],
    *,
    limit: int = 0,
) -> RegistryResult:
    """Scan decoded entries and build a property key census.

    Attempts to decode each entry as type-4 or type-2 (simple/complex-pairs).
    For each successfully decoded property, records key statistics.

    Args:
        archive: Open DatArchive instance.
        entries: File table entries from scan_file_table().
        limit: Maximum entries to scan (0 = all).

    Returns:
        RegistryResult with per-key statistics.
    """
    result = RegistryResult()
    sorted_entries = sorted(entries.values(), key=lambda e: e.file_id)
    if limit > 0:
        sorted_entries = sorted_entries[:limit]

    for entry in sorted_entries:
        result.total_scanned += 1

        try:
            data = read_entry_data(archive, entry)
        except (ValueError, OSError):
            result.skipped += 1
            continue

        if len(data) < 5:
            result.skipped += 1
            continue

        try:
            header = parse_entry_header(data)
        except ValueError:
            result.skipped += 1
            continue

        if header.did == 4:
            try:
                decoded = decode_type4(data)
            except (ValueError, struct.error):
                result.skipped += 1
                continue
            result.decoded_type4 += 1
            for prop in decoded.properties:
                _record_property(result, prop, header.did, entry.file_id)

        elif header.did == 2:
            try:
                decoded = decode_type2(data)
            except (ValueError, struct.error):
                result.skipped += 1
                continue
            if decoded.variant in ("simple", "complex-pairs"):
                result.decoded_type2 += 1
                for prop in decoded.properties:
                    _record_property(result, prop, header.did, entry.file_id)
            else:
                result.skipped += 1

        else:
            result.skipped += 1

    logger.info(
        "Registry: scanned %d, decoded %d type-4 + %d type-2, skipped %d, %d unique keys",
        result.total_scanned,
        result.decoded_type4,
        result.decoded_type2,
        result.skipped,
        len(result.keys),
    )
    return result


def _record_property(
    result: RegistryResult,
    prop: DecodedProperty,
    did: int,
    file_id: int,
) -> None:
    """Update registry statistics for a single decoded property."""
    result.total_properties += 1

    key_stats = result.keys.get(prop.key)
    if key_stats is None:
        key_stats = PropertyKeyInfo(key=prop.key)
        result.keys[prop.key] = key_stats

    key_stats.count += 1
    key_stats.entry_types.add(did)

    if prop.is_array:
        key_stats.array_count += 1
        length = len(prop.value)
        key_stats.array_lengths[length] = key_stats.array_lengths.get(length, 0) + 1
    else:
        key_stats.scalar_count += 1
        scalar_val = prop.value
        if key_stats.min_scalar is None or scalar_val < key_stats.min_scalar:
            key_stats.min_scalar = scalar_val
        if key_stats.max_scalar is None or scalar_val > key_stats.max_scalar:
            key_stats.max_scalar = scalar_val

    if len(key_stats.sample_entry_ids) < _MAX_SAMPLE_IDS:
        key_stats.sample_entry_ids.append(file_id)


def format_registry(result: RegistryResult) -> str:
    """Format a RegistryResult as a human-readable report."""
    lines: list[str] = []

    lines.append("Property Key Registry")
    lines.append("=" * 21)
    lines.append(
        f"Entries scanned: {result.total_scanned:,}"
        f"  (type-4: {result.decoded_type4:,},"
        f" type-2: {result.decoded_type2:,},"
        f" skipped: {result.skipped:,})"
    )
    lines.append(f"Total properties: {result.total_properties:,}")
    lines.append(f"Unique keys: {len(result.keys):,}")

    if not result.keys:
        return "\n".join(lines)

    sorted_keys = sorted(
        result.keys.values(), key=lambda k: k.count, reverse=True
    )

    lines.append("")
    lines.append(
        f"{'Key':<14} {'Count':>6} {'Scalar':>7} {'Array':>6} {'DIDs'}"
    )
    lines.append(f"{'-'*14} {'-'*6} {'-'*7} {'-'*6} {'-'*10}")

    display_count = min(len(sorted_keys), 50)
    for key_stats in sorted_keys[:display_count]:
        dids = ",".join(str(d) for d in sorted(key_stats.entry_types))
        lines.append(
            f"0x{key_stats.key:08X}     {key_stats.count:>6} {key_stats.scalar_count:>7}"
            f" {key_stats.array_count:>6} {{{dids}}}"
        )

    if len(sorted_keys) > 50:
        lines.append(f"  ... and {len(sorted_keys) - 50} more keys")

    return "\n".join(lines)


def format_registry_json(result: RegistryResult) -> dict:
    """Format a RegistryResult as a JSON-serializable dict."""
    return {
        "summary": {
            "total_scanned": result.total_scanned,
            "decoded_type4": result.decoded_type4,
            "decoded_type2": result.decoded_type2,
            "skipped": result.skipped,
            "total_properties": result.total_properties,
            "unique_keys": len(result.keys),
        },
        "keys": {
            f"0x{key:08X}": {
                "key_int": key,
                "count": info.count,
                "entry_types": sorted(info.entry_types),
                "scalar_count": info.scalar_count,
                "array_count": info.array_count,
                "min_scalar": info.min_scalar,
                "max_scalar": info.max_scalar,
                "array_lengths": {
                    str(length): count
                    for length, count in sorted(info.array_lengths.items())
                },
                "sample_entry_ids": [
                    f"0x{fid:08X}" for fid in info.sample_entry_ids
                ],
            }
            for key, info in sorted(
                result.keys.items(), key=lambda kv: kv[1].count, reverse=True
            )
        },
    }
