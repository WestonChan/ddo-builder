"""Parse DDO feat definitions from binary game archives.

Reads 0x79XXXXXX entries from client_gamelogic.dat, resolves names
from the 0x25XXXXXX string table in client_local_English.dat, and
returns all non-item entries (feats, abilities) with their dat_id.
Optionally merges wiki-scraped data for fields not in the binary format.
"""

from __future__ import annotations

import json
import logging
import struct
from collections.abc import Callable
from pathlib import Path

from ..dat_parser.archive import DatArchive
from ..dat_parser.btree import traverse_btree
from ..dat_parser.extract import read_entry_data
from ..dat_parser.namemap import DISCOVERED_KEYS, decode_dup_triple
from ..dat_parser.strings import load_localization_tables, load_string_table, load_tooltip_table

logger = logging.getLogger(__name__)

# Property key reverse lookup
_KEY_BY_NAME: dict[str, int] = {
    info["name"]: key for key, info in DISCOVERED_KEYS.items()
}

# Item indicator keys — entries with any of these are items, not feats
_ITEM_INDICATOR_KEYS: frozenset[int] = frozenset({
    _KEY_BY_NAME["equipment_slot"],
    _KEY_BY_NAME["rarity"],
    _KEY_BY_NAME["item_category"],
})

_KEY_DAMAGE_DICE = _KEY_BY_NAME["damage_dice_notation"]

# Float-valued property keys (u32 values reinterpreted as IEEE 754 floats)
_KEY_COOLDOWN = 0x10000B7A   # Cooldown in seconds (mostly 15.0)
_KEY_DURATION = 0x10000907   # Duration in seconds (-1 = permanent)
_KEY_TIER_QUARTER = 0x10000867  # Difficulty tier fraction: 0.25 (Normal)
_KEY_TIER_HALF = 0x10000868     # Difficulty tier fraction: 0.50 (Hard)
_KEY_TIER_THREE_Q = 0x10000869  # Difficulty tier fraction: 0.75 (Elite)

# Feat type flag keys — discovered via 562-feat wiki cross-reference.
# Presence of ANY key in each set indicates the feat has that type.
_ACTIVE_FEAT_KEYS: frozenset[int] = frozenset({
    0x10000D81, 0x10000829, 0x10002878, 0x100008E2,
    0x100020D0, 0x100020D1, 0x100059F6, 0x10006F7C, 0x10006F7D,
})
_STANCE_FEAT_KEYS: frozenset[int] = frozenset({
    0x100024D1, 0x10000771,
})
_FREE_FEAT_KEY = 0x100040FB


def _u32_to_float(value: int) -> float | None:
    """Reinterpret a u32 value as an IEEE 754 float, or None if invalid."""
    try:
        result = struct.unpack("<f", struct.pack("<I", value))[0]
    except struct.error:
        return None
    if result != result:  # NaN
        return None
    if abs(result) > 1e6:  # Unreasonably large
        return None
    return result


def _decode_damage_dice(value: int) -> str | None:
    """Decode packed u32 damage dice notation.

    Encoding: byte[0]=bonus, bytes[1..3]=ASCII dice string.
    Example: 0x32643205 → "2d2+5"  (bonus=5, dice="2d2")
             0x34643103 → "1d4+3"  (bonus=3, dice="1d4")
    """
    bonus = value & 0xFF
    dice_bytes = bytes([
        (value >> 8) & 0xFF,
        (value >> 16) & 0xFF,
        (value >> 24) & 0xFF,
    ])
    try:
        dice_str = dice_bytes.decode("ascii").strip("\x00")
    except (UnicodeDecodeError, ValueError):
        return None
    if not dice_str:
        return None
    return f"{dice_str}+{bonus}" if bonus else dice_str


def _normalize_name(name: str) -> str:
    """Normalize a feat name for fuzzy matching."""
    return name.strip().replace("_", " ").lower()


def _decode_feat_entry(
    data: bytes,
    file_id: int,
    name: str,
) -> dict | None:
    """Decode one 0x79XXXXXX entry into a feat dict.

    Returns None if the entry has item indicator keys (equipment_slot,
    rarity, or item_category) — those belong to the items parser.
    Also returns None if the entry has no decodable properties.
    """
    properties = decode_dup_triple(data)
    if not properties:
        return None

    prop_map: dict[int, int] = {}
    for prop in properties:
        if not prop.is_array:
            prop_map[prop.key] = prop.value

    # If any item indicator key is present, this entry is an item — skip
    if _ITEM_INDICATOR_KEYS.intersection(prop_map):
        return None

    feat: dict = {
        "dat_id": f"0x{file_id:08X}",
        "name": name,
    }

    dice_raw = prop_map.get(_KEY_DAMAGE_DICE)
    if dice_raw is not None:
        feat["damage_dice_notation"] = _decode_damage_dice(dice_raw)

    cooldown_raw = prop_map.get(_KEY_COOLDOWN)
    if cooldown_raw is not None:
        cooldown_f = _u32_to_float(cooldown_raw)
        if cooldown_f is not None and cooldown_f > 0:
            feat["cooldown_seconds"] = round(cooldown_f, 1)

    duration_raw = prop_map.get(_KEY_DURATION)
    if duration_raw is not None:
        duration_f = _u32_to_float(duration_raw)
        if duration_f is not None:
            feat["duration_seconds"] = round(duration_f, 1)

    # Difficulty tier scaling — presence indicates the feat scales by difficulty
    has_tiers = (
        _KEY_TIER_QUARTER in prop_map
        or _KEY_TIER_HALF in prop_map
        or _KEY_TIER_THREE_Q in prop_map
    )
    if has_tiers:
        feat["scales_with_difficulty"] = True

    # Feat type flags from property key presence
    if _ACTIVE_FEAT_KEYS.intersection(prop_map):
        feat["is_active_binary"] = True
    if _STANCE_FEAT_KEYS.intersection(prop_map):
        feat["is_stance_binary"] = True
    if _FREE_FEAT_KEY in prop_map:
        feat["is_free_binary"] = True

    return feat


def _merge_wiki_feats(
    binary_feats: list[dict],
    wiki_feats: list[dict],
) -> list[dict]:
    """Merge wiki feat data onto binary-extracted feats matched by name.

    - Matched: binary dict gets all wiki fields overlaid where binary
      has None or the key is absent. dat_id from binary is preserved.
    - Unmatched binary entries (NPCs, abilities without a wiki page):
      discarded — not appended to the result.
    - Wiki-only feats (no binary match): kept with dat_id=None.

    Returns feats in wiki ordering, with wiki-only feats at the end.
    """
    binary_by_name: dict[str, int] = {}
    for i, feat in enumerate(binary_feats):
        if feat.get("name"):
            norm = _normalize_name(feat["name"])
            if norm not in binary_by_name:
                binary_by_name[norm] = i

    merged: list[dict] = []
    for wiki_feat in wiki_feats:
        wiki_name = wiki_feat.get("name")
        if not wiki_name:
            continue
        norm = _normalize_name(wiki_name)
        idx = binary_by_name.get(norm)

        if idx is not None:
            target = dict(binary_feats[idx])
            for field, wiki_value in wiki_feat.items():
                if field not in target or target[field] is None:
                    target[field] = wiki_value
            merged.append(target)
        else:
            wiki_entry = dict(wiki_feat)
            wiki_entry["dat_id"] = None
            merged.append(wiki_entry)

    return merged


def parse_feats(
    ddo_path: Path,
    *,
    wiki_feats_path: Path | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> list[dict]:
    """Parse feat definitions from DDO game archives.

    Reads 0x79XXXXXX entries from client_gamelogic.dat, resolves names
    from client_local_English.dat, and returns all non-item entries
    (feats, abilities) with their dat_id. Optionally merges wiki data
    to enrich results and filter to wiki-known feats only.

    Args:
        ddo_path: DDO installation directory containing .dat files.
        wiki_feats_path: Path to wiki feats.json for merge (None = skip).
        on_progress: Optional callback for progress messages.

    Returns:
        List of feat dicts. With wiki merge: filtered to wiki-known feats
        with dat_id populated for binary matches. Without wiki merge: all
        non-item 0x79 entries with a string-table name.
    """
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
        on_progress("Loading localization tables...")
    loc_tables = load_localization_tables(english_archive)
    description_table = loc_tables["description"]
    enchant_names = loc_tables["enchant_name"]
    if on_progress:
        on_progress(f"  {len(description_table):,} descriptions, {len(enchant_names):,} enchant names")

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

    feats: list[dict] = []
    skipped = 0

    for file_id, entry in entries.items():
        if (file_id >> 24) & 0xFF != 0x79:
            continue

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

        feat = _decode_feat_entry(data, file_id, name)
        if feat is not None:
            tooltip = tooltip_table.get(str_id)
            if tooltip:
                feat["tooltip"] = tooltip
            desc = description_table.get(str_id)
            if desc:
                feat["binary_description"] = desc
            enchant = enchant_names.get(str_id)
            if enchant:
                feat["enchant_name"] = enchant
            feats.append(feat)

    if on_progress:
        on_progress(
            f"  {len(feats):,} feat-like entries decoded ({skipped:,} skipped)"
        )

    if wiki_feats_path and wiki_feats_path.exists():
        if on_progress:
            on_progress(f"Merging wiki data from {wiki_feats_path}...")
        with open(wiki_feats_path) as f:
            wiki_feats_data = json.load(f)
        feats = _merge_wiki_feats(feats, wiki_feats_data)
        if on_progress:
            on_progress(f"  {len(feats):,} feats after merge")

    return feats


def export_feats_json(feats: list[dict], output: Path) -> None:
    """Export parsed feats to a JSON file."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        json.dump(feats, f, indent=2)
