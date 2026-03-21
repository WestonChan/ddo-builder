"""Survey tool for 0x47XXXXXX spell entries in client_gamelogic.dat.

Spell entries are unique among DDO binary formats: the body is 0-2 bytes
(essentially empty), and the entire spell definition is packed into the
header ref list as 10-41 uint32 slots.  This module surveys all 0x47
entries to discover ref_count shapes, slot value distributions, and
localization string content.

Known slot semantics (from prior analysis of 152 named spells):
  Slot 0: 0x0147XXXX -- spell template pointer in client_general.dat
  Slot 1: 0xNN000000 -- variant/type ID (NOT school; class variants)
  Slot 2: 0x001FXXXX -- parameter block indicator
  Slots 3+: packed binary parameters (small ints, stat_def_ids)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .archive import DatArchive, FileEntry
from .btree import traverse_btree
from .extract import read_entry_data
from .probe import parse_entry_header
from .strings import load_string_table

logger = logging.getLogger(__name__)


@dataclass
class SpellEntry:
    """A single parsed 0x47XXXXXX spell entry."""

    file_id: int
    name: str | None
    ref_count: int
    refs: list[int]
    body_size: int
    did: int

    # Derived slot values
    slot0_template: int = 0
    slot1_variant: int = 0

    # Resolved 0x0A localization strings found in refs
    oa_refs: dict[int, str] = field(default_factory=dict)
    """Maps slot index -> resolved string for 0x0AXXXXXX refs."""


@dataclass
class SpellSurveyResult:
    """Aggregated statistics from surveying all 0x47 spell entries."""

    total_entries: int = 0
    named_entries: int = 0
    did_histogram: dict[int, int] = field(default_factory=dict)
    ref_count_histogram: dict[int, int] = field(default_factory=dict)
    body_size_histogram: dict[int, int] = field(default_factory=dict)

    # Per-slot analysis: slot_index -> {high_byte -> count}
    slot_high_byte_dist: dict[int, dict[int, int]] = field(default_factory=dict)

    # Resolved 0x0A strings: string_text -> count
    oa_string_frequency: dict[str, int] = field(default_factory=dict)
    # Which slot positions carry 0x0A refs: slot_index -> count
    oa_slot_positions: dict[int, int] = field(default_factory=dict)

    # Named spell grouping: name -> list of file_ids (class variants)
    name_variants: dict[str, list[int]] = field(default_factory=dict)

    # Slot value distributions for small-integer slots (slots 3+)
    # slot_index -> {value -> count} (only for values < 0x10000)
    slot_small_value_dist: dict[int, dict[int, int]] = field(default_factory=dict)

    # Sample entries for downstream analysis
    entries: list[SpellEntry] = field(default_factory=list)

    errors: int = 0


def _parse_spell_entry(
    data: bytes,
    file_id: int,
    name: str | None,
    string_table: dict[int, str],
) -> SpellEntry:
    """Parse a single 0x47 entry into a SpellEntry."""
    header = parse_entry_header(data)

    entry = SpellEntry(
        file_id=file_id,
        name=name,
        ref_count=header.ref_count,
        refs=header.file_ids,
        body_size=len(data) - header.body_offset,
        did=header.did,
    )

    if header.ref_count >= 1:
        entry.slot0_template = header.file_ids[0]
    if header.ref_count >= 2:
        entry.slot1_variant = header.file_ids[1]

    # Resolve 0x0A localization refs
    for i, ref_val in enumerate(header.file_ids):
        high = (ref_val >> 24) & 0xFF
        if high == 0x0A:
            resolved = string_table.get(ref_val)
            if resolved:
                entry.oa_refs[i] = resolved

    return entry


def survey_spell_entries(
    ddo_path: Path,
    *,
    on_progress: Callable[[str], None] | None = None,
) -> SpellSurveyResult:
    """Survey all 0x47XXXXXX spell entries and compute statistics.

    Opens client_gamelogic.dat and client_local_English.dat, loads the
    string table, traverses the gamelogic B-tree, filters to 0x47 entries,
    and collects ref_count shapes, slot distributions, and 0x0A string
    resolution data.
    """
    result = SpellSurveyResult()
    log = on_progress or (lambda msg: None)

    gamelogic_path = ddo_path / "client_gamelogic.dat"
    english_path = ddo_path / "client_local_English.dat"

    # Load string table (covers both 0x25 and 0x0A file IDs)
    log("Loading English string table...")
    english_archive = DatArchive(english_path)
    english_archive.read_header()
    string_table = load_string_table(english_archive)
    log(f"  {len(string_table):,} strings loaded")

    # Traverse gamelogic B-tree
    log("Traversing gamelogic B-tree...")
    gamelogic_archive = DatArchive(gamelogic_path)
    gamelogic_archive.read_header()
    all_entries = traverse_btree(gamelogic_archive)
    log(f"  {len(all_entries):,} total entries")

    # Filter to 0x47 namespace
    spell_file_ids = [
        fid for fid in all_entries if (fid >> 24) & 0xFF == 0x47
    ]
    log(f"  {len(spell_file_ids):,} spell entries (0x47)")

    # Process each spell entry
    for i, file_id in enumerate(sorted(spell_file_ids)):
        if (i + 1) % 5000 == 0:
            log(f"  Processing {i + 1:,}/{len(spell_file_ids):,}...")

        fe = all_entries[file_id]
        try:
            data = read_entry_data(gamelogic_archive, fe)
        except (ValueError, OSError):
            result.errors += 1
            continue

        # Resolve name via shared 24-bit namespace
        lower = file_id & 0x00FFFFFF
        name_id = 0x25000000 | lower
        name = string_table.get(name_id)

        entry = _parse_spell_entry(data, file_id, name, string_table)
        result.entries.append(entry)
        result.total_entries += 1

        # Aggregate statistics
        if name:
            result.named_entries += 1
            result.name_variants.setdefault(name, []).append(file_id)

        result.did_histogram[entry.did] = (
            result.did_histogram.get(entry.did, 0) + 1
        )
        result.ref_count_histogram[entry.ref_count] = (
            result.ref_count_histogram.get(entry.ref_count, 0) + 1
        )
        result.body_size_histogram[entry.body_size] = (
            result.body_size_histogram.get(entry.body_size, 0) + 1
        )

        # Per-slot high-byte distribution
        for slot_idx, ref_val in enumerate(entry.refs):
            high = (ref_val >> 24) & 0xFF
            if slot_idx not in result.slot_high_byte_dist:
                result.slot_high_byte_dist[slot_idx] = {}
            dist = result.slot_high_byte_dist[slot_idx]
            dist[high] = dist.get(high, 0) + 1

            # Track small integer values at slots 3+
            if slot_idx >= 3 and ref_val < 0x10000:
                if slot_idx not in result.slot_small_value_dist:
                    result.slot_small_value_dist[slot_idx] = {}
                vdist = result.slot_small_value_dist[slot_idx]
                vdist[ref_val] = vdist.get(ref_val, 0) + 1

        # 0x0A string aggregation
        for slot_idx, text in entry.oa_refs.items():
            result.oa_string_frequency[text] = (
                result.oa_string_frequency.get(text, 0) + 1
            )
            result.oa_slot_positions[slot_idx] = (
                result.oa_slot_positions.get(slot_idx, 0) + 1
            )

    log(f"Survey complete: {result.total_entries:,} entries, "
        f"{result.named_entries:,} named, {result.errors} errors")

    return result


def format_spell_survey(result: SpellSurveyResult) -> str:
    """Format a SpellSurveyResult as a human-readable report."""
    lines: list[str] = []

    lines.append("Spell Entry Survey (0x47XXXXXX)")
    lines.append("=" * 40)
    lines.append(f"Total entries: {result.total_entries:,}  "
                 f"(named: {result.named_entries:,}, errors: {result.errors})")
    lines.append("")

    # DID histogram
    lines.append("DID distribution:")
    for did in sorted(result.did_histogram, key=lambda k: result.did_histogram[k], reverse=True):
        count = result.did_histogram[did]
        pct = 100 * count / max(result.total_entries, 1)
        lines.append(f"  0x{did:08X}  {count:>8,}  ({pct:5.1f}%)")
    lines.append("")

    # ref_count histogram
    lines.append("ref_count distribution:")
    for rc in sorted(result.ref_count_histogram):
        count = result.ref_count_histogram[rc]
        pct = 100 * count / max(result.total_entries, 1)
        lines.append(f"  ref_count={rc:<4d}  {count:>8,}  ({pct:5.1f}%)")
    lines.append("")

    # Body size histogram
    lines.append("Body size distribution:")
    for bs in sorted(result.body_size_histogram):
        count = result.body_size_histogram[bs]
        pct = 100 * count / max(result.total_entries, 1)
        lines.append(f"  body_size={bs:<4d}  {count:>8,}  ({pct:5.1f}%)")
    lines.append("")

    # Per-slot high-byte distribution (first 10 slots)
    max_slot = min(max(result.slot_high_byte_dist.keys(), default=0) + 1, 15)
    lines.append(f"Slot high-byte distribution (slots 0-{max_slot - 1}):")
    for slot_idx in range(max_slot):
        dist = result.slot_high_byte_dist.get(slot_idx, {})
        if not dist:
            continue
        total = sum(dist.values())
        # Show top 5 high bytes
        top = sorted(dist.items(), key=lambda kv: -kv[1])[:5]
        parts = [f"0x{hb:02X}:{count}" for hb, count in top]
        lines.append(f"  Slot {slot_idx:>2d}: {', '.join(parts)}  (total={total:,})")
    lines.append("")

    # 0x0A localization strings
    if result.oa_string_frequency:
        lines.append(f"Resolved 0x0A strings ({len(result.oa_string_frequency)} unique):")
        for text, count in sorted(
            result.oa_string_frequency.items(), key=lambda kv: -kv[1]
        )[:30]:
            lines.append(f"  {count:>6,}  {text!r}")
        if len(result.oa_string_frequency) > 30:
            lines.append(f"  ... and {len(result.oa_string_frequency) - 30} more")
        lines.append("")

        lines.append("0x0A ref slot positions:")
        for slot_idx in sorted(result.oa_slot_positions):
            count = result.oa_slot_positions[slot_idx]
            lines.append(f"  Slot {slot_idx:>2d}: {count:,} entries")
        lines.append("")

    # Named spell variants (spells appearing as multiple entries)
    multi_variant = {
        name: fids for name, fids in result.name_variants.items()
        if len(fids) > 1
    }
    if multi_variant:
        lines.append(f"Named spells with multiple variants: "
                     f"{len(multi_variant)} (of {len(result.name_variants)} named)")
        # Show top 10 by variant count
        for name, fids in sorted(
            multi_variant.items(), key=lambda kv: -len(kv[1])
        )[:10]:
            ids = " ".join(f"0x{fid:08X}" for fid in sorted(fids)[:5])
            suffix = " ..." if len(fids) > 5 else ""
            lines.append(f"  {name!r} x{len(fids)}: {ids}{suffix}")
        lines.append("")

    # Frequent small values at slots 3+
    if result.slot_small_value_dist:
        lines.append("Frequent small integer values at slots 3+:")
        for slot_idx in sorted(result.slot_small_value_dist):
            vdist = result.slot_small_value_dist[slot_idx]
            total = sum(vdist.values())
            if total < 100:
                continue
            top = sorted(vdist.items(), key=lambda kv: -kv[1])[:8]
            parts = [f"{val}:{count}" for val, count in top]
            lines.append(f"  Slot {slot_idx:>2d}: {', '.join(parts)}  "
                         f"({len(vdist)} unique, {total:,} entries)")
        lines.append("")

    return "\n".join(lines)


def format_spell_survey_json(result: SpellSurveyResult) -> dict:
    """Format a SpellSurveyResult as a JSON-serializable dict."""
    return {
        "summary": {
            "total_entries": result.total_entries,
            "named_entries": result.named_entries,
            "errors": result.errors,
        },
        "did_histogram": {
            f"0x{did:08X}": count
            for did, count in sorted(result.did_histogram.items(), key=lambda kv: -kv[1])
        },
        "ref_count_histogram": {
            str(rc): count
            for rc, count in sorted(result.ref_count_histogram.items())
        },
        "body_size_histogram": {
            str(bs): count
            for bs, count in sorted(result.body_size_histogram.items())
        },
        "oa_string_frequency": {
            text: count
            for text, count in sorted(
                result.oa_string_frequency.items(), key=lambda kv: -kv[1]
            )
        },
        "oa_slot_positions": {
            str(slot): count
            for slot, count in sorted(result.oa_slot_positions.items())
        },
        "slot_high_byte_dist": {
            str(slot): {
                f"0x{hb:02X}": count
                for hb, count in sorted(dist.items(), key=lambda kv: -kv[1])
            }
            for slot, dist in sorted(result.slot_high_byte_dist.items())
        },
        "name_variants": {
            name: [f"0x{fid:08X}" for fid in sorted(fids)]
            for name, fids in sorted(result.name_variants.items())
            if len(fids) > 1
        },
    }
