"""Parse DDO item definitions from binary game archives.

Reads 0x79XXXXXX entries from client_gamelogic.dat, resolves names
from the 0x25XXXXXX string table in client_local_English.dat, maps
known property keys to human-readable fields, and optionally merges
wiki-scraped data for fields not stored in the binary format.
"""

from __future__ import annotations

import json
import logging
import re
import struct
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from ..dat_parser.archive import DatArchive
from ..dat_parser.btree import traverse_btree
from ..dat_parser.extract import read_entry_data
from ..dat_parser.fid_lookups import EFFECT_FID_LOOKUP
from ..dat_parser.namemap import DISCOVERED_KEYS, decode_dup_triple
from ..dat_parser.probe import decode_effect_entry
from ..dat_parser.strings import load_localization_tables, load_string_table, load_tooltip_table
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

# Float-valued property keys (u32 values reinterpreted as IEEE 754 floats)
_KEY_COOLDOWN = 0x10000B7A       # Cooldown in seconds
_KEY_INTERNAL_LEVEL = 0x10000742  # Encounter/object level (distinct from minimum_level)
_KEY_TIER_MULTIPLIER = 0x10000B60  # Effect scaling tier (1.0, 2.0, 3.0, etc.)

# Integer-valued property keys
_KEY_EFFECT_VALUE = 0x100012A2    # Magnitude of effect/enchantment (range 1-100)

# Sign/scaling multiplier keys
_KEY_SIGN_MULTIPLIER = 0x10000B5C  # +1 (buff) or -1 (debuff)

# Low-volume but named property keys
_KEY_ITEM_SUBTYPE = 0x10001C5B     # Item system category (values 1-6, 132 items)
_KEY_GROUP_REF = 0x10000A48        # Loot group ID (8 distinct values, 155 items)
_KEY_LONG_COOLDOWN = 0x10001013    # Long recharge timer in seconds (300-5400, clickie items)


def _u32_to_float(value: int) -> float | None:
    """Reinterpret a u32 value as an IEEE 754 float, or None if invalid."""
    try:
        result = struct.unpack("<f", struct.pack("<I", value))[0]
    except struct.error:
        return None
    if result != result:  # NaN
        return None
    if abs(result) > 1e6:
        return None
    return result

# Wiki fields confirmed NOT in binary dup-triple property keys.
# Verified 2026-03-22 via dat-namemap with full 8,600-item wiki catalog
# (6,895 matched, 0 new property key mappings discovered).
# NOTE: minimum_level IS from binary (key 0x10001C5D) — not listed here.
_WIKI_ONLY_FIELDS = [
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
    "damage_class",
    "attack_mod",
    "damage_mod",
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

    # Filter: augment gems have item_subtype but no equipment_slot.
    # These are socketable augments, not equippable items.
    if _KEY_ITEM_SUBTYPE in prop_map and _KEY_BY_NAME["equipment_slot"] not in prop_map:
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
    primary_effect_fid: int | None = None
    for prop in properties:
        if prop.key in _EFFECT_REF_KEYS and not prop.is_array:
            if isinstance(prop.value, int) and (prop.value >> 24) & 0xFF == 0x70:
                effect_refs.append(f"0x{prop.value:08X}")
                # Track primary effect_ref (key 0x10000919) for FID lookups
                if prop.key == 0x10000919 and primary_effect_fid is None:
                    primary_effect_fid = prop.value

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
    if primary_effect_fid is not None:
        item["_primary_effect_fid"] = primary_effect_fid

    cooldown_raw = prop_map.get(_KEY_COOLDOWN)
    long_cd_raw = prop_map.get(_KEY_LONG_COOLDOWN)
    if cooldown_raw is not None:
        cooldown_f = _u32_to_float(cooldown_raw)
        if cooldown_f is not None and cooldown_f > 0:
            item["cooldown_seconds"] = round(cooldown_f, 1)
    if long_cd_raw is not None:
        long_cd_f = _u32_to_float(long_cd_raw)
        if long_cd_f is not None and long_cd_f > 0:
            # Use the longer cooldown if it's bigger than the short one
            existing = item.get("cooldown_seconds", 0)
            if long_cd_f > existing:
                item["cooldown_seconds"] = round(long_cd_f, 1)

    level_raw = prop_map.get(_KEY_INTERNAL_LEVEL)
    if level_raw is not None:
        level_f = _u32_to_float(level_raw)
        if level_f is not None and 0 < level_f < 1000:
            item["internal_level"] = round(level_f)

    tier_raw = prop_map.get(_KEY_TIER_MULTIPLIER)
    if tier_raw is not None:
        tier_f = _u32_to_float(tier_raw)
        if tier_f is not None and abs(tier_f) < 100:
            item["tier_multiplier"] = round(tier_f, 1)

    effect_val = prop_map.get(_KEY_EFFECT_VALUE)
    if effect_val is not None and 0 < effect_val <= 1000:
        item["effect_value"] = effect_val

    sign_raw = prop_map.get(_KEY_SIGN_MULTIPLIER)
    if sign_raw is not None:
        sign_f = _u32_to_float(sign_raw)
        if sign_f is not None and sign_f in (1.0, -1.0):
            item["is_debuff"] = sign_f < 0

    subtype = prop_map.get(_KEY_ITEM_SUBTYPE)
    if subtype is not None and 0 < subtype < 100:
        item["item_subtype"] = subtype

    group_ref = prop_map.get(_KEY_GROUP_REF)
    if group_ref is not None and group_ref != 0:
        item["group_ref"] = group_ref

    return item


def _merge_wiki_data(
    binary_items: list[dict],
    wiki_items: list[dict],
) -> list[dict]:
    """Overlay wiki fields onto binary items matched by normalized name.

    - Matched: binary dict + wiki fields where binary is None/absent.
      Binary values win when both sources have the same field.
      Adds wiki_url and marks data_source='both'.
    - Binary-only: kept as-is, data_source='binary'.
    - Wiki-only: appended with id=None, data_source='wiki'.

    Sets ``_wiki_fields`` on each item to track which fields came from wiki.
    """
    import html as html_mod

    # Build normalized-name -> index for binary items
    binary_by_name: dict[str, int] = {}
    for i, item in enumerate(binary_items):
        if item.get("name"):
            norm = _normalize_name(item["name"])
            if norm not in binary_by_name:
                binary_by_name[norm] = i

    merged = list(binary_items)

    # Mark all binary items as binary source
    for item in merged:
        item["data_source"] = "binary"
        item["dat_id"] = item.get("id")  # rename id -> dat_id for DB

    matched_indices: set[int] = set()

    for wiki_item in wiki_items:
        wiki_name = wiki_item.get("name")
        if not wiki_name:
            continue

        # Try matching with HTML entity decoding and Legendary prefix
        clean = html_mod.unescape(wiki_name)
        norm = _normalize_name(clean)
        idx = binary_by_name.get(norm)
        if idx is None and not norm.startswith("legendary "):
            idx = binary_by_name.get("legendary " + norm)
        if idx is None and norm.startswith("legendary "):
            idx = binary_by_name.get(norm[len("legendary "):])

        if idx is not None:
            matched_indices.add(idx)
            target = merged[idx]
            wiki_fields = []
            for field in _WIKI_ONLY_FIELDS:
                if field not in target or target[field] is None:
                    wiki_val = wiki_item.get(field)
                    if wiki_val is not None:
                        target[field] = wiki_val
                        wiki_fields.append(field)
            # Enchantments always come from wiki
            if wiki_item.get("enchantments"):
                target["enchantments"] = wiki_item["enchantments"]
                wiki_fields.append("enchantments")
            # Wiki "slot" field maps to equipment_slot for non-weapon items
            if target.get("equipment_slot") is None and wiki_item.get("slot"):
                target["equipment_slot"] = wiki_item["slot"]
                wiki_fields.append("equipment_slot(slot)")
            target["wiki_url"] = wiki_item.get("wiki_url") or _wiki_url(wiki_name)
            target["data_source"] = "both"
            target["_wiki_fields"] = wiki_fields
        else:
            # Wiki-only item
            wiki_entry = dict(wiki_item)
            wiki_entry["dat_id"] = None
            wiki_entry["data_source"] = "wiki"
            if not wiki_entry.get("wiki_url"):
                wiki_entry["wiki_url"] = _wiki_url(wiki_name)
            merged.append(wiki_entry)

    return merged


def parse_items(
    ddo_path: Path,
    *,
    wiki_items_path: Path | None = None,
    wiki_items: list[dict] | None = None,
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

    if on_progress:
        on_progress("Loading tooltip table...")
    tooltip_table = load_tooltip_table(english_archive)
    if on_progress:
        on_progress(f"  {len(tooltip_table):,} tooltips loaded")

    if on_progress:
        on_progress("Loading localization tables (enchant names, descriptions)...")
    loc_tables = load_localization_tables(english_archive)
    enchant_names = loc_tables["enchant_name"]
    enchant_suffixes = loc_tables["enchant_suffix"]
    if on_progress:
        on_progress(
            f"  {len(enchant_names):,} enchant names, "
            f"{len(enchant_suffixes):,} enchant suffixes loaded"
        )

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

        # Filter garbled names (raw localization entries with embedded formatting).
        # Valid DDO item names use ASCII/Latin-1 only; structured localization
        # entries that failed to parse contain chars above U+00FF.
        if len(name) > 100 or any(ord(c) > 0xFF for c in name[:30]):
            skipped += 1
            continue

        try:
            data = read_entry_data(gamelogic_archive, entry)
        except (ValueError, OSError):
            skipped += 1
            continue

        item = _decode_item_entry(data, file_id, name)
        if item is not None:
            # Look up localization data via same 0x25XXXXXX namespace as name
            tooltip = tooltip_table.get(str_id)
            if tooltip:
                item["tooltip"] = tooltip
            enchant = enchant_names.get(str_id)
            if enchant:
                item["enchant_name"] = enchant
            suffix = enchant_suffixes.get(str_id)
            if suffix:
                item["enchant_suffix"] = suffix
            items.append(item)

    if on_progress:
        on_progress(f"  {len(items):,} items decoded ({skipped:,} skipped)")

    # Resolve effect refs → decoded bonus dicts
    effects_decoded = 0
    fid_resolved = 0
    for item in items:
        effect_refs = item.pop("_effect_refs", [])
        bonuses: list[dict] = []
        type167_refs: list[str] = []
        for ref_str in effect_refs:
            ref_id = int(ref_str, 16)
            effect_entry = entries.get(ref_id)
            if effect_entry is None:
                continue
            try:
                effect_data = read_entry_data(gamelogic_archive, effect_entry)
            except (ValueError, OSError):
                continue
            # Track type-167 refs for localization name parsing
            if len(effect_data) > 8:
                et = struct.unpack_from("<I", effect_data, 5)[0]
                if et == 167:
                    type167_refs.append(ref_str)
            effect_desc = decode_effect_entry(effect_data)
            if effect_desc is not None:
                # FID lookup (primary): always preferred over content-based
                # STAT_DEF_IDS (97 entries, 0 conflicts vs 10 entries with
                # false positives like sid 376 = "Haggle" on all type-53).
                fid_result = EFFECT_FID_LOOKUP.get(ref_id)
                if fid_result:
                    stat, bt = fid_result
                    effect_desc["stat"] = stat
                    effect_desc["bonus_type"] = bt
                    effect_desc["_resolution_method"] = "fid_lookup"
                    fid_resolved += 1
                elif effect_desc.get("stat") is not None:
                    effect_desc["_resolution_method"] = "stat_def_ids"
                # Grab localization name as the in-game description text
                lower = ref_id & 0x00FFFFFF
                eff_name = string_table.get(0x25000000 | lower)
                if eff_name:
                    effect_desc["_description"] = eff_name.strip()
                bonuses.append(effect_desc)
        if bonuses:
            item["_bonuses"] = bonuses
            effects_decoded += len(bonuses)
        if type167_refs:
            item["_effect_refs_167"] = type167_refs
    if on_progress:
        on_progress(f"  {effects_decoded:,} effect bonuses decoded ({fid_resolved} via FID lookup)")

    # Resolve bonuses from type-167 localization names
    # Type-167 entries are referenced via effect_ref_11/12/13 and their
    # localization names contain human-readable bonuses like "+10 Seeker".
    # Only accept names matching known stat names from the DB seed.
    _known_stats = {
        "Strength", "Dexterity", "Constitution", "Intelligence", "Wisdom", "Charisma",
        "Melee Power", "Ranged Power", "Attack Bonus", "Damage Bonus", "Hit Points",
        "Sneak Attack Dice", "Seeker", "Deadly", "Accuracy", "Deception", "Speed",
        "Doublestrike", "Doubleshot", "Combat Mastery", "Armor Class",
        "Physical Resistance Rating", "Magical Resistance Rating", "Fortification",
        "Dodge", "Fortitude Save", "Reflex Save", "Will Save", "Spell Resistance",
        "Physical Sheltering", "Magical Sheltering", "Sheltering", "Natural Armor",
        "Protection", "Resistance", "Spell Points", "Spell Penetration",
        "Universal Spell Power", "Fire Spell Power", "Cold Spell Power",
        "Electric Spell Power", "Acid Spell Power", "Sonic Spell Power",
        "Light Spell Power", "Force Spell Power", "Negative Spell Power",
        "Positive Spell Power", "Repair Spell Power", "Wizardry",
        "Healing Amplification", "Repair Amplification", "Well Rounded",
        "Enhancement Bonus", "Spell Focus Mastery",
    }
    _known_bonus_types = {
        "Enhancement", "Insightful", "Insight", "Quality", "Exceptional",
        "Competence", "Luck", "Sacred", "Profane", "Artifact",
    }
    type167_resolved = 0
    for item in items:
        for ref_str in item.pop("_effect_refs_167", []):
            ref_id = int(ref_str, 16)
            lower = ref_id & 0x00FFFFFF
            eff_name = string_table.get(0x25000000 | lower)
            if not eff_name or len(eff_name) > 80:
                continue
            m = re.match(r'^\+(\d+)\s+(.+)$', eff_name.strip())
            if not m:
                continue
            value = int(m.group(1))
            rest = m.group(2).strip()
            if value < 1 or value > 50:
                continue
            # Try "BonusType Stat" or just "Stat"
            bonus_type = "Enhancement"
            stat_name = rest
            for bt in _known_bonus_types:
                if rest.startswith(bt + " "):
                    bonus_type = bt
                    stat_name = rest[len(bt) + 1:]
                    break
            if stat_name not in _known_stats:
                continue
            bonuses = item.setdefault("_bonuses", [])
            bonuses.append({
                "stat": stat_name,
                "magnitude": value,
                "bonus_type": bonus_type,
                "_resolution_method": "type167_name",
                "_description": eff_name.strip(),
            })
            type167_resolved += 1
    if on_progress and type167_resolved:
        on_progress(f"  {type167_resolved:,} bonuses from type-167 localization names")

    # Resolve item-level fields from FID item lookup (material, damage, augment_count)
    fid_item_lookup_path = Path(__file__).parent.parent / "dat_parser" / "fid_item_lookup.json"
    fid_item_resolved = 0
    if fid_item_lookup_path.exists():
        with open(fid_item_lookup_path) as f:
            fid_item_lookup: dict[str, dict] = json.load(f)
        for item in items:
            pfid = item.pop("_primary_effect_fid", None)
            if not pfid:
                continue
            fid_key = f"0x{pfid:08X}"
            fid_data = fid_item_lookup.get(fid_key)
            if not fid_data:
                continue
            # Overlay FID-resolved fields where item has None
            for field in ("material", "damage", "augment_count", "weight", "binding",
                         "base_value", "handedness", "proficiency", "weapon_type", "critical",
                         "damage_class", "attack_mod", "damage_mod", "slot"):
                if item.get(field) is None and field in fid_data:
                    item[field] = fid_data[field]
                    fid_item_resolved += 1
        if on_progress:
            on_progress(f"  {fid_item_resolved:,} item fields resolved via FID item lookup")

    # Merge wiki data if available
    wiki_data = wiki_items
    if wiki_data is None and wiki_items_path and wiki_items_path.exists():
        if on_progress:
            on_progress(f"Loading wiki data from {wiki_items_path}...")
        with open(wiki_items_path) as f:
            wiki_data = json.load(f)
    if wiki_data:
        if on_progress:
            on_progress(f"Merging {len(wiki_data):,} wiki items...")
        items = _merge_wiki_data(items, wiki_data)
        if on_progress:
            on_progress(f"  {len(items):,} items after merge")

    return items


def export_items_json(items: list[dict], output: Path) -> None:
    """Export parsed items to a JSON file."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        json.dump(items, f, indent=2)
