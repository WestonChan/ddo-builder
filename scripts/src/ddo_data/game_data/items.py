"""Parse DDO item definitions from binary game archives.

Reads 0x79XXXXXX entries from client_gamelogic.dat, resolves names
from the 0x25XXXXXX string table in client_local_English.dat, maps
known property keys to human-readable fields, and optionally merges
wiki-scraped data for fields not stored in the binary format.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from ..dat_parser.archive import DatArchive
from ..dat_parser.btree import traverse_btree
from ..dat_parser.extract import read_entry_data
from ..dat_parser.namemap import DISCOVERED_KEYS, decode_dup_triple
from ..dat_parser.strings import load_string_table
from .enums import (
    EQUIPMENT_SLOTS,
    ITEM_CATEGORIES,
    RARITY_TIERS,
    resolve_enum,
)

logger = logging.getLogger(__name__)

# Property keys by name (reverse lookup from DISCOVERED_KEYS)
_KEY_BY_NAME: dict[str, int] = {
    info["name"]: key for key, info in DISCOVERED_KEYS.items()
}

# All effect_ref slot keys (0x70XXXXXX file IDs referencing effect entries)
_EFFECT_REF_KEYS: frozenset[int] = frozenset(
    key for key, info in DISCOVERED_KEYS.items()
    if info["name"].startswith("effect_ref")
)

# Keys that indicate an entry is an item (not a quest object, NPC, etc.)
_ITEM_INDICATOR_KEYS = {
    _KEY_BY_NAME["equipment_slot"],
    _KEY_BY_NAME["rarity"],
    _KEY_BY_NAME["item_category"],
}

# Wiki fields that the binary format does not provide
_WIKI_ONLY_FIELDS = [
    "minimum_level",
    "item_type",
    "enchantments",
    "augment_slots",
    "damage",
    "critical",
    "description",
    "quest",
    "set_name",
    "material",
    "binding",
    "weight",
    "enhancement_bonus",
    "armor_bonus",
    "max_dex_bonus",
    "base_value",
    "handedness",
    "proficiency",
    "weapon_type",
    "hardness",
]


def _normalize_name(name: str) -> str:
    """Normalize an item name for fuzzy matching."""
    return name.strip().replace("_", " ").lower()


def _wiki_url(name: str) -> str:
    """Build a DDO Wiki URL from an item name."""
    slug = quote(name.replace(" ", "_"), safe="_/:()'-,")
    return f"https://ddowiki.com/page/Item:{slug}"


def _decode_item_entry(
    data: bytes,
    file_id: int,
    name: str,
) -> dict | None:
    """Decode one 0x79XXXXXX entry into an item dict.

    Uses decode_dup_triple() to extract properties, maps known keys
    via DISCOVERED_KEYS, and resolves enum values to labels.

    Returns None if the entry has no item-like properties (i.e. none of
    equipment_slot, rarity, or item_category keys are present).
    """
    properties = decode_dup_triple(data)
    if not properties:
        return None

    # Build key -> value lookup
    prop_map: dict[int, int] = {}
    for prop in properties:
        if not prop.is_array:
            prop_map[prop.key] = prop.value

    # Filter: must have at least one item indicator key
    if not _ITEM_INDICATOR_KEYS.intersection(prop_map):
        return None

    # Extract known fields
    rarity_code = prop_map.get(_KEY_BY_NAME["rarity"])
    slot_code = prop_map.get(_KEY_BY_NAME["equipment_slot"])
    category_code = prop_map.get(_KEY_BY_NAME["item_category"])
    level = prop_map.get(_KEY_BY_NAME["level"])
    durability = prop_map.get(_KEY_BY_NAME["durability"])
    minimum_level = prop_map.get(_KEY_BY_NAME["minimum_level"])

    # Collect effect refs from all 28+ effect_ref slots (0x70XXXXXX)
    effect_refs: list[str] = []
    for prop in properties:
        if prop.key in _EFFECT_REF_KEYS and not prop.is_array:
            if isinstance(prop.value, int) and (prop.value >> 24) & 0xFF == 0x70:
                effect_refs.append(f"0x{prop.value:08X}")

    item: dict = {
        "id": f"0x{file_id:08X}",
        "name": name,
        "rarity": resolve_enum(RARITY_TIERS, rarity_code) if rarity_code is not None else None,
        "durability": durability,
        "equipment_slot": resolve_enum(EQUIPMENT_SLOTS, slot_code) if slot_code is not None else None,
        "item_category": resolve_enum(ITEM_CATEGORIES, category_code) if category_code is not None else None,
        "level": level,
        "minimum_level": minimum_level,
    }

    if effect_refs:
        item["_effect_refs"] = effect_refs

    return item


def _merge_wiki_data(
    binary_items: list[dict],
    wiki_items: list[dict],
) -> list[dict]:
    """Overlay wiki fields onto binary items matched by normalized name.

    - Matched: binary dict + wiki fields where binary is None/absent.
      Binary values win when both sources have the same field.
      Adds wiki_url from the matched wiki item name.
    - Binary-only: kept as-is (no wiki_url).
    - Wiki-only: appended with id=None, includes wiki_url.
    """
    # Build normalized-name -> index for binary items
    binary_by_name: dict[str, int] = {}
    for i, item in enumerate(binary_items):
        if item.get("name"):
            norm = _normalize_name(item["name"])
            if norm not in binary_by_name:
                binary_by_name[norm] = i

    merged = list(binary_items)

    for wiki_item in wiki_items:
        wiki_name = wiki_item.get("name")
        if not wiki_name:
            continue

        norm = _normalize_name(wiki_name)
        idx = binary_by_name.get(norm)

        if idx is not None:
            # Merge: overlay wiki fields where binary has None or lacks key
            target = merged[idx]
            for field in _WIKI_ONLY_FIELDS:
                if field not in target or target[field] is None:
                    wiki_val = wiki_item.get(field)
                    if wiki_val is not None:
                        target[field] = wiki_val
            target["wiki_url"] = _wiki_url(wiki_name)
        else:
            # Wiki-only item
            wiki_entry = dict(wiki_item)
            wiki_entry["id"] = None
            wiki_entry["wiki_url"] = _wiki_url(wiki_name)
            merged.append(wiki_entry)

    return merged


def parse_items(
    ddo_path: Path,
    *,
    wiki_items_path: Path | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> list[dict]:
    """Parse item definitions from DDO game archives.

    Reads 0x79XXXXXX entries from client_gamelogic.dat, resolves names
    from client_local_English.dat, applies known property key mappings,
    and optionally merges wiki data.

    Args:
        ddo_path: DDO installation directory containing .dat files.
        wiki_items_path: Path to wiki items.json for merge (None = skip).
        on_progress: Optional callback for status messages.

    Returns:
        List of item dicts with binary + wiki fields merged.
    """
    # Load English string table
    english_path = ddo_path / "client_local_English.dat"
    if not english_path.exists():
        logger.warning("English archive not found: %s", english_path)
        return []

    if on_progress:
        on_progress("Loading string table...")
    english_archive = DatArchive(english_path)
    english_archive.read_header()
    string_table = load_string_table(english_archive)
    if on_progress:
        on_progress(f"  {len(string_table):,} strings loaded")

    # Load gamelogic entries
    gamelogic_path = ddo_path / "client_gamelogic.dat"
    if not gamelogic_path.exists():
        logger.warning("Gamelogic archive not found: %s", gamelogic_path)
        return []

    if on_progress:
        on_progress("Scanning gamelogic entries...")
    gamelogic_archive = DatArchive(gamelogic_path)
    gamelogic_archive.read_header()
    entries = traverse_btree(gamelogic_archive)
    if on_progress:
        on_progress(f"  {len(entries):,} entries scanned")

    # Decode items from 0x79 entries
    items: list[dict] = []
    skipped = 0

    for file_id, entry in entries.items():
        if (file_id >> 24) & 0xFF != 0x79:
            continue

        # Resolve name from string table (shared lower 3 bytes)
        lower = file_id & 0x00FFFFFF
        str_id = 0x25000000 | lower
        name = string_table.get(str_id)
        if not name:
            skipped += 1
            continue

        try:
            data = read_entry_data(gamelogic_archive, entry)
        except (ValueError, OSError):
            skipped += 1
            continue

        item = _decode_item_entry(data, file_id, name)
        if item is not None:
            items.append(item)

    if on_progress:
        on_progress(f"  {len(items):,} items decoded ({skipped:,} skipped)")

    # Merge wiki data if available
    if wiki_items_path and wiki_items_path.exists():
        if on_progress:
            on_progress(f"Merging wiki data from {wiki_items_path}...")
        with open(wiki_items_path) as f:
            wiki_items = json.load(f)
        items = _merge_wiki_data(items, wiki_items)
        if on_progress:
            on_progress(f"  {len(items):,} items after merge")

    return items


def export_items_json(items: list[dict], output: Path) -> None:
    """Export parsed items to a JSON file."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        json.dump(items, f, indent=2)
