"""Property key name mapping via wiki cross-reference and distribution analysis.

Cross-references wiki item data with decoded gamelogic entries to discover
what binary property keys (0x10XXXXXX) mean in human terms.

Entry format:
  0x79XXXXXX entries in client_gamelogic.dat use a "dup-triple" encoding:
  [preamble:2B] [key:u32][val:u32] [key:u32][key:u32][val:u32] ...
  These share a 24-bit namespace with 0x25XXXXXX localization strings.

Discovery methods:
  1. Wiki correlation: match entries to wiki items via the string table,
     then find property keys whose values match known wiki fields.
  2. Distribution analysis: classify keys by their value distributions
     across all entries (see DISCOVERED_KEYS constant).

Key finding: minimum_level is stored directly as key 0x10001C5D in
dup-triple items (confirmed via Black Opal Bracers ML=31 cross-check).
"""

from __future__ import annotations

import json
import logging
import struct
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .archive import DatArchive, FileEntry
from .btree import traverse_btree
from .extract import read_entry_data
from .probe import DecodedProperty
from .strings import load_string_table

logger = logging.getLogger(__name__)

# Wiki fields to correlate against property key values.
# Numeric fields: compared directly as int.
_NUMERIC_FIELDS = [
    "minimum_level",
    "enhancement_bonus",
    "durability",
    "hardness",
    "armor_bonus",
    "max_dex_bonus",
]

# String fields: property value is a 0x0AXXXXXX string ref, resolved via
# the string table and compared to the wiki field text.
_STRING_FIELDS = [
    "weapon_type",
    "proficiency",
    "material",
    "binding",
    "quest",
    "description",
    "set_name",
    "handedness",
]

_MAX_SAMPLE_VALUES = 5


# ---------------------------------------------------------------------------
# Statistically discovered key meanings (from distribution analysis)
# ---------------------------------------------------------------------------
# These were identified by analyzing value distributions across 76,000+
# named 0x79 entries.  Confidence level indicates how strongly the
# distribution matches the proposed meaning.
#
# NOTE: minimum_level is stored directly as key 0x10001C5D (confirmed via
# cross-check of Black Opal Bracers ML=31).  The earlier hypothesis that it
# was computed at runtime was incorrect.

DISCOVERED_KEYS: dict[int, dict[str, str]] = {
    0x1000361A: {
        "name": "level",
        "confidence": "high",
        "evidence": "4715 entries, range 1-30, smooth tapering distribution. "
                    "Likely quest/encounter level, not item ML.",
    },
    0x10000E29: {
        "name": "rarity",
        "confidence": "high",
        "evidence": "6401 entries, values 2-5. Matches DDO rarity tiers: "
                    "2=Common, 3=Uncommon, 4=Rare, 5=Epic.",
    },
    0x10003D24: {
        "name": "durability",
        "confidence": "medium",
        "evidence": "3898 entries, range 1-169. 169 is standard heavy armor "
                    "durability; other peaks match DDO item types.",
    },
    0x10001BA1: {
        "name": "equipment_slot",
        "confidence": "medium",
        "evidence": "8345 entries, range 2-17. Values: 6(3139), 16(1954), "
                    "2(926), 8(702). Consistent with equipment slot codes.",
    },
    0x10001C59: {
        "name": "item_category",
        "confidence": "medium",
        "evidence": "13217 entries, range 1-12. Dominated by 12(6637) and "
                    "3(4367). Likely item type/category enum.",
    },
    0x100012A2: {
        "name": "effect_value",
        "confidence": "medium",
        "evidence": "4988 entries, range 1-100. Top: 33(1155), 100(1131). "
                    "Numeric magnitude of effect/enchantment.",
    },
    0x10000919: {
        "name": "effect_ref",
        "confidence": "high",
        "evidence": "16,168 total B-tree entries (236 wiki-named items), values "
                    "are 0x70XXXXXX file IDs pointing to type-2 effect definition "
                    "entries. Primary effect_ref slot used by BOP Bracers and "
                    "similar complex items.",
    },
    0x10001C5D: {
        "name": "minimum_level",
        "confidence": "high",
        "evidence": "Confirmed for Black Opal Bracers (ML=31, value=31) and "
                    "cross-checked against dat-identified items. Stored as a "
                    "plain u32 in dup-triple items (not computed at runtime).",
    },
    0x10001390: {
        "name": "effect_ref_2",
        "confidence": "high",
        "evidence": "185 named items, all values are 0x70XXXXXX effect IDs. "
                    "Second-most common effect_ref slot; often paired with "
                    "0x10000919 in the same item (125 items have both).",
    },
    0x100012AC: {
        "name": "effect_ref_3",
        "confidence": "medium",
        "evidence": "49 named items, all 0x70XXXXXX values. Third effect_ref "
                    "slot; frequently appears without the primary slots.",
    },
    0x100012BC: {
        "name": "effect_ref_4",
        "confidence": "medium",
        "evidence": "14 named items, all 0x70XXXXXX values. Fourth effect_ref "
                    "slot; sometimes paired with 0x100012AC.",
    },
    0x10006392: {
        "name": "effect_ref_compound",
        "confidence": "medium",
        "evidence": "Appears as first dup-triple key in rc=19 compound entries "
                    "(37,971 entries). Value is always a 0x70XXXXXX effect FID "
                    "whose low 3 bytes mirror the parent item FID. These entries "
                    "also carry refs[1..2]=0x47XXXXXX spell templates in header.",
    },
    0x10000882: {
        "name": "unknown_compound_0882",
        "confidence": "low",
        "evidence": "Most common first dup-triple key in rc=19 compound entries "
                    "(31,556 of 37,971). Purpose unknown; may be a template or "
                    "class reference for compound game objects.",
    },
    0x100008AC: {
        "name": "is_unique_or_deconstructable",
        "confidence": "low",
        "evidence": "Binary flag: 146/148 named items have val=0, 2 items "
                    "('Incredible Potential Ring Deconstruction') have val=1. "
                    "Likely a boolean flag for deconstruction eligibility or "
                    "unique-drop status.",
    },
    0x10001C5B: {
        "name": "item_subtype",
        "confidence": "low",
        "evidence": "Small enum: values 1-6 (plus rare 16, 20) in 132 named items. "
                    "Adjacent to confirmed item fields 0x10001C5D (min_level). "
                    "val=1: Blue Augment Slots, colorless diamonds, rubies (70 items); "
                    "val=2: Red Slot, abilities, quests (23 items); "
                    "val=3: Small crystals, Purple Slot (13 items); "
                    "val=20: Topaz/Legendary items at ML=55 (3 items). "
                    "Does NOT cleanly encode augment color — too mixed across item "
                    "types. May be 'item_system_category' (1=standard, 2=special, ...).",
    },
    0x10001C5F: {
        "name": "stat_def_id_item",
        "confidence": "low",
        "evidence": "Medium integers (range 369-1574) in 147 named items. Adjacent "
                    "to minimum_level (0x10001C5D) in key space. Values overlap "
                    "with stat_def_ids seen in effect entries (376=Haggle, etc.), "
                    "suggesting this encodes the primary stat_def_id for the item "
                    "as a whole rather than for individual effect sub-entries.",
    },
    0x10001C58: {
        "name": "item_schema_ref",
        "confidence": "low",
        "evidence": "146 named items, all values are 0x10XXXXXX property key IDs "
                    "(e.g. 0x10000914, 0x1000090B). Adjacent to 0x10001C5F and "
                    "0x10001C5D in the item property cluster. Functions as a "
                    "'linked schema' or 'bonus type template' pointer.",
    },
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class NamedEntry:
    """A gamelogic entry matched to its wiki item data."""

    file_id: int
    name: str
    wiki_fields: dict[str, int | float | str]
    properties: list[DecodedProperty]


@dataclass
class KeyMapping:
    """A discovered mapping from property key to human-readable name."""

    key: int
    """Property key, e.g. 0x10000042."""

    name: str
    """Human-readable field name, e.g. 'minimum_level'."""

    confidence: float
    """Fraction of matched entries where the value agreed."""

    match_count: int
    """Number of entries that contributed to this mapping."""

    sample_values: list[int] = field(default_factory=list)
    """A few example values observed for this key."""


@dataclass
class NameMapResult:
    """Results of the property name mapping process."""

    matched_entries: int = 0
    """Wiki items successfully matched to gamelogic entries."""

    unmatched_wiki: int = 0
    """Wiki items not found in the string table / gamelogic."""

    mappings: list[KeyMapping] = field(default_factory=list)
    """Discovered key-to-name mappings, sorted by confidence."""

    unmapped_keys: list[int] = field(default_factory=list)
    """High-frequency keys with no wiki field match."""


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------


def _normalize_name(name: str) -> str:
    """Normalize an item name for fuzzy matching."""
    return name.strip().replace("_", " ").lower()


# ---------------------------------------------------------------------------
# Dup-triple decoder for 0x79XXXXXX entries
# ---------------------------------------------------------------------------


def decode_dup_triple(data: bytes) -> list[DecodedProperty]:
    """Decode property key-value pairs from a dup-triple format entry.

    The 0x79XXXXXX entries in client_gamelogic.dat use a 2-byte-aligned
    format that starts with a 2-byte preamble (the schema type's low
    bytes, e.g. 0x1000 -> bytes 00 10), followed by property records:

        [preamble:2B] [key2:u32][key2:u32][val2:u32] [key2:u32][key2:u32][val2:u32] ...

    Most records duplicate the key: [key][key][value] (12 bytes, "dup-triple").
    Some records appear as lone pairs: [key][value] (8 bytes, no key repeat).
    Zero u32s act as section breaks within the stream.

    This scanner finds dup-triples at 2-byte alignment throughout the
    entry, plus lone key-value pairs not captured by the dup pass.
    """
    props: list[DecodedProperty] = []
    seen_keys: set[int] = set()
    n = len(data)

    # Pass 1: scan for dup-triples at 2-byte alignment
    # The preamble is 2 bytes, so all u32s in the property stream are
    # at even offsets (2, 6, 10, 14, ...). Step by 2 to match.
    i = 0
    while i + 12 <= n:
        k1 = struct.unpack_from("<I", data, i)[0]
        k2 = struct.unpack_from("<I", data, i + 4)[0]
        if k1 == k2 and (k1 >> 24) == 0x10:
            val = struct.unpack_from("<I", data, i + 8)[0]
            if k1 not in seen_keys:
                props.append(DecodedProperty(key=k1, value=val))
                seen_keys.add(k1)
            i += 12
        else:
            i += 2

    # Pass 2: lone key-value pairs (first record in each section)
    i = 0
    while i + 8 <= n:
        k = struct.unpack_from("<I", data, i)[0]
        if (k >> 24) == 0x10 and k not in seen_keys:
            val = struct.unpack_from("<I", data, i + 4)[0]
            # Skip if next u32 equals k (dup-triple, handled above)
            if val != k:
                props.append(DecodedProperty(key=k, value=val))
                seen_keys.add(k)
        i += 2

    return props


# ---------------------------------------------------------------------------
# Step 1: Match wiki items to gamelogic entries
# ---------------------------------------------------------------------------


def match_wiki_to_entries(
    wiki_items: list[dict],
    string_table: dict[int, str],
    archive: DatArchive,
    entries: dict[int, FileEntry],
) -> tuple[list[NamedEntry], int]:
    """Match wiki items to gamelogic entries via deterministic ID mapping.

    The Turbine engine uses a shared 24-bit namespace across archives.
    Item definitions live in the 0x79XXXXXX range of client_gamelogic.dat,
    with corresponding localization strings at 0x25XXXXXX in the English
    archive (same lower 3 bytes).

    These 0x79 entries use a "dup-triple" property encoding (not type-2),
    which decode_dup_triple handles.

    Returns (matched_entries, unmatched_wiki_count).
    """
    # Build reverse lookups
    wiki_by_name: dict[str, dict] = {}
    for item in wiki_items:
        name = item.get("name")
        if name:
            wiki_by_name[_normalize_name(name)] = item

    # Build string table lookup by lower 3 bytes (shared namespace)
    lower_to_name: dict[int, str] = {}
    for file_id, text in string_table.items():
        lower = file_id & 0x00FFFFFF
        norm = _normalize_name(text)
        # Only store if it matches a wiki item (avoids noise)
        if norm in wiki_by_name:
            lower_to_name[lower] = norm

    matched: list[NamedEntry] = []

    for file_id, entry in entries.items():
        # Only process 0x79XXXXXX entries (item definitions)
        if (file_id >> 24) & 0xFF != 0x79:
            continue

        # Check deterministic ID mapping: same lower 3 bytes in English
        lower = file_id & 0x00FFFFFF
        matched_name = lower_to_name.get(lower)
        if matched_name is None:
            continue

        try:
            data = read_entry_data(archive, entry)
        except (ValueError, OSError):
            continue

        if len(data) < 12:
            continue

        # Decode properties from dup-triple format
        properties = decode_dup_triple(data)
        if not properties:
            continue

        wiki_item = wiki_by_name[matched_name]
        named = NamedEntry(
            file_id=file_id,
            name=wiki_item.get("name", matched_name),
            wiki_fields={
                k: v for k, v in wiki_item.items()
                if v is not None and k != "name"
            },
            properties=properties,
        )
        matched.append(named)

    unmatched = len(wiki_by_name) - len({e.name.strip().lower() for e in matched})
    return matched, unmatched


# ---------------------------------------------------------------------------
# Step 2: Correlate property keys to field names
# ---------------------------------------------------------------------------


def correlate_keys(
    named_entries: list[NamedEntry],
    string_table: dict[int, str] | None = None,
    *,
    min_confidence: float = 0.8,
    min_matches: int = 5,
) -> list[KeyMapping]:
    """Find property keys that consistently match wiki field values.

    For numeric wiki fields, checks if a property key's scalar value equals
    the expected wiki value. For string fields, resolves 0x0AXXXXXX property
    values via the string table and compares to wiki text.

    Returns mappings sorted by confidence (descending).
    """
    mappings: list[KeyMapping] = []
    claimed_keys: set[int] = set()

    # --- Numeric fields ---
    for field_name in _NUMERIC_FIELDS:
        # For each property key, collect (actual_value, expected_value) pairs
        candidates: dict[int, list[tuple[int, int]]] = defaultdict(list)

        for entry in named_entries:
            expected = entry.wiki_fields.get(field_name)
            if expected is None or not isinstance(expected, (int, float)):
                continue
            expected_int = int(expected)

            for prop in entry.properties:
                if prop.is_array:
                    continue
                candidates[prop.key].append((prop.value, expected_int))

        # Score each candidate
        best_key = None
        best_confidence = 0.0
        best_count = 0
        best_values: list[int] = []

        for key, pairs in candidates.items():
            if key in claimed_keys:
                continue
            matches = sum(1 for actual, exp in pairs if actual == exp)
            total = len(pairs)
            if matches < min_matches:
                continue
            confidence = matches / total
            if confidence >= min_confidence and confidence > best_confidence:
                best_key = key
                best_confidence = confidence
                best_count = matches
                best_values = sorted({exp for actual, exp in pairs if actual == exp})[:_MAX_SAMPLE_VALUES]

        if best_key is not None:
            mappings.append(KeyMapping(
                key=best_key,
                name=field_name,
                confidence=best_confidence,
                match_count=best_count,
                sample_values=best_values[:_MAX_SAMPLE_VALUES],
            ))
            claimed_keys.add(best_key)

    # --- String fields ---
    if string_table:
        for field_name in _STRING_FIELDS:
            str_candidates: dict[int, list[tuple[str, str]]] = defaultdict(list)

            for entry in named_entries:
                expected_text = entry.wiki_fields.get(field_name)
                if not expected_text or not isinstance(expected_text, str):
                    continue
                norm_expected = _normalize_name(expected_text)

                for prop in entry.properties:
                    if prop.is_array:
                        continue
                    # Check if value looks like a string ref.
                    # 0x79 entries reference the localization archive
                    # directly via 0x25XXXXXX file IDs.
                    if isinstance(prop.value, int):
                        high = (prop.value >> 24) & 0xFF
                        if high in (0x25, 0x0A):
                            resolved = string_table.get(prop.value)
                            if resolved:
                                str_candidates[prop.key].append((
                                    _normalize_name(resolved),
                                    norm_expected,
                                ))

            best_key = None
            best_confidence = 0.0
            best_count = 0

            for key, pairs in str_candidates.items():
                if key in claimed_keys:
                    continue
                matches = sum(1 for actual, exp in pairs if actual == exp)
                total = len(pairs)
                if matches < min_matches:
                    continue
                confidence = matches / total
                if confidence >= min_confidence and confidence > best_confidence:
                    best_key = key
                    best_confidence = confidence
                    best_count = matches

            if best_key is not None:
                mappings.append(KeyMapping(
                    key=best_key,
                    name=field_name,
                    confidence=best_confidence,
                    match_count=best_count,
                    sample_values=[],
                ))
                claimed_keys.add(best_key)

    mappings.sort(key=lambda m: (-m.confidence, -m.match_count))
    return mappings


# ---------------------------------------------------------------------------
# Step 3: Orchestration
# ---------------------------------------------------------------------------


def build_name_map(
    ddo_path: Path,
    wiki_items_path: Path,
    *,
    on_progress: Callable[[str], None] | None = None,
) -> NameMapResult:
    """Run the full name mapping pipeline.

    Args:
        ddo_path: DDO installation directory containing .dat files.
        wiki_items_path: Path to items.json from wiki scraper.
        on_progress: Optional callback for status messages.

    Returns:
        NameMapResult with discovered mappings.
    """
    result = NameMapResult()

    # Load wiki items
    with open(wiki_items_path) as f:
        wiki_items = json.load(f)
    if on_progress:
        on_progress(f"Loaded {len(wiki_items)} wiki items")

    # Load string table from English archive
    english_path = ddo_path / "client_local_English.dat"
    if not english_path.exists():
        logger.error("English archive not found: %s", english_path)
        return result

    if on_progress:
        on_progress("Loading string table from client_local_English.dat...")
    english_archive = DatArchive(english_path)
    english_archive.read_header()
    string_table = load_string_table(english_archive)
    if on_progress:
        on_progress(f"  {len(string_table):,} strings loaded")

    # Scan gamelogic entries
    gamelogic_path = ddo_path / "client_gamelogic.dat"
    if not gamelogic_path.exists():
        logger.error("Gamelogic archive not found: %s", gamelogic_path)
        return result

    if on_progress:
        on_progress("Scanning gamelogic entries...")
    gamelogic_archive = DatArchive(gamelogic_path)
    gamelogic_archive.read_header()
    entries = traverse_btree(gamelogic_archive)
    if on_progress:
        on_progress(f"  {len(entries):,} entries scanned")

    # Match wiki items to gamelogic entries
    if on_progress:
        on_progress("Matching wiki items to gamelogic entries...")
    matched, unmatched = match_wiki_to_entries(
        wiki_items, string_table, gamelogic_archive, entries,
    )
    result.matched_entries = len(matched)
    result.unmatched_wiki = unmatched
    if on_progress:
        on_progress(f"  {len(matched)} matched, {unmatched} unmatched")

    if not matched:
        return result

    # Correlate property keys
    if on_progress:
        on_progress("Correlating property keys...")
    result.mappings = correlate_keys(matched, string_table)
    if on_progress:
        on_progress(f"  {len(result.mappings)} mappings discovered")

    # Collect unmapped high-frequency keys
    mapped_keys = {m.key for m in result.mappings}
    key_freq: dict[int, int] = defaultdict(int)
    for entry in matched:
        for prop in entry.properties:
            if not prop.is_array and prop.key not in mapped_keys:
                key_freq[prop.key] += 1
    result.unmapped_keys = sorted(
        key_freq, key=lambda k: -key_freq[k],
    )[:20]

    return result


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


def format_name_map(result: NameMapResult) -> str:
    """Format name map results as human-readable text."""
    lines: list[str] = []
    lines.append(f"Matched entries: {result.matched_entries}")
    lines.append(f"Unmatched wiki items: {result.unmatched_wiki}")
    lines.append("")

    if result.mappings:
        lines.append(f"Discovered mappings ({len(result.mappings)}):")
        lines.append("-" * 60)
        for m in result.mappings:
            vals = ", ".join(str(v) for v in m.sample_values) if m.sample_values else "-"
            lines.append(
                f"  0x{m.key:08X}  {m.name:<25s} "
                f"conf={m.confidence:.0%}  n={m.match_count}  "
                f"samples=[{vals}]"
            )
    else:
        lines.append("No mappings discovered.")

    if result.unmapped_keys:
        lines.append("")
        lines.append(f"Top unmapped keys ({len(result.unmapped_keys)}):")
        for key in result.unmapped_keys[:10]:
            lines.append(f"  0x{key:08X}")

    return "\n".join(lines)


def format_name_map_json(result: NameMapResult) -> dict:
    """Format name map results as a JSON-serializable dict."""
    return {
        "summary": {
            "matched_entries": result.matched_entries,
            "unmatched_wiki": result.unmatched_wiki,
            "mappings_found": len(result.mappings),
        },
        "mappings": [
            {
                "key": f"0x{m.key:08X}",
                "key_int": m.key,
                "name": m.name,
                "confidence": round(m.confidence, 4),
                "match_count": m.match_count,
                "sample_values": m.sample_values,
            }
            for m in result.mappings
        ],
        "unmapped_keys": [f"0x{k:08X}" for k in result.unmapped_keys],
    }
