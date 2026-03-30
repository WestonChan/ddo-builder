"""Insert functions for populating the DDO game database from scraper dicts."""

from __future__ import annotations

import logging

from ddo_data.enums import (
    DataSource, Handedness, ItemCategory, ResolutionMethod, TreeType,
)
import re
import sqlite3

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Normalisation maps (wiki strings → schema CHECK constraint values)
# ---------------------------------------------------------------------------

# Wiki {{Named item|TYPE}} positional arg → items.item_category CHECK value
_ITEM_CATEGORY_MAP: dict[str, str] = {
    "weapon":      ItemCategory.WEAPON,
    "armor":       ItemCategory.ARMOR,
    "shield":      ItemCategory.SHIELD,
    "jewelry":     ItemCategory.JEWELRY,
    "ring":        ItemCategory.JEWELRY,
    "necklace":    ItemCategory.JEWELRY,
    "bracelet":    ItemCategory.JEWELRY,
    "trinket":     ItemCategory.JEWELRY,
    "accessory":   ItemCategory.JEWELRY,
    "clothing":    ItemCategory.CLOTHING,
    "outfit":      ItemCategory.CLOTHING,
    "wondrous":    ItemCategory.WONDROUS,
    "potion":      ItemCategory.POTION,
    "scroll":      ItemCategory.SCROLL,
    "wand":        ItemCategory.WAND,
    "component":   ItemCategory.COMPONENT,
    "collectible": ItemCategory.COLLECTIBLE,
    "consumable":  ItemCategory.CONSUMABLE,
}

# Wiki handedness strings → item_weapon_stats.handedness CHECK value
_HANDEDNESS_MAP: dict[str, str] = {
    "one-handed":  Handedness.ONE_HANDED,
    "one handed":  Handedness.ONE_HANDED,
    "1-handed":    Handedness.ONE_HANDED,
    "two-handed":  Handedness.TWO_HANDED,
    "two handed":  Handedness.TWO_HANDED,
    "2-handed":    Handedness.TWO_HANDED,
    "off-hand":    Handedness.OFF_HAND,
    "off hand":    Handedness.OFF_HAND,
    "offhand":     Handedness.OFF_HAND,
    "thrown":      Handedness.THROWN,
}

# ap_pool derived from tree_type
_AP_POOL_MAP: dict[str, str] = {
    TreeType.CLASS:     "heroic",
    TreeType.UNIVERSAL: "heroic",
    TreeType.RACIAL:    "racial",
    TreeType.REAPER:    "reaper",
    TreeType.DESTINY:   "legendary",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_item_category(raw: str | None) -> str | None:
    if not raw:
        return None
    return _ITEM_CATEGORY_MAP.get(raw.strip().lower())


def _normalise_handedness(raw: str | None) -> str | None:
    if not raw:
        return None
    return _HANDEDNESS_MAP.get(raw.strip().lower())


def _parse_enchantment(text: str) -> list[dict]:
    """Parse a wiki enchantment string into structured bonus dicts.

    Returns a list (handles composite stats that split into multiple bonuses).
    Returns empty list if unparseable.
    """
    from ..dat_parser.effects import parse_enchantment_string_multi

    return parse_enchantment_string_multi(text)


def _get_named_enchantment_effects(enchantment_name: str) -> list[dict]:
    """Get fixed bonus/penalty effects for a named enchantment.

    Returns additional bonus dicts from NAMED_ENCHANTMENT_EFFECTS lookup.
    Two types:
    - Numeric: has stat + value + bonus_type -> stored as stat bonus
    - Description-only: has description, stat=None -> stored with NULL stat_id
    """
    from ..dat_parser.effects import NAMED_ENCHANTMENT_EFFECTS

    effects = NAMED_ENCHANTMENT_EFFECTS.get(enchantment_name, [])
    result = []
    for e in effects:
        if e.get("stat") is not None and e.get("value") is not None:
            result.append({
                "value": e["value"], "bonus_type": e["bonus_type"], "stat": e["stat"],
            })
        elif e.get("description"):
            result.append({
                "value": None, "bonus_type": None, "stat": None,
                "description": e["description"],
            })
    return result


def _parse_effect(text: str) -> dict | None:
    """Parse a wiki enchantment string as a weapon/armor effect."""
    from ..dat_parser.effects import parse_effect_template

    return parse_effect_template(text)


def _is_metadata(text: str) -> bool:
    """Check if a wiki enchantment string is item metadata (augments, sets, etc.)."""
    from ..dat_parser.effects import is_metadata_template

    return is_metadata_template(text)


def _parse_saving_throw(text: str | None) -> tuple[str | None, str | None]:
    """Parse saving throw text into (save_type, save_effect).

    Examples:
        "Reflex save takes half damage" -> ("Reflex", "half")
        "Will save negates" -> ("Will", "negates")
        "Fortitude save negates Strength damage" -> ("Fortitude", "negates")
        "None" -> (None, None)
    """
    if not text:
        return None, None
    t = text.strip().lower()
    if t in ("none", "no", ""):
        return None, None
    save_type = None
    if "will" in t:
        save_type = "Will"
    elif "reflex" in t:
        save_type = "Reflex"
    elif "fortitude" in t or "fort" in t:
        save_type = "Fortitude"
    if not save_type:
        return None, None
    save_effect = "special"
    if "negate" in t:
        save_effect = "negates"
    elif "half" in t:
        save_effect = "half"
    elif "partial" in t:
        save_effect = "partial"
    return save_type, save_effect


def _parse_cooldown_text(text: str | None) -> list[tuple[str, float]]:
    """Parse cooldown text into [(class_abbrev, seconds), ...].

    Examples:
        "3 seconds (Wiz), 2 seconds (Sor)" -> [("Wiz", 3.0), ("Sor", 2.0)]
        "5 seconds" -> [("", 5.0)]
        "3.5 seconds" -> [("", 3.5)]
    """
    if not text:
        return []
    results = []
    # Pattern: "N seconds (Class)" or "N seconds"
    import re
    for m in re.finditer(r'([\d.]+)\s*seconds?\s*(?:\(([^)]+)\))?', text):
        try:
            secs = float(m.group(1))
        except ValueError:
            continue
        cls = m.group(2) or ""
        results.append((cls.strip(), secs))
    return results


# Class abbreviation -> full name for cooldown parsing
_CLASS_ABBREV: dict[str, str] = {
    "wiz": "Wizard", "sor": "Sorcerer", "brd": "Bard", "clr": "Cleric",
    "fvs": "Favored Soul", "pal": "Paladin", "rgr": "Ranger", "drd": "Druid",
    "art": "Artificer", "alc": "Alchemist", "wlk": "Warlock", "mnk": "Monk",
    "rog": "Rogue", "ftr": "Fighter", "brb": "Barbarian",
}


# Stat normalization moved to dat_parser/effects.py normalize_stat_name().
# _normalize_stat_name() was here — removed; composite splitting now
# happens in parse_enchantment_string_multi() at the parser level.


def _ensure_effect(conn: sqlite3.Connection, name: str, modifier: str | None) -> int | None:
    """Get or create an effects row, returning its id."""
    coalesced = modifier or ""
    row = conn.execute(
        "SELECT id FROM effects WHERE name = ? AND COALESCE(modifier, '') = ?",
        (name, coalesced),
    ).fetchone()
    if row:
        return row[0]
    conn.execute(
        "INSERT OR IGNORE INTO effects (name, modifier) VALUES (?, ?)",
        (name, modifier),
    )
    row = conn.execute(
        "SELECT id FROM effects WHERE name = ? AND COALESCE(modifier, '') = ?",
        (name, coalesced),
    ).fetchone()
    return row[0] if row else None


def _ensure_bonus(
    conn: sqlite3.Connection,
    name: str,
    stat_id: int | None,
    bonus_type_id: int | None,
    value: int | None,
    description: str | None = None,
) -> int:
    """Get or create a bonus definition row. Returns the bonus id."""
    row = conn.execute(
        f"""
        SELECT id FROM bonuses
        WHERE COALESCE(stat_id, -1) = COALESCE(?, -1)
          AND COALESCE(bonus_type_id, -1) = COALESCE(?, -1)
          AND COALESCE(value, -1) = COALESCE(?, -1)
          AND name = ?
        """,
        (stat_id, bonus_type_id, value, name),
    ).fetchone()
    if row:
        bonus_id = row[0]
        # Update description if we have one and the existing row doesn't
        if description:
            conn.execute(
                "UPDATE bonuses SET description = ? WHERE id = ? AND description IS NULL",
                (description, bonus_id),
            )
        return bonus_id
    cur = conn.execute(
        "INSERT INTO bonuses (name, description, stat_id, bonus_type_id, value) VALUES (?, ?, ?, ?, ?)",
        (name, description, stat_id, bonus_type_id, value),
    )
    return cur.lastrowid


def _lookup_id(conn: sqlite3.Connection, table: str, name_col: str, id_col: str, name: str | None) -> int | None:
    """Return the integer PK for a row matched by *name*, or None if not found or name is None."""
    if not name:
        return None
    row = conn.execute(
        f"SELECT {id_col} FROM {table} WHERE {name_col} = ?", (name,)
    ).fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Public insert functions
# ---------------------------------------------------------------------------


def insert_items(conn: sqlite3.Connection, items: list[dict]) -> int:
    """Insert a list of item dicts (as produced by wiki/game_data parsers) into the DB.

    Handles:
    - ``items`` table (base fields)
    - ``item_weapon_stats`` (if weapon fields present)
    - ``item_armor_stats`` (if armor fields present)
    - ``item_augment_slots`` (from ``augment_slots`` list)
    - ``bonuses`` (from ``enchantments`` list; stat_id/bonus_type_id/value left NULL
      for deferred resolution in a future linking pass)

    Skips ``quest`` field — those cross-entity links are owned by the quest
    scraper (Task 4). Links items to sets via ``set_bonus_items``.

    Returns the count of item rows inserted (not counting sub-table rows).
    """
    inserted = 0

    # Generic names that leak through from wiki parsing artifacts
    _SKIP_NAMES = {"sets", "Armor", "Random Loot Deconstruct"}

    for item in items:
        name = item.get("name")
        if not name:
            logger.warning("Skipping item with missing name: %r", item)
            continue
        if name in _SKIP_NAMES:
            continue

        # Resolve item_category: try item_category (from binary parser) first,
        # then fall back to mapping item_type (wiki positional arg)
        item_category = item.get("item_category") or _normalise_item_category(
            item.get("item_type")
        )

        # Skip non-equippable items (potions, scrolls, wands, consumables, etc.)
        _NON_EQUIP = {
            ItemCategory.POTION, ItemCategory.SCROLL, ItemCategory.WAND,
            ItemCategory.COMPONENT, ItemCategory.COLLECTIBLE, ItemCategory.CONSUMABLE,
            ItemCategory.WONDROUS,
        }
        if item_category in _NON_EQUIP:
            # Keep Wondrous items that have a real equipment_slot (miscategorized gear)
            if item_category == ItemCategory.WONDROUS and item.get("equipment_slot"):
                item_category = _normalise_item_category(item.get("item_type")) or ItemCategory.CLOTHING
            else:
                continue

        # Skip binary-only entries without equipment_slot — these are enchantment
        # effects, quest rewards, and crafting materials miscategorized as gear.
        # Keep items from wiki (wiki_url set) or with explicit equipment_slot.
        # Also keep items without dat_id (test/manual items).
        has_slot = bool(item.get("equipment_slot"))
        has_wiki = bool(item.get("wiki_url"))
        is_binary_only = bool(item.get("dat_id")) and not has_wiki
        if is_binary_only and not has_slot:
            continue

        # Resolve slot_id FK from equipment_slot name (set by EQUIPMENT_SLOTS enum)
        equipment_slot = item.get("equipment_slot")
        slot_id = _lookup_id(conn, "equipment_slots", "name", "id", equipment_slot)

        cur = conn.execute(
            f"""
            INSERT OR IGNORE INTO items (
                name, dat_id, rarity, slot_id, equipment_slot, item_category,
                level, durability, item_type, minimum_level, enhancement_bonus,
                hardness, weight, material, binding, base_value,
                race_required, icon, description, tooltip,
                enchant_name, enchant_suffix, effect_value,
                cooldown_seconds, internal_level, tier_multiplier, wiki_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                item.get("dat_id"),
                item.get("rarity"),
                slot_id,
                equipment_slot,
                item_category,
                item.get("level"),
                item.get("durability"),
                item.get("item_type"),
                item.get("minimum_level"),
                item.get("enhancement_bonus"),
                item.get("hardness"),
                item.get("weight"),
                item.get("material"),
                item.get("binding"),
                item.get("base_value"),
                item.get("race_required"),
                item.get("icon"),
                item.get("description"),
                item.get("tooltip"),
                item.get("enchant_name"),
                item.get("enchant_suffix"),
                item.get("effect_value"),
                item.get("cooldown_seconds"),
                item.get("internal_level"),
                item.get("tier_multiplier"),
                item.get("wiki_url"),
            ),
        )
        inserted += cur.rowcount

        # Retrieve id (whether just inserted or already existed)
        row = conn.execute("SELECT id FROM items WHERE name = ?", (name,)).fetchone()
        if row is None:
            logger.warning("Failed to retrieve id for %r after insert", name)
            continue
        item_id: int = row[0]

        # --- item_weapon_stats ---
        # Only create weapon stats when weapon-specific fields are present.
        # weapon_type alone is not enough — FID lookup sets it on armor too.
        weapon_required = ("damage", "critical", "handedness")
        weapon_fields = ("damage", "critical", "weapon_type", "proficiency", "handedness",
                         "damage_class", "attack_mod", "damage_mod")
        if any(item.get(f) for f in weapon_required):
            handedness = _normalise_handedness(item.get("handedness"))
            conn.execute(
                f"""
                INSERT OR IGNORE INTO item_weapon_stats
                    (item_id, damage, critical, damage_class, attack_mod, damage_mod,
                     weapon_type, proficiency, handedness)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    item.get("damage"),
                    item.get("critical"),
                    item.get("damage_class"),
                    item.get("attack_mod"),
                    item.get("damage_mod"),
                    item.get("weapon_type"),
                    item.get("proficiency"),
                    handedness,
                ),
            )

        # --- item_armor_stats ---
        if item.get("armor_bonus") is not None or item.get("max_dex_bonus") is not None:
            conn.execute(
                f"""
                INSERT OR IGNORE INTO item_armor_stats (item_id, armor_bonus, max_dex_bonus)
                VALUES (?, ?, ?)
                """,
                (item_id, item.get("armor_bonus"), item.get("max_dex_bonus")),
            )

        # --- item_augment_slots ---
        for sort_order, slot_color in enumerate(item.get("augment_slots") or []):
            if not slot_color:
                continue
            conn.execute(
                f"""
                INSERT OR IGNORE INTO item_augment_slots (item_id, sort_order, slot_type)
                VALUES (?, ?, ?)
                """,
                (item_id, sort_order, slot_color.strip()),
            )

        # --- bonuses pass A: decoded effect entries with resolved stat/bonus_type ---
        decoded_bonuses = item.get("_bonuses") or []
        for sort_order, effect in enumerate(decoded_bonuses):
            if effect.get("stat") is None:
                continue  # stat_def_id not yet in STAT_DEF_IDS — skip until mapped
            stat_id = _lookup_id(conn, "stats", "name", "id", effect["stat"])
            bonus_type_id = (
                _lookup_id(conn, "bonus_types", "name", "id", effect["bonus_type"])
                if effect.get("bonus_type")
                else None
            )
            bonus_name = f"{effect['stat']} +{effect['magnitude']}"
            resolution = effect.get("_resolution_method", "stat_def_ids")
            bonus_id = _ensure_bonus(
                conn, bonus_name, stat_id, bonus_type_id, effect["magnitude"],
                description=effect.get("_description"),
            )
            conn.execute(
                f"""
                INSERT OR IGNORE INTO item_bonuses
                    (item_id, bonus_id, sort_order, data_source, resolution_method)
                VALUES (?, ?, ?, '{DataSource.BINARY}', ?)
                """,
                (item_id, bonus_id, sort_order, resolution),
            )

        # --- pass B: wiki enchantment routing ---
        # Each enchantment goes to one of three destinations:
        #   1. item_bonuses — stat+value bonuses ({{Stat}}, {{SpellPower}}, etc.)
        #   2. item_effects — weapon/armor effects (Vorpal, Bane, etc.)
        #   3. skip — metadata already stored elsewhere (augments, sets, materials)
        pass_a_count = len(decoded_bonuses)
        bonus_offset = 0
        effect_offset = 0
        for enchantment in item.get("enchantments") or []:
            if not enchantment:
                continue

            # 0. Check for named enchantment side effects (e.g., Command's -6 Hide)
            # Extract enchantment name from template: {{Skills|Command|5}} -> "Command"
            # or {{Deception|6}} -> "Deception", or plain "Finesse" -> "Finesse"
            import re as _re
            enchantment_clean = enchantment.strip()
            _tmpl_match = _re.match(r"\{\{(?:Skills\|)?(\w[\w\s:'-]*?)(?:\||\}\})", enchantment_clean)
            enchantment_name = _tmpl_match.group(1).strip() if _tmpl_match else enchantment_clean
            named_effects = _get_named_enchantment_effects(enchantment_name)
            for ne in named_effects:
                if ne.get("stat") is not None:
                    # Numeric bonus/penalty
                    ne_stat_id = _lookup_id(conn, "stats", "name", "id", ne["stat"])
                    ne_bt_id = _lookup_id(conn, "bonus_types", "name", "id", ne["bonus_type"])
                    ne_name = f"{ne['stat']} {ne['value']:+d}"
                    ne_bonus_id = _ensure_bonus(
                        conn, ne_name, ne_stat_id, ne_bt_id, ne["value"],
                        description=f"Named enchantment: {enchantment_clean}",
                    )
                else:
                    # Description-only (conditional/proc)
                    ne_desc = ne.get("description", enchantment_name)
                    ne_bonus_id = _ensure_bonus(
                        conn, ne_desc, None, None, None,
                        description=ne_desc,
                    )
                conn.execute(
                    f"""
                    INSERT OR IGNORE INTO item_bonuses
                        (item_id, bonus_id, sort_order, data_source, resolution_method)
                    VALUES (?, ?, ?, '{DataSource.WIKI}', '{ResolutionMethod.NAMED_ENCHANTMENT}')
                    """,
                    (item_id, ne_bonus_id, pass_a_count + bonus_offset),
                )
                bonus_offset += 1

            # 1. Stat bonus → item_bonuses junction (composites already split by parser)
            parsed_list = _parse_enchantment(enchantment)
            if parsed_list:
                for parsed in parsed_list:
                    stat_id = _lookup_id(conn, "stats", "name", "id", parsed["stat"])
                    bonus_type_id = _lookup_id(
                        conn, "bonus_types", "name", "id", parsed["bonus_type"]
                    )
                    bonus_name = f"{parsed['stat']} +{parsed['value']}"
                    bonus_id = _ensure_bonus(
                        conn, bonus_name, stat_id, bonus_type_id, parsed["value"],
                        description=enchantment,
                    )
                    conn.execute(
                        f"""
                        INSERT OR IGNORE INTO item_bonuses
                            (item_id, bonus_id, sort_order, data_source, resolution_method)
                        VALUES (?, ?, ?, '{DataSource.WIKI}', '{ResolutionMethod.WIKI_ENCHANTMENT}')
                        """,
                        (item_id, bonus_id, pass_a_count + bonus_offset),
                    )
                    bonus_offset += 1
                continue

            # 2. Weapon/armor effect → item_effects table
            effect = _parse_effect(enchantment)
            if effect:
                effect_id = _ensure_effect(conn, effect["effect"], effect["modifier"])
                if effect_id is not None:
                    conn.execute(
                        f"""
                        INSERT OR IGNORE INTO item_effects
                            (item_id, effect_id, value, sort_order, data_source)
                        VALUES (?, ?, ?, ?, '{DataSource.WIKI}')
                        """,
                        (item_id, effect_id, effect["value"], effect_offset),
                    )
                    effect_offset += 1
                continue

            # 3. Metadata — skip (augments, sets, materials already stored)
            if _is_metadata(enchantment):
                continue

            # 4. Fallback: plain text enchantments → item_effects (weapon effect names)
            # Skip broken/empty strings
            cleaned = enchantment.strip().strip("}")
            if cleaned and len(cleaned) > 2 and not cleaned.startswith("{{"):
                effect_id = _ensure_effect(conn, cleaned, None)
                if effect_id is not None:
                    conn.execute(
                        f"INSERT OR IGNORE INTO item_effects (item_id, effect_id, value, sort_order, data_source) VALUES (?, ?, NULL, ?, '{DataSource.WIKI}')",
                        (item_id, effect_id, effect_offset),
                    )
                    effect_offset += 1

        # --- set membership ---
        set_names: list[str] = []
        # Source 1: set_name field from wiki parser
        sn = item.get("set_name")
        if sn and isinstance(sn, str) and sn.strip():
            set_names.append(sn.strip())
        # Source 2: {{Named item sets|...}} enchantment templates (already filtered
        # as metadata in pass B, so extract directly from enchantments list)
        for ench in item.get("enchantments") or []:
            m = re.search(r"\{\{Named item sets\|([^|}]+)", ench, re.IGNORECASE)
            if m:
                sn2 = m.group(1).strip()
                if sn2 and sn2 not in set_names:
                    set_names.append(sn2)
        for sn in set_names:
            set_id = _ensure_set_bonus(conn, sn)
            if set_id is not None:
                conn.execute(
                    "INSERT OR IGNORE INTO set_bonus_items (set_id, item_id) VALUES (?, ?)",
                    (set_id, item_id),
                )

    conn.commit()
    return inserted


def _ensure_set_bonus(conn: sqlite3.Connection, name: str) -> int | None:
    """Get or create a set_bonuses row, returning its id."""
    row = conn.execute("SELECT id FROM set_bonuses WHERE name = ?", (name,)).fetchone()
    if row:
        return row[0]
    conn.execute("INSERT OR IGNORE INTO set_bonuses (name) VALUES (?)", (name,))
    row = conn.execute("SELECT id FROM set_bonuses WHERE name = ?", (name,)).fetchone()
    return row[0] if row else None


def insert_set_bonus_effects(conn: sqlite3.Connection, sets: list[dict]) -> int:
    """Insert set bonus effects from wiki scraper into set_bonuses + bonuses tables.

    Each dict has:
        {"name": "Seasons of the Feywild",
         "bonuses": [{"min_pieces": 2, "text": "+10 Artifact bonus to HP"}, ...]}

    Returns the count of set rows created/updated.
    """
    inserted = 0
    for set_data in sets:
        name = set_data.get("name")
        if not name:
            continue
        set_id = _ensure_set_bonus(conn, name)
        if set_id is None:
            continue
        inserted += 1
        for sort_order, bonus in enumerate(set_data.get("bonuses", [])):
            bonus_text = bonus["text"]
            parsed_list = _parse_enchantment(bonus_text)
            if parsed_list:
                for parsed in parsed_list:
                    stat_id = _lookup_id(conn, "stats", "name", "id", parsed["stat"])
                    bonus_type_id = _lookup_id(
                        conn, "bonus_types", "name", "id", parsed["bonus_type"],
                    )
                    bonus_name = f"{parsed['stat']} +{parsed['value']}"
                    bonus_id = _ensure_bonus(
                        conn, bonus_name, stat_id, bonus_type_id, parsed["value"],
                        description=bonus_text,
                    )
            else:
                bonus_id = _ensure_bonus(conn, bonus_text, None, None, None, description=bonus_text)
            conn.execute(
                f"""
                INSERT OR IGNORE INTO set_bonus_bonuses
                    (set_id, bonus_id, min_pieces, sort_order, data_source, resolution_method)
                VALUES (?, ?, ?, ?, '{DataSource.WIKI}', '{ResolutionMethod.WIKI_ENCHANTMENT}')
                """,
                (set_id, bonus_id, bonus["min_pieces"], sort_order),
            )
    conn.commit()
    return inserted


def insert_filigrees(conn: sqlite3.Connection, filigrees: list[dict]) -> int:
    """Insert filigree dicts (from wiki scraper) into the DB.

    Returns the count of filigree rows inserted.
    """
    inserted = 0
    for fil in filigrees:
        name = fil.get("name")
        if not name:
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO filigrees (name, icon, set_name, rare_bonus, bonus) VALUES (?, ?, ?, ?, ?)",
            (name, fil.get("icon"), fil.get("set_name"), fil.get("rare_bonus"), fil.get("bonus")),
        )
        inserted += cur.rowcount
    conn.commit()
    return inserted


def insert_augments(conn: sqlite3.Connection, augments: list[dict]) -> int:
    """Insert augment dicts (from wiki scraper) into the DB.

    Populates the ``augments`` table and creates ``bonuses`` rows with
    ``source_type='augment'`` for each enchantment on the augment.

    Returns the count of augment rows inserted.
    """
    inserted = 0
    for augment in augments:
        name = augment.get("name")
        if not name:
            continue

        slot_color = (augment.get("slot_color") or "colorless").lower()
        cur = conn.execute(
            f"""
            INSERT OR IGNORE INTO augments (dat_id, name, icon, slot_color, min_level)
            VALUES (?, ?, ?, ?, ?)
            """,
            (augment.get("dat_id"), name, augment.get("icon"), slot_color, augment.get("minimum_level")),
        )
        if cur.rowcount == 0:
            continue

        augment_id = conn.execute(
            "SELECT id FROM augments WHERE name = ?", (name,)
        ).fetchone()
        if augment_id is None:
            continue
        augment_id = augment_id[0]
        inserted += 1

        # Bonuses from enchantments
        for sort_order, enchantment in enumerate(augment.get("enchantments") or []):
            if not enchantment:
                continue
            parsed_list = _parse_enchantment(enchantment)
            for parsed in parsed_list:
                stat_id = _lookup_id(conn, "stats", "name", "id", parsed["stat"])
                bonus_type_id = _lookup_id(
                    conn, "bonus_types", "name", "id", parsed["bonus_type"]
                )
                bonus_name = f"{parsed['stat']} +{parsed['value']}"
                bonus_id = _ensure_bonus(
                    conn, bonus_name, stat_id, bonus_type_id, parsed["value"],
                    description=enchantment,
                )
                conn.execute(
                    f"""
                    INSERT OR IGNORE INTO augment_bonuses
                        (augment_id, bonus_id, sort_order, data_source, resolution_method)
                    VALUES (?, ?, ?, '{DataSource.WIKI}', '{ResolutionMethod.WIKI_ENCHANTMENT}')
                    """,
                    (augment_id, bonus_id, sort_order),
                )

        # Binary bonuses from effect_ref localization names
        for sort_order_b, bb in enumerate(augment.get("_binary_bonuses") or []):
            stat_id = _lookup_id(conn, "stats", "name", "id", bb["stat"])
            bonus_type_id = (
                _lookup_id(conn, "bonus_types", "name", "id", bb["bonus_type"])
                if bb.get("bonus_type")
                else None
            )
            value = bb.get("value")
            bonus_name = f"{bb['stat']} +{value}" if value else bb["stat"]
            bonus_id = _ensure_bonus(
                conn, bonus_name, stat_id, bonus_type_id, value,
                description=bb.get("_description"),
            )
            conn.execute(
                f"""
                INSERT OR IGNORE INTO augment_bonuses
                    (augment_id, bonus_id, sort_order, data_source, resolution_method)
                VALUES (?, ?, ?, '{DataSource.BINARY}', ?)
                """,
                (augment_id, bonus_id, 100 + sort_order_b, bb.get("_resolution_method")),
            )

    conn.commit()
    return inserted


def insert_spells(conn: sqlite3.Connection, spells: list[dict]) -> int:
    """Insert spell dicts (from wiki scraper) into the DB.

    Populates ``spells``, ``spell_class_levels``, and ``spell_damage_types``.

    Returns the count of spell rows inserted.
    """
    inserted = 0
    for spell in spells:
        name = spell.get("name")
        if not name:
            continue

        school_id = _lookup_id(conn, "spell_schools", "name", "id", spell.get("school"))

        cur = conn.execute(
            f"""
            INSERT OR IGNORE INTO spells
                (name, icon, school_id, spell_points, cooldown, cooldown_seconds,
                 tick_count, description, components, range, target, duration,
                 saving_throw, save_type, save_effect, spell_resistance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                spell.get("icon"),
                school_id,
                spell.get("spell_points"),
                spell.get("cooldown"),
                spell.get("cooldown_seconds"),
                spell.get("tick_count"),
                spell.get("description"),
                spell.get("components"),
                spell.get("range"),
                spell.get("target"),
                spell.get("duration"),
                spell.get("saving_throw"),
                *_parse_saving_throw(spell.get("saving_throw")),
                spell.get("spell_resistance"),
            ),
        )
        if cur.rowcount == 0:
            continue

        spell_id = conn.execute(
            "SELECT id FROM spells WHERE name = ?", (name,)
        ).fetchone()
        if spell_id is None:
            continue
        spell_id = spell_id[0]
        inserted += 1

        # Class spell levels
        for class_name, spell_level in (spell.get("class_levels") or {}).items():
            class_id = _lookup_id(conn, "classes", "name", "id", class_name)
            if class_id is not None:
                conn.execute(
                    "INSERT OR IGNORE INTO spell_class_levels (spell_id, class_id, spell_level) VALUES (?, ?, ?)",
                    (spell_id, class_id, spell_level),
                )

        # Per-class cooldowns (parsed from text like "3 seconds (Wiz), 2 seconds (Sor)")
        cooldown_parts = _parse_cooldown_text(spell.get("cooldown"))
        for cls_abbrev, secs in cooldown_parts:
            if cls_abbrev:
                full_name = _CLASS_ABBREV.get(cls_abbrev.lower(), cls_abbrev)
                class_id = _lookup_id(conn, "classes", "name", "id", full_name)
                if class_id is not None:
                    conn.execute(
                        "INSERT OR IGNORE INTO spell_class_cooldowns (spell_id, class_id, cooldown_seconds) VALUES (?, ?, ?)",
                        (spell_id, class_id, secs),
                    )

        # Damage types
        for dt_name in spell.get("damage_types") or []:
            dt_id = _lookup_id(conn, "damage_types", "name", "id", dt_name)
            if dt_id is not None:
                conn.execute(
                    "INSERT OR IGNORE INTO spell_damage_types (spell_id, damage_type_id) VALUES (?, ?)",
                    (spell_id, dt_id),
                )

        # Metamagic feats
        for meta_name in spell.get("metamagics") or []:
            # Metamagic names come as "empower", "maximize" etc.; match to feat names
            feat_name = meta_name.replace("_", " ").title() + " Spell"
            feat_id = _lookup_id(conn, "feats", "name", "id", feat_name)
            if feat_id is not None:
                conn.execute(
                    "INSERT OR IGNORE INTO spell_metamagics (spell_id, feat_id) VALUES (?, ?)",
                    (spell_id, feat_id),
                )

    conn.commit()
    return inserted


def _parse_feat_prerequisites(
    conn: sqlite3.Connection, feat_id: int, prereq_text: str,
) -> None:
    """Parse a feat's free-text prerequisite string into structured junction rows.

    Handles:
    - Stat requirements: "17 Strength", "Dexterity 13+"
    - BAB requirements: "Base Attack Bonus +13" → sets feats.min_bab
    - Class requirements: "Warlock Level 15", "Alchemist 8"
    - Race requirements: "Half-Elf", "Warforged"
    - Skill requirements: "7 ranks of Balance"
    - Feat requirements: any remaining text matching a known feat name
    """
    if not prereq_text:
        return

    # Split on commas (but not inside numbers like "625,000") and "and"
    parts = re.split(r',\s+(?![0-9])|\s+and\s+', prereq_text)

    _stat_names = {
        "strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma",
    }
    _stat_title = {s.title() for s in _stat_names}

    for part in parts:
        p = part.strip().rstrip(".")
        if not p or p.lower() == "none":
            continue

        # BAB: "Base Attack Bonus +N" / "Base Attack Bonus of +N" / "+N Base Attack Bonus"
        m = re.search(r'[Bb]ase [Aa]ttack [Bb]onus\s+(?:of\s+)?\+?(\d+)', p)
        if not m:
            m = re.match(r'\+(\d+)\s+[Bb]ase [Aa]ttack [Bb]onus', p)
        if m:
            bab = int(m.group(1))
            conn.execute("UPDATE feats SET min_bab = ? WHERE id = ? AND (min_bab IS NULL OR min_bab < ?)",
                         (bab, feat_id, bab))
            continue

        # Stat: "17 Strength" or "Strength 17+"
        m = re.match(r'(\d+)\s+(' + '|'.join(_stat_title) + r')', p, re.IGNORECASE)
        if not m:
            m = re.match(r'(' + '|'.join(_stat_title) + r')\s+(\d+)', p, re.IGNORECASE)
            if m:
                # Swap groups: stat name first, value second
                stat_name, val_str = m.group(1).title(), m.group(2)
                m = None  # Prevent re-use
                stat_id = _lookup_id(conn, "stats", "name", "id", stat_name)
                if stat_id:
                    conn.execute(
                        "INSERT OR IGNORE INTO feat_prereq_stats (feat_id, stat_id, min_value) VALUES (?, ?, ?)",
                        (feat_id, stat_id, int(val_str)),
                    )
                continue
        if m:
            val_str, stat_name = m.group(1), m.group(2).title()
            stat_id = _lookup_id(conn, "stats", "name", "id", stat_name)
            if stat_id:
                conn.execute(
                    "INSERT OR IGNORE INTO feat_prereq_stats (feat_id, stat_id, min_value) VALUES (?, ?, ?)",
                    (feat_id, stat_id, int(val_str)),
                )
            continue

        # Skill: "N ranks of Skill" or "N trained Ranks of Skill"
        m = re.match(r'(\d+)\s+(?:trained\s+)?[Rr]anks?\s+(?:of\s+|in\s+)?(\w[\w ]*)', p, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            skill_name = m.group(2).strip().title()
            skill_id = _lookup_id(conn, "skills", "name", "id", skill_name)
            if skill_id:
                conn.execute(
                    "INSERT OR IGNORE INTO feat_prereq_skills (feat_id, skill_id, min_rank) VALUES (?, ?, ?)",
                    (feat_id, skill_id, val),
                )
            continue

        # Character level: "Level 21" / "Character level 25" / "Character Level 28"
        # Must precede the class-level pattern to avoid matching "Level" as a class name.
        m = re.match(r'(?:Character\s+)?[Ll]evel\s+(\d+)$', p)
        if m:
            char_level = int(m.group(1))
            if 1 <= char_level <= 30:
                conn.execute(
                    "UPDATE feats SET min_character_level = ? WHERE id = ? "
                    "AND (min_character_level IS NULL OR min_character_level < ?)",
                    (char_level, feat_id, char_level),
                )
            continue

        # Class level: "Warlock Level 15" / "Alchemist 8" / "Rogue level 10"
        m = re.match(r'(\w[\w ]*?)\s+(?:[Ll]evel\s+)?(\d+)$', p)
        if m:
            class_name = m.group(1).strip()
            level = int(m.group(2))
            class_id = _lookup_id(conn, "classes", "name", "id", class_name)
            if class_id and level >= 1:
                conn.execute(
                    "INSERT OR IGNORE INTO feat_prereq_classes (feat_id, class_id, min_level) VALUES (?, ?, ?)",
                    (feat_id, class_id, level),
                )
                continue

        # Race: just a race name
        race_id = _lookup_id(conn, "races", "name", "id", p)
        if race_id:
            conn.execute(
                "INSERT OR IGNORE INTO feat_prereq_races (feat_id, race_id) VALUES (?, ?)",
                (feat_id, race_id),
            )
            continue

        # Feat: match against known feat names
        required_feat_id = _lookup_id(conn, "feats", "name", "id", p)
        if required_feat_id and required_feat_id != feat_id:
            conn.execute(
                "INSERT OR IGNORE INTO feat_prereq_feats (feat_id, required_feat_id) VALUES (?, ?)",
                (feat_id, required_feat_id),
            )


def insert_feats(conn: sqlite3.Connection, feats: list[dict], **kwargs: object) -> int:
    """Insert a list of feat dicts (as produced by wiki/parsers.py) into the DB.

    Handles:
    - ``feats`` table (all boolean flags + text fields)
    - ``feat_bonus_classes`` junction (resolves class names to class_ids; skips
      unknown class names with a warning rather than failing)

    Returns the count of feat rows inserted.
    """
    inserted = 0

    def _bool(d: dict, key: str) -> int:
        return 1 if d.get(key) else 0

    for feat in feats:
        name = feat.get("name")
        if not name:
            logger.warning("Skipping feat with missing name: %r", feat)
            continue

        cur = conn.execute(
            f"""
            INSERT OR IGNORE INTO feats (
                dat_id, name, icon, description, tooltip, prerequisite, note,
                cooldown, cooldown_seconds, duration_seconds,
                damage_dice_notation,
                is_free, is_passive, is_active, is_stance, is_metamagic, is_epic_destiny,
                scales_with_difficulty, feat_tier, wiki_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                feat.get("dat_id"),
                name,
                feat.get("icon"),
                feat.get("description"),
                feat.get("tooltip"),
                feat.get("prerequisite"),
                feat.get("note"),
                feat.get("cooldown"),
                feat.get("cooldown_seconds"),
                feat.get("duration_seconds"),
                feat.get("damage_dice_notation"),
                _bool(feat, "free"),
                _bool(feat, "passive"),
                _bool(feat, "active"),
                _bool(feat, "stance"),
                _bool(feat, "metamagic"),
                _bool(feat, "epic_destiny"),
                _bool(feat, "scales_with_difficulty"),
                feat.get("tier"),
                feat.get("wiki_url"),
            ),
        )
        inserted += cur.rowcount

        row = conn.execute("SELECT id FROM feats WHERE name = ?", (name,)).fetchone()
        if row is None:
            logger.warning("Failed to retrieve id for %r after insert", name)
            continue
        feat_id: int = row[0]

        # --- feat_past_life_stats ---
        past_life_type = feat.get("past_life_type")
        if past_life_type:
            pl_class_id = _lookup_id(conn, "classes", "name", "id", feat.get("past_life_class"))
            pl_race_id  = _lookup_id(conn, "races",   "name", "id", feat.get("past_life_race"))
            conn.execute(
                f"""
                INSERT OR IGNORE INTO feat_past_life_stats
                    (feat_id, past_life_type, class_id, race_id, max_stacks)
                VALUES (?, ?, ?, ?, ?)
                """,
                (feat_id, past_life_type, pl_class_id, pl_race_id, feat.get("past_life_max_stacks")),
            )

        # --- feat_bonus_classes ---
        for class_name in feat.get("bonus_classes") or []:
            class_id = _lookup_id(conn, "classes", "name", "id", class_name)
            if class_id is None:
                logger.debug(
                    "Feat %r: bonus class %r not found in classes table — skipping",
                    name, class_name,
                )
                continue
            conn.execute(
                "INSERT OR IGNORE INTO feat_bonus_classes (feat_id, class_id) VALUES (?, ?)",
                (feat_id, class_id),
            )

    # --- Second pass: structured prerequisites ---
    # Must happen after ALL feats are inserted so feat-to-feat lookups work.
    for feat in feats:
        name = feat.get("name")
        prereq = feat.get("prerequisite")
        if not name or not prereq:
            continue
        row = conn.execute("SELECT id FROM feats WHERE name = ?", (name,)).fetchone()
        if row:
            _parse_feat_prerequisites(conn, row[0], prereq)

    # --- Third pass: race_feats (from scraped wiki data) ---
    race_feats_data = kwargs.get("race_feats") or {}
    for race_name, feat_names in race_feats_data.items():
        race_id = _lookup_id(conn, "races", "name", "id", race_name)
        if not race_id:
            continue
        for feat_name in feat_names:
            feat_id = _lookup_id(conn, "feats", "name", "id", feat_name)
            if feat_id:
                conn.execute(
                    "INSERT OR IGNORE INTO race_auto_feats (race_id, feat_id) VALUES (?, ?)",
                    (race_id, feat_id),
                )

    conn.commit()
    return inserted


# ---------------------------------------------------------------------------
# Enhancement description parsing
# ---------------------------------------------------------------------------

# Known bonus types that appear in enhancement descriptions
_ENH_BONUS_TYPES = [
    "Enhancement", "Insightful", "Insight", "Quality", "Competence",
    "Profane", "Sacred", "Luck", "Morale", "Artifact", "Exceptional",
    "Resistance", "Deflection", "Natural Armor", "Shield", "Dodge",
    "Alchemical", "Equipment", "Festive", "Rage", "Primal",
    "Determination", "Implement", "Music",
]
_ENH_BT_ALT = "|".join(sorted(_ENH_BONUS_TYPES, key=len, reverse=True))

# "+N bonus_type bonus(es) to STAT"
_ENH_PAT_TYPED = re.compile(
    rf"\+(\d+)%?\s+({_ENH_BT_ALT})\s+bonus(?:es)?\s+to\s+(.+?)(?:\.|,|\n|$)",
    re.IGNORECASE,
)

# "+N STAT" or "+N to [your] STAT" (no explicit bonus type)
_ENH_PAT_PLAIN = re.compile(
    r"\+(\d+)%?\s+(?:to\s+(?:your\s+)?)?([A-Z][A-Za-z ]+?)(?:\.|,|\n|$)"
)

# "+[N1/N2/N3] bonus_type bonus(es) to STAT"
_ENH_PAT_RANKED_TYPED = re.compile(
    rf"\+\[([^\]]+)\]\s+({_ENH_BT_ALT})\s+bonus(?:es)?\s+to\s+(.+?)(?:\.|,|\n|$)",
    re.IGNORECASE,
)

# "+[N1/N2/N3] STAT"
_ENH_PAT_RANKED_PLAIN = re.compile(
    r"\+\[([^\]]+)\]\s+(?:to\s+)?([A-Z][A-Za-z ]+?)(?:\.|,|\n|$)"
)

_ENH_BONUS_TYPE_NORM: dict[str, str] = {
    "insight": "Insight",
    "insightful": "Insight",
}


def _parse_enhancement_description(description: str) -> list[dict]:
    """Parse a wiki enhancement description into structured bonus dicts.

    Returns a list of dicts with keys:
        rank (int), value (int), stat (str), bonus_type (str | None)

    Handles patterns like:
        "+1 Strength"
        "+4 Insightful bonus to Wisdom"
        "+[1/2/3] Haggle, Concentration, and Heal"
        "+[3/6/10] Positive Healing Amplification"
    """
    if not description:
        return []

    results: list[dict] = []
    captured_spans: set[tuple[int, int]] = set()

    # --- Pass 1: Ranked patterns with bonus type "+[1/2/3] Type bonus to Stat" ---
    for m in _ENH_PAT_RANKED_TYPED.finditer(description):
        captured_spans.add((m.start(), m.end()))
        values_str = m.group(1)
        raw_bt = m.group(2).strip()
        raw_stat = m.group(3).strip()
        bt = _ENH_BONUS_TYPE_NORM.get(raw_bt.lower(), raw_bt)
        values = [int(v.strip()) for v in values_str.split("/") if v.strip().isdigit()]
        # Handle comma-separated stats: "Haggle, Concentration, and Heal"
        stats = _split_stat_list(raw_stat)
        for stat in stats:
            for i, val in enumerate(values):
                rank = i + 1
                if val > 0 and val <= 500:
                    results.append({"rank": rank, "value": val, "stat": stat, "bonus_type": bt})

    # --- Pass 2: Ranked patterns without bonus type "+[1/2/3] Stat" ---
    for m in _ENH_PAT_RANKED_PLAIN.finditer(description):
        if any(m.start() >= s and m.start() < e for s, e in captured_spans):
            continue
        captured_spans.add((m.start(), m.end()))
        values_str = m.group(1)
        raw_stat = m.group(2).strip()
        # Skip if stat looks like it contains a bonus type name
        if _stat_is_bonus_type(raw_stat):
            continue
        values = [int(v.strip()) for v in values_str.split("/") if v.strip().isdigit()]
        stats = _split_stat_list(raw_stat)
        for stat in stats:
            for i, val in enumerate(values):
                rank = i + 1
                if val > 0 and val <= 500:
                    results.append({"rank": rank, "value": val, "stat": stat, "bonus_type": None})

    # --- Pass 3: Single-value with bonus type "+N Type bonus to Stat" ---
    for m in _ENH_PAT_TYPED.finditer(description):
        if any(m.start() >= s and m.start() < e for s, e in captured_spans):
            continue
        captured_spans.add((m.start(), m.end()))
        val = int(m.group(1))
        raw_bt = m.group(2).strip()
        raw_stat = m.group(3).strip()
        bt = _ENH_BONUS_TYPE_NORM.get(raw_bt.lower(), raw_bt)
        stats = _split_stat_list(raw_stat)
        for stat in stats:
            if val > 0 and val <= 500:
                # If multi-rank enhancement with single value, assign to rank 1
                results.append({"rank": 1, "value": val, "stat": stat, "bonus_type": bt})

    # --- Pass 4: Single-value plain "+N Stat" ---
    for m in _ENH_PAT_PLAIN.finditer(description):
        if any(m.start() >= s and m.start() < e for s, e in captured_spans):
            continue
        captured_spans.add((m.start(), m.end()))
        val = int(m.group(1))
        raw_stat = m.group(2).strip()
        if _stat_is_bonus_type(raw_stat):
            continue
        stats = _split_stat_list(raw_stat)
        for stat in stats:
            if val > 0 and val <= 500:
                results.append({"rank": 1, "value": val, "stat": stat, "bonus_type": None})

    return results


def _split_stat_list(raw: str) -> list[str]:
    """Split comma/and-separated stat lists like 'Haggle, Concentration, and Heal'.

    Only splits on commas. 'X and Y' without commas is treated as a single
    compound name (e.g. 'Positive and Negative Healing Amplification', 'Melee
    and Ranged Power').
    """
    if "," not in raw:
        return [raw.strip()] if raw.strip() and len(raw.strip()) > 1 else []
    parts = re.split(r",\s*(?:and\s+)?", raw)
    # Final part might still have leading "and "
    cleaned = []
    for p in parts:
        p = re.sub(r"^\s*and\s+", "", p).strip()
        if p and len(p) > 1:
            cleaned.append(p)
    return cleaned


def _stat_is_bonus_type(stat: str) -> bool:
    """Check if a stat name is actually a bonus type qualifier."""
    sl = stat.lower()
    return any(bt.lower() == sl or sl.startswith(bt.lower() + " bonus") for bt in _ENH_BONUS_TYPES)


def insert_enhancement_trees(conn: sqlite3.Connection, trees: list[dict]) -> int:
    """Insert a list of enhancement tree dicts (as produced by wiki/scraper.py).

    Each tree dict has the shape::

        {
            "name": "Kensei",
            "type": "class",          # class | racial | universal
            "class_or_race": "Fighter",
            "enhancements": [
                {"name": ..., "icon": ..., "description": ..., "ranks": 1,
                 "ap_cost": 1, "progression": 0, "level": "Fighter Level 1",
                 "prerequisite": ..., "tier": "1"}
            ]
        }

    Handles:
    - ``enhancement_trees`` table (resolves class_id/race_id by name)
    - ``enhancements`` table (one row per enhancement)
    - ``enhancement_ranks`` table (one rank=1 row per enhancement from wiki description)

    Returns the count of tree rows inserted.
    """
    inserted = 0

    for tree in trees:
        name = tree.get("name")
        if not name:
            logger.warning("Skipping enhancement tree with missing name: %r", tree)
            continue

        tree_type = tree.get("type", "universal")
        ap_pool = _AP_POOL_MAP.get(tree_type, "heroic")
        class_or_race = tree.get("class_or_race") or None

        # Resolve class_id / race_id
        class_id: int | None = None
        race_id: int | None = None
        if tree_type == "class" and class_or_race:
            class_id = _lookup_id(conn, "classes", "name", "id", class_or_race)
            if class_id is None:
                logger.debug(
                    "Enhancement tree %r: class %r not found — inserting without class_id",
                    name, class_or_race,
                )
        elif tree_type == "racial" and class_or_race:
            race_id = _lookup_id(conn, "races", "name", "id", class_or_race)
            if race_id is None:
                logger.debug(
                    "Enhancement tree %r: race %r not found — inserting without race_id",
                    name, class_or_race,
                )

        # For 'class' tree_type we need class_id to satisfy the CHECK constraint.
        # If we couldn't resolve it, store as 'universal' (ap_pool='heroic') so the
        # CHECK doesn't fire — the tree data is still preserved, just without the FK.
        effective_tree_type = tree_type
        effective_class_id = class_id
        effective_race_id = race_id
        if tree_type == "class" and class_id is None:
            effective_tree_type = "universal"
        elif tree_type == "racial" and race_id is None:
            effective_tree_type = "universal"

        cur = conn.execute(
            f"""
            INSERT OR IGNORE INTO enhancement_trees
                (name, tree_type, ap_pool, class_id, race_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, effective_tree_type, ap_pool, effective_class_id, effective_race_id),
        )
        inserted += cur.rowcount

        row = conn.execute(
            "SELECT id FROM enhancement_trees WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            logger.warning("Failed to retrieve id for %r after insert", name)
            continue
        tree_id: int = row[0]

        # --- enhancements + enhancement_ranks ---
        for enh in tree.get("enhancements") or []:
            enh_name = enh.get("name")
            if not enh_name:
                continue

            tier = enh.get("tier", "unknown")
            # 'unknown' is allowed by the schema CHECK
            conn.execute(
                f"""
                INSERT OR IGNORE INTO enhancements
                    (tree_id, dat_id, name, icon, max_ranks, ap_cost, progression,
                     tier, level_req, prerequisite)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tree_id,
                    enh.get("dat_id"),
                    enh_name,
                    enh.get("icon"),
                    enh.get("ranks") or 1,
                    enh.get("ap_cost") or 1,
                    enh.get("progression") or 0,
                    tier,
                    enh.get("level"),
                    enh.get("prerequisite"),
                ),
            )

            enh_row = conn.execute(
                f"""
                SELECT id FROM enhancements
                WHERE tree_id = ? AND name = ?
                """,
                (tree_id, enh_name),
            ).fetchone()
            if enh_row is None:
                continue
            enh_id: int = enh_row[0]

            description = enh.get("description")
            max_ranks = enh.get("ranks") or 1
            if description:
                # Insert rank 1 with wiki description
                conn.execute(
                    "INSERT OR IGNORE INTO enhancement_ranks (enhancement_id, rank, description) VALUES (?, 1, ?)",
                    (enh_id, description),
                )
                # Insert additional ranks from localization tooltips or per-rank patterns
                loc_tooltips = enh.get("localization_tooltips") or []
                if max_ranks > 1 and len(loc_tooltips) >= max_ranks:
                    # Use localization tooltips sorted by length as per-rank descriptions
                    for rank_idx in range(1, max_ranks):
                        if rank_idx < len(loc_tooltips):
                            conn.execute(
                                "INSERT OR IGNORE INTO enhancement_ranks (enhancement_id, rank, description) VALUES (?, ?, ?)",
                                (enh_id, rank_idx + 1, loc_tooltips[rank_idx]),
                            )
                elif max_ranks > 1:
                    # No localization — just insert placeholder ranks
                    for rank_idx in range(2, max_ranks + 1):
                        conn.execute(
                            "INSERT OR IGNORE INTO enhancement_ranks (enhancement_id, rank, description) VALUES (?, ?, NULL)",
                            (enh_id, rank_idx),
                        )

            # --- enhancement_bonuses from parsed description ---
            if description:
                parsed_bonuses = _parse_enhancement_description(description)
                for pb in parsed_bonuses:
                    stat_id = _lookup_id(conn, "stats", "name", "id", pb["stat"])
                    bonus_type_id = (
                        _lookup_id(conn, "bonus_types", "name", "id", pb["bonus_type"])
                        if pb.get("bonus_type")
                        else None
                    )
                    bonus_name = f"{pb['stat']} +{pb['value']}"
                    bonus_id = _ensure_bonus(
                        conn, bonus_name, stat_id, bonus_type_id, pb["value"],
                        description=description,
                    )
                    conn.execute(
                        f"""
                        INSERT OR IGNORE INTO enhancement_bonuses
                            (enhancement_id, bonus_id, min_rank, data_source, resolution_method)
                        VALUES (?, ?, ?, '{DataSource.WIKI}', '{ResolutionMethod.WIKI_DESCRIPTION}')
                        """,
                        (enh_id, bonus_id, pb["rank"]),
                    )

    # --- Second pass: enhancement prerequisites ---
    # Parse "prerequisite" text into enhancement_prereqs and enhancement_prereq_classes.
    # Must happen after all enhancements are inserted so name lookups work.
    _class_level_pat = re.compile(r'(\w[\w ]*?)\s+[Ll]evel\s+(\d+)')
    for tree in trees:
        tname = tree.get("name", "")
        row = conn.execute("SELECT id FROM enhancement_trees WHERE name = ?", (tname,)).fetchone()
        if not row:
            continue
        tree_id = row[0]

        for enh in tree.get("enhancements") or []:
            prereq = enh.get("prerequisite")
            if not prereq:
                continue
            enh_name = enh.get("name")
            if not enh_name:
                continue
            enh_row = conn.execute(
                "SELECT id FROM enhancements WHERE tree_id = ? AND name = ?",
                (tree_id, enh_name),
            ).fetchone()
            if not enh_row:
                continue
            enh_id = enh_row[0]

            for part in re.split(r',\s*', prereq):
                p = part.strip()
                if not p:
                    continue
                # Class level: "Alchemist Level 3"
                m = _class_level_pat.match(p)
                if m:
                    class_name = m.group(1).strip()
                    level = int(m.group(2))
                    class_id = _lookup_id(conn, "classes", "name", "id", class_name)
                    if class_id:
                        conn.execute(
                            "INSERT OR IGNORE INTO enhancement_prereq_classes "
                            "(enhancement_id, class_id, min_level) VALUES (?, ?, ?)",
                            (enh_id, class_id, level),
                        )
                    continue
                # Enhancement name in same tree
                req_row = conn.execute(
                    "SELECT id FROM enhancements WHERE tree_id = ? AND name = ?",
                    (tree_id, p),
                ).fetchone()
                if req_row and req_row[0] != enh_id:
                    conn.execute(
                        "INSERT OR IGNORE INTO enhancement_prereqs "
                        "(enhancement_id, required_enhancement_id) VALUES (?, ?)",
                        (enh_id, req_row[0]),
                    )

    conn.commit()
    return inserted


def insert_class_progression(
    conn: sqlite3.Connection, classes: list[dict],
) -> int:
    """Insert class progression data from wiki-scraped class pages.

    Populates: class_spell_slots, class_auto_feats, class_bonus_feat_slots.
    Does NOT modify the classes seed table (hit_die, saves, etc. are seeded).

    Each class dict has::

        {"name": "Wizard", "levels": [
            {"level": 1, "feats": ["Dismiss Charm", ...],
             "spell_slots": {1: 3}, "sp": 80},
            ...
        ]}
    """
    inserted = 0
    cursor = conn.cursor()

    # Build class name -> id lookup from seed
    class_ids: dict[str, int] = {}
    for row in cursor.execute("SELECT id, name FROM classes"):
        class_ids[row[1]] = row[0]

    # Build feat name -> id lookup (case-insensitive)
    feat_ids: dict[str, int] = {}
    feat_ids_lower: dict[str, int] = {}
    for row in cursor.execute("SELECT id, name FROM feats"):
        feat_ids[row[1]] = row[0]
        feat_ids_lower[row[1].lower()] = row[0]

    for cls in classes:
        class_name = cls["name"]
        class_id = class_ids.get(class_name)
        if class_id is None:
            logger.warning("Class %r not in seed table, skipping", class_name)
            continue

        is_spontaneous = cls.get("spells_known_type") == "known"

        for lv in cls.get("levels", []):
            level = lv["level"]

            # --- Spell slots / spells known ---
            for spell_level, slots in lv.get("spell_slots", {}).items():
                cursor.execute(
                    """INSERT OR IGNORE INTO class_spell_slots
                       (class_id, class_level, spell_level, slots)
                       VALUES (?, ?, ?, ?)""",
                    (class_id, level, spell_level, slots),
                )
                inserted += cursor.rowcount

                # For spontaneous casters, also populate class_spells_known
                if is_spontaneous:
                    cursor.execute(
                        """INSERT OR IGNORE INTO class_spells_known
                           (class_id, class_level, spell_level, known_count)
                           VALUES (?, ?, ?, ?)""",
                        (class_id, level, spell_level, slots),
                    )
                    inserted += cursor.rowcount

            # --- Feats (auto-granted, bonus feat slots, and class choices) ---
            slot_sort_order = 0  # incremented per bonus/choice slot at this level
            for feat_name in lv.get("feats", []):
                feat_name_clean = feat_name.strip().lstrip("|").strip()
                if not feat_name_clean:
                    continue

                fn_lower = feat_name_clean.lower()

                # Bonus feat slots — "Fighter bonus feats", "Martial Arts Feat", etc.
                is_bonus_slot = (
                    "bonus feat" in fn_lower
                    or fn_lower in ("martial arts feat", "dragon arts feat")
                )
                if is_bonus_slot:
                    if fn_lower in ("martial arts feat", "dragon arts feat"):
                        slot_type = "martial_arts"
                    else:
                        slot_type = "class_bonus"
                    cursor.execute(
                        """INSERT OR IGNORE INTO class_bonus_feat_slots
                           (class_id, class_level, sort_order, slot_type, slot_label)
                           VALUES (?, ?, ?, ?, ?)""",
                        (class_id, level, slot_sort_order, slot_type, feat_name_clean),
                    )
                    inserted += cursor.rowcount
                    slot_sort_order += 1

                # Class choice — "X or Y" pattern (e.g., FvS "Grace of Battle or Knowledge of Battle")
                elif " or " in feat_name_clean:
                    choices = [c.strip() for c in feat_name_clean.split(" or ") if c.strip()]
                    cursor.execute(
                        """INSERT OR IGNORE INTO class_bonus_feat_slots
                           (class_id, class_level, sort_order, slot_type, slot_label)
                           VALUES (?, ?, ?, 'class_choice', ?)""",
                        (class_id, level, slot_sort_order, feat_name_clean),
                    )
                    inserted += cursor.rowcount
                    for choice_name in choices:
                        choice_id = feat_ids.get(choice_name)
                        if choice_id is None:
                            choice_id = feat_ids_lower.get(choice_name.lower())
                        if choice_id is not None:
                            cursor.execute(
                                """INSERT OR IGNORE INTO class_choice_feats
                                   (class_id, class_level, sort_order, feat_id)
                                   VALUES (?, ?, ?, ?)""",
                                (class_id, level, slot_sort_order, choice_id),
                            )
                            inserted += cursor.rowcount
                    slot_sort_order += 1

                else:
                    # Auto-granted feat — match by name
                    feat_id = feat_ids.get(feat_name_clean)
                    if feat_id is None:
                        feat_id = feat_ids_lower.get(feat_name_clean.lower())
                    if feat_id is not None:
                        cursor.execute(
                            """INSERT OR IGNORE INTO class_auto_feats
                               (class_id, class_level, feat_id)
                               VALUES (?, ?, ?)""",
                            (class_id, level, feat_id),
                        )
                        inserted += cursor.rowcount
                    else:
                        # Stub: insert minimal feat row for unmatched auto-feats
                        cursor.execute(
                            "INSERT OR IGNORE INTO feats (name, feat_tier) VALUES (?, NULL)",
                            (feat_name_clean,),
                        )
                        if cursor.rowcount > 0:
                            logger.warning(
                                "Created stub feat %r (auto-granted by %s level %d)",
                                feat_name_clean, class_name, level,
                            )
                            stub_id = cursor.lastrowid
                            feat_ids[feat_name_clean] = stub_id
                            feat_ids_lower[feat_name_clean.lower()] = stub_id
                            cursor.execute(
                                """INSERT OR IGNORE INTO class_auto_feats
                                   (class_id, class_level, feat_id)
                                   VALUES (?, ?, ?)""",
                                (class_id, level, stub_id),
                            )
                            inserted += cursor.rowcount

    conn.commit()
    logger.info("Inserted %d class progression rows", inserted)
    return inserted


# ---------------------------------------------------------------------------
# Crafting
# ---------------------------------------------------------------------------


def insert_crafting(conn: sqlite3.Connection, crafting_data: dict) -> int:
    """Insert Cannith Crafting enchantments, scaling values, and slot assignments.

    *crafting_data* is the dict returned by ``collect_crafting()``.
    Returns the total number of rows inserted across all crafting tables.
    """
    enchantments = crafting_data.get("enchantments", [])
    scaling_values = crafting_data.get("values", {})

    # Build equipment slot name -> id map
    slot_ids = dict(conn.execute("SELECT name, id FROM equipment_slots").fetchall())

    inserted = 0

    # 1. Insert enchantment definitions
    for ench in enchantments:
        name = ench["name"]
        cur = conn.execute(
            """INSERT OR IGNORE INTO crafting_enchantments
               (name, is_scaling, crafting_level)
               VALUES (?, ?, ?)""",
            (name, 1 if ench["is_scaling"] else 0, ench.get("crafting_level")),
        )
        inserted += cur.rowcount

    conn.commit()

    # Build enchantment name -> id map
    ench_ids = dict(conn.execute(
        "SELECT name, id FROM crafting_enchantments"
    ).fetchall())

    # 2. Insert scaling values
    for group_name, ml_values in scaling_values.items():
        ench_id = ench_ids.get(group_name)
        if ench_id is None:
            # Try matching "Ins. X" -> "Insightful X" which is the recipe name
            alt_name = group_name.replace("Ins. ", "Insightful ")
            ench_id = ench_ids.get(alt_name)
        if ench_id is None:
            logger.debug("Scaling group %r not matched to enchantment", group_name)
            continue

        for ml, value in ml_values.items():
            cur = conn.execute(
                """INSERT OR IGNORE INTO crafting_enchantment_values
                   (enchantment_id, minimum_level, value)
                   VALUES (?, ?, ?)""",
                (ench_id, ml, str(value)),
            )
            inserted += cur.rowcount

    # 3. Insert slot assignments
    for ench in enchantments:
        ench_id = ench_ids.get(ench["name"])
        if ench_id is None:
            continue

        for slot_name, affix_type in ench.get("slots", []):
            slot_id = slot_ids.get(slot_name)
            if slot_id is None:
                logger.debug(
                    "Unknown equipment slot %r for enchantment %r",
                    slot_name, ench["name"],
                )
                continue

            cur = conn.execute(
                """INSERT OR IGNORE INTO crafting_enchantment_slots
                   (enchantment_id, slot_id, affix_type)
                   VALUES (?, ?, ?)""",
                (ench_id, slot_id, affix_type),
            )
            inserted += cur.rowcount

    conn.commit()
    logger.info("Inserted %d crafting rows", inserted)
    return inserted


def insert_crafting_options(
    conn: sqlite3.Connection, options: list[dict]
) -> int:
    """Insert named crafting system options (Green Steel, Thunder-Forged, etc.).

    Each dict has: system_id, tier, name, description.
    Deduplicates by (system_id, tier, name) before inserting.
    Returns the count of crafting_options rows inserted.
    """
    inserted = 0
    seen: set[tuple] = set()

    for opt in options:
        system_id = opt.get("system_id")
        tier = opt.get("tier", "")
        name = opt.get("name", "")
        description = opt.get("description", "")

        if not system_id or not name:
            continue

        key = (system_id, tier, name)
        if key in seen:
            continue
        seen.add(key)

        cur = conn.execute(
            """INSERT OR IGNORE INTO crafting_options
               (system_id, tier, name, description)
               VALUES (?, ?, ?, ?)""",
            (system_id, tier, name, description),
        )
        inserted += cur.rowcount

    conn.commit()
    logger.info("Inserted %d crafting option rows", inserted)
    return inserted


def seed_crafting_data(conn: sqlite3.Connection) -> int:
    """Seed crafting items, ingredients, and recipes from static wiki-scraped data.

    Loads ``crafting_seed_data.json`` (scraped from DDO Wiki) and populates:
    - crafting_system_items: links systems to their craftable items
    - crafting_ingredients: material definitions
    - crafting_recipes: upgrade paths (input + materials -> output)
    - crafting_recipe_ingredients: materials needed per recipe

    Returns total rows inserted across all tables.
    """
    import json
    from pathlib import Path

    from ddo_data.enums import CraftingSystem

    seed_path = Path(__file__).parent.parent / "wiki" / "crafting_seed_data.json"
    if not seed_path.exists():
        logger.warning("crafting_seed_data.json not found, skipping seed")
        return 0

    data = json.loads(seed_path.read_text())
    inserted = 0

    # Insert missing craftable items as stubs before linking
    missing_path = Path(__file__).parent.parent / "wiki" / "crafting_missing_items.json"
    if missing_path.exists():
        missing_items = json.loads(missing_path.read_text())
        # Map equipment slot names to IDs
        slot_ids = dict(conn.execute("SELECT name, id FROM equipment_slots").fetchall())
        for mi in missing_items:
            name = mi["name"]
            slot_name = mi.get("equipment_slot")
            slot_id = slot_ids.get(slot_name) if slot_name else None
            cur = conn.execute(
                """INSERT OR IGNORE INTO items
                   (name, minimum_level, equipment_slot, slot_id, item_category)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    name,
                    mi.get("minimum_level"),
                    slot_name,
                    slot_id,
                    mi.get("item_category"),
                ),
            )
            inserted += cur.rowcount
        conn.commit()
        logger.info("Inserted %d missing craftable items", inserted)

    # Build system name -> id map
    sys_ids = {m.value: m.id for m in CraftingSystem}
    # Build item name -> id map (rebuilt after missing item insertion)
    item_ids = dict(conn.execute("SELECT name, id FROM items").fetchall())

    for sys_data in data:
        sys_name = sys_data["system"]
        sys_id = sys_ids.get(sys_name)
        if sys_id is None:
            logger.debug("Unknown crafting system %r, skipping", sys_name)
            continue

        # --- Link items ---
        for item_name in sys_data.get("items", []):
            item_id = item_ids.get(item_name)
            if item_id is not None:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO crafting_system_items (system_id, item_id) VALUES (?, ?)",
                    (sys_id, item_id),
                )
                inserted += cur.rowcount

        # --- Insert ingredients ---
        for ingr in sys_data.get("ingredients", []):
            name = ingr.get("name", "").strip()
            if not name:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO crafting_ingredients (name, wiki_url) VALUES (?, ?)",
                (name, ingr.get("wiki_url")),
            )

        # --- Insert recipes ---
        for recipe in sys_data.get("upgrades", []):
            recipe_name = recipe.get("input", "") or recipe.get("tier", "")
            input_name = recipe.get("input", "")
            output_name = recipe.get("output", "")
            input_id = item_ids.get(input_name) if input_name else None
            output_id = item_ids.get(output_name) if output_name else None

            cur = conn.execute(
                """INSERT INTO crafting_recipes
                   (system_id, name, input_item_id, output_item_id, description)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    sys_id,
                    recipe_name,
                    input_id,
                    output_id,
                    recipe.get("tier", ""),
                ),
            )
            recipe_id = cur.lastrowid
            inserted += 1

            # Link ingredients to recipe
            for ingr_name, qty in recipe.get("ingredients", {}).items():
                ingr_row = conn.execute(
                    "SELECT id FROM crafting_ingredients WHERE name = ?",
                    (ingr_name,),
                ).fetchone()
                if ingr_row:
                    conn.execute(
                        """INSERT OR IGNORE INTO crafting_recipe_ingredients
                           (recipe_id, ingredient_id, quantity)
                           VALUES (?, ?, ?)""",
                        (recipe_id, ingr_row[0], qty),
                    )
                    inserted += 1

    conn.commit()
    logger.info("Seeded %d crafting data rows (items, ingredients, recipes)", inserted)
    return inserted
