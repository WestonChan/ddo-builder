"""Insert functions for populating the DDO game database from scraper dicts."""

from __future__ import annotations

import logging
import re
import sqlite3

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Normalisation maps (wiki strings → schema CHECK constraint values)
# ---------------------------------------------------------------------------

# Wiki {{Named item|TYPE}} positional arg → items.item_category CHECK value
_ITEM_CATEGORY_MAP: dict[str, str] = {
    "weapon":      "Weapon",
    "armor":       "Armor",
    "shield":      "Shield",
    "jewelry":     "Jewelry",
    "ring":        "Jewelry",
    "necklace":    "Jewelry",
    "bracelet":    "Jewelry",
    "trinket":     "Jewelry",
    "accessory":   "Jewelry",
    "clothing":    "Clothing",
    "outfit":      "Clothing",
    "wondrous":    "Wondrous",
    "potion":      "Potion",
    "scroll":      "Scroll",
    "wand":        "Wand",
    "component":   "Component",
    "collectible": "Collectible",
    "consumable":  "Consumable",
}

# Wiki handedness strings → item_weapon_stats.handedness CHECK value
_HANDEDNESS_MAP: dict[str, str] = {
    "one-handed":  "One-handed",
    "one handed":  "One-handed",
    "1-handed":    "One-handed",
    "two-handed":  "Two-handed",
    "two handed":  "Two-handed",
    "2-handed":    "Two-handed",
    "off-hand":    "Off-hand",
    "off hand":    "Off-hand",
    "offhand":     "Off-hand",
    "thrown":      "Thrown",
}

# ap_pool derived from tree_type
_AP_POOL_MAP: dict[str, str] = {
    "class":     "heroic",
    "universal": "heroic",
    "racial":    "racial",
    "reaper":    "reaper",
    "destiny":   "legendary",
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


def _parse_enchantment(text: str) -> dict | None:
    """Parse a wiki enchantment string into a structured bonus dict.

    Deferred import to avoid circular dependency at module load time.
    """
    from ..dat_parser.effects import parse_enchantment_string

    return parse_enchantment_string(text)


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
) -> int:
    """Get or create a bonus definition row. Returns the bonus id."""
    row = conn.execute(
        """
        SELECT id FROM bonuses
        WHERE COALESCE(stat_id, -1) = COALESCE(?, -1)
          AND COALESCE(bonus_type_id, -1) = COALESCE(?, -1)
          AND COALESCE(value, -1) = COALESCE(?, -1)
          AND name = ?
        """,
        (stat_id, bonus_type_id, value, name),
    ).fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO bonuses (name, stat_id, bonus_type_id, value) VALUES (?, ?, ?, ?)",
        (name, stat_id, bonus_type_id, value),
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

    for item in items:
        name = item.get("name")
        if not name:
            logger.warning("Skipping item with missing name: %r", item)
            continue

        # Resolve item_category: try item_category (from binary parser) first,
        # then fall back to mapping item_type (wiki positional arg)
        item_category = item.get("item_category") or _normalise_item_category(
            item.get("item_type")
        )

        # Resolve slot_id FK from equipment_slot name (set by EQUIPMENT_SLOTS enum)
        equipment_slot = item.get("equipment_slot")
        slot_id = _lookup_id(conn, "equipment_slots", "name", "id", equipment_slot)

        cur = conn.execute(
            """
            INSERT OR IGNORE INTO items (
                name, dat_id, rarity, slot_id, equipment_slot, item_category,
                level, durability, item_type, minimum_level, enhancement_bonus,
                hardness, weight, material, binding, base_value, description, tooltip,
                enchant_name, enchant_suffix, effect_value,
                cooldown_seconds, internal_level, tier_multiplier, race_required, wiki_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                item.get("description"),
                item.get("tooltip"),
                item.get("enchant_name"),
                item.get("enchant_suffix"),
                item.get("effect_value"),
                item.get("cooldown_seconds"),
                item.get("internal_level"),
                item.get("tier_multiplier"),
                item.get("race_required"),
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
        weapon_fields = ("damage", "critical", "weapon_type", "proficiency", "handedness",
                         "damage_class", "attack_mod", "damage_mod")
        if any(item.get(f) for f in weapon_fields):
            handedness = _normalise_handedness(item.get("handedness"))
            conn.execute(
                """
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
                """
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
                """
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
            bonus_id = _ensure_bonus(conn, bonus_name, stat_id, bonus_type_id, effect["magnitude"])
            conn.execute(
                """
                INSERT OR IGNORE INTO item_bonuses
                    (item_id, bonus_id, sort_order, data_source, resolution_method)
                VALUES (?, ?, ?, 'binary', ?)
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

            # 1. Stat bonus → item_bonuses junction
            parsed = _parse_enchantment(enchantment)
            if parsed:
                stat_id = _lookup_id(conn, "stats", "name", "id", parsed["stat"])
                bonus_type_id = _lookup_id(
                    conn, "bonus_types", "name", "id", parsed["bonus_type"]
                )
                bonus_name = f"{parsed['stat']} +{parsed['value']}"
                bonus_id = _ensure_bonus(conn, bonus_name, stat_id, bonus_type_id, parsed["value"])
                conn.execute(
                    """
                    INSERT OR IGNORE INTO item_bonuses
                        (item_id, bonus_id, sort_order, data_source, resolution_method)
                    VALUES (?, ?, ?, 'wiki', 'wiki_enchantment')
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
                        """
                        INSERT OR IGNORE INTO item_effects
                            (item_id, effect_id, value, sort_order, data_source)
                        VALUES (?, ?, ?, ?, 'wiki')
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
                        "INSERT OR IGNORE INTO item_effects (item_id, effect_id, value, sort_order, data_source) VALUES (?, ?, NULL, ?, 'wiki')",
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
            bonus_id = _ensure_bonus(conn, bonus["text"], None, None, None)
            conn.execute(
                """
                INSERT OR IGNORE INTO set_bonus_bonuses
                    (set_id, bonus_id, min_pieces, sort_order, data_source)
                VALUES (?, ?, ?, ?, 'wiki')
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
            "INSERT OR IGNORE INTO filigrees (name, set_name, rare_bonus, bonus) VALUES (?, ?, ?, ?)",
            (name, fil.get("set_name"), fil.get("rare_bonus"), fil.get("bonus")),
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
            """
            INSERT OR IGNORE INTO augments (name, slot_color, min_level)
            VALUES (?, ?, ?)
            """,
            (name, slot_color, augment.get("minimum_level")),
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
            parsed = _parse_enchantment(enchantment)
            if parsed:
                stat_id = _lookup_id(conn, "stats", "name", "id", parsed["stat"])
                bonus_type_id = _lookup_id(
                    conn, "bonus_types", "name", "id", parsed["bonus_type"]
                )
                bonus_name = f"{parsed['stat']} +{parsed['value']}"
                bonus_id = _ensure_bonus(conn, bonus_name, stat_id, bonus_type_id, parsed["value"])
                conn.execute(
                    """
                    INSERT OR IGNORE INTO augment_bonuses
                        (augment_id, bonus_id, sort_order, data_source)
                    VALUES (?, ?, ?, 'wiki')
                    """,
                    (augment_id, bonus_id, sort_order),
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
            """
            INSERT OR IGNORE INTO spells
                (name, school_id, spell_points, cooldown, cooldown_seconds,
                 tick_count, description, components, range, target, duration,
                 saving_throw, save_type, save_effect, spell_resistance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
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


def insert_feats(conn: sqlite3.Connection, feats: list[dict]) -> int:
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
            """
            INSERT OR IGNORE INTO feats (
                dat_id, name, icon, description, tooltip, prerequisite, note,
                cooldown, cooldown_seconds, duration_seconds,
                damage_dice_notation,
                is_free, is_passive, is_active, is_stance, is_metamagic, is_epic_destiny,
                scales_with_difficulty, wiki_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                """
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

    conn.commit()
    return inserted


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
            """
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
                """
                INSERT OR IGNORE INTO enhancements
                    (tree_id, name, icon, max_ranks, ap_cost, progression,
                     tier, level_req, prerequisite)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tree_id,
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
                """
                SELECT id FROM enhancements
                WHERE tree_id = ? AND name = ?
                """,
                (tree_id, enh_name),
            ).fetchone()
            if enh_row is None:
                continue
            enh_id: int = enh_row[0]

            description = enh.get("description")
            if description:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO enhancement_ranks (enhancement_id, rank, description)
                    VALUES (?, 1, ?)
                    """,
                    (enh_id, description),
                )

    conn.commit()
    return inserted
