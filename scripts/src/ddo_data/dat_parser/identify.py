"""Entity identification via localization cross-reference.

Cross-references all entries in client_gamelogic.dat with the English
string table to discover which entries have human-readable names.

The Turbine engine uses a shared 24-bit namespace across archives.
A gamelogic entry with file_id 0x79001234 (for example) will have
its name string at 0x0A001234 in the English archive. This holds
for 0x79XXXXXX item entries and may extend to other high-byte ranges.

This module enumerates ALL B-tree entries (not just the 2,270 found
by the brute-force scanner) and builds a complete entity inventory.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .archive import DatArchive
from .btree import traverse_btree
from .strings import load_string_table


@dataclass
class IdentifyResult:
    """Results of the full entity identification pass."""

    total_gamelogic: int = 0
    """Total entries found in the gamelogic B-tree."""

    total_named: int = 0
    """Entries successfully resolved to a name string."""

    by_high_byte: dict[int, int] = field(default_factory=dict)
    """Entry counts grouped by file_id high byte."""

    named_by_high_byte: dict[int, int] = field(default_factory=dict)
    """Named-entry counts grouped by file_id high byte."""

    prefix_counts: Counter = field(default_factory=Counter)
    """Counts of name prefix patterns (e.g. 'Quest', 'Spell', 'Feat')."""

    sample_names: dict[int, list[str]] = field(default_factory=dict)
    """Up to 5 sample names per high byte."""


def _extract_prefix(name: str) -> str:
    """Extract a category prefix from a name string.

    Looks for patterns like "Quest: Foo", "Spell: Fireball", etc.
    Falls back to first 2 words or the full name if short.
    """
    # Pattern: "Category: Rest of name"
    m = re.match(r"^([A-Za-z][A-Za-z ]{1,25}):\s", name)
    if m:
        return m.group(1).strip()

    # Items often have no prefix — classify by parenthetical suffix
    m = re.search(r"\(([A-Za-z ]+)\)\s*$", name)
    if m:
        return m.group(1).strip()

    # Use first word as a rough category
    words = name.split()
    if words:
        return words[0].rstrip(",:.")

    return name[:20]


def identify_entities(
    ddo_path: Path,
    *,
    on_progress: Callable[[str], None] | None = None,
) -> IdentifyResult:
    """Identify all gamelogic entries via localization cross-reference.

    Args:
        ddo_path: DDO installation directory containing .dat files.
        on_progress: Optional status callback.

    Returns:
        IdentifyResult with counts and sample names.
    """
    result = IdentifyResult()

    # Load English string table (uses B-tree, fast key-by-lower24 lookup)
    english_path = ddo_path / "client_local_English.dat"
    if not english_path.exists():
        if on_progress:
            on_progress(f"English archive not found: {english_path}")
        return result

    if on_progress:
        on_progress("Loading English string table...")
    english_archive = DatArchive(english_path)
    english_archive.read_header()
    string_table = load_string_table(english_archive)

    # Build lower-24-bit lookup: lower24 -> name
    lower24_to_name: dict[int, str] = {}
    for file_id, text in string_table.items():
        lower = file_id & 0x00FFFFFF
        if lower not in lower24_to_name:
            lower24_to_name[lower] = text

    if on_progress:
        on_progress(f"  {len(string_table):,} strings loaded ({len(lower24_to_name):,} unique lower-24)")

    # Traverse gamelogic B-tree — this finds all ~490K entries
    gamelogic_path = ddo_path / "client_gamelogic.dat"
    if not gamelogic_path.exists():
        if on_progress:
            on_progress(f"Gamelogic archive not found: {gamelogic_path}")
        return result

    if on_progress:
        on_progress("Traversing gamelogic B-tree (this may take a moment)...")
    gamelogic_archive = DatArchive(gamelogic_path)
    gamelogic_archive.read_header()
    entries = traverse_btree(gamelogic_archive)
    result.total_gamelogic = len(entries)

    if on_progress:
        on_progress(f"  {len(entries):,} entries found")

    # Count by high byte and attempt name resolution
    high_byte_counts: Counter[int] = Counter()
    named_by_hb: Counter[int] = Counter()
    samples: dict[int, list[str]] = defaultdict(list)

    for file_id in entries:
        high = (file_id >> 24) & 0xFF
        high_byte_counts[high] += 1

        lower = file_id & 0x00FFFFFF
        name = lower24_to_name.get(lower)
        if name:
            result.total_named += 1
            named_by_hb[high] += 1
            # Only count prefix patterns and collect samples for clean ASCII names.
            # The fallback decoder in load_string_table sometimes returns garbled
            # text (binary header bytes decoded as UTF-16LE before the real text).
            is_printable_ascii = all(0x20 <= ord(c) <= 0x7E for c in name)
            if is_printable_ascii:
                result.prefix_counts[_extract_prefix(name)] += 1
                if len(samples[high]) < 5:
                    samples[high].append(name)

    result.by_high_byte = dict(high_byte_counts)
    result.named_by_high_byte = dict(named_by_hb)
    result.sample_names = dict(samples)

    return result


def format_identify(result: IdentifyResult) -> str:
    """Format identification results as human-readable text."""
    lines: list[str] = []
    lines.append(f"Total gamelogic entries: {result.total_gamelogic:,}")
    lines.append(f"Named entries:           {result.total_named:,} ({100 * result.total_named / max(result.total_gamelogic, 1):.1f}%)")
    lines.append("")

    lines.append("Entry counts by file_id high byte:")
    lines.append(f"  {'High Byte':>10}  {'Total':>8}  {'Named':>8}  {'Match%':>7}  {'Sample names'}")
    lines.append("  " + "-" * 80)
    for high in sorted(result.by_high_byte, key=lambda h: -result.by_high_byte[h]):
        total = result.by_high_byte[high]
        named = result.named_by_high_byte.get(high, 0)
        pct = 100 * named / total if total else 0
        samples = result.sample_names.get(high, [])
        sample_str = " | ".join(samples[:2]) if samples else ""
        lines.append(f"  0x{high:02X}           {total:>8,}  {named:>8,}  {pct:>6.1f}%  {sample_str}")

    if result.prefix_counts:
        lines.append("")
        lines.append(f"Name prefix patterns (top 30, across {result.total_named:,} named entries):")
        lines.append(f"  {'Prefix':<30}  {'Count':>8}")
        lines.append("  " + "-" * 42)
        for prefix, count in result.prefix_counts.most_common(30):
            lines.append(f"  {prefix:<30}  {count:>8,}")

    return "\n".join(lines)
