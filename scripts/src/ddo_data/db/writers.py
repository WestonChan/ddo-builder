"""Insert functions for populating the DDO game database from scraper dicts."""

from __future__ import annotations

import logging
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

    Skips ``quest`` and ``set_name`` fields — those cross-entity links are owned
    by the quest scraper (Task 4) and set bonus scraper (Task 5).

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
                hardness, weight, material, binding, base_value, description, wiki_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        weapon_fields = ("damage", "critical", "weapon_type", "proficiency", "handedness")
        if any(item.get(f) for f in weapon_fields):
            handedness = _normalise_handedness(item.get("handedness"))
            conn.execute(
                """
                INSERT OR IGNORE INTO item_weapon_stats
                    (item_id, damage, critical, weapon_type, proficiency, handedness)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    item.get("damage"),
                    item.get("critical"),
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
            conn.execute(
                """
                INSERT OR IGNORE INTO bonuses
                    (source_type, source_id, min_rank, min_pieces, sort_order,
                     name, stat_id, bonus_type_id, value)
                VALUES ('item', ?, NULL, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    sort_order,
                    f"{effect['stat']} +{effect['magnitude']}",
                    stat_id,
                    bonus_type_id,
                    effect["magnitude"],
                ),
            )

        # --- pass B: wiki enchantment routing ---
        # Each enchantment goes to one of three destinations:
        #   1. bonuses table — stat+value bonuses ({{Stat}}, {{SpellPower}}, etc.)
        #   2. item_effects table — weapon/armor effects (Vorpal, Bane, etc.)
        #   3. skip — metadata already stored elsewhere (augments, sets, materials)
        pass_a_count = len(decoded_bonuses)
        bonus_offset = 0
        effect_offset = 0
        for enchantment in item.get("enchantments") or []:
            if not enchantment:
                continue

            # 1. Stat bonus → bonuses table
            parsed = _parse_enchantment(enchantment)
            if parsed:
                stat_id = _lookup_id(conn, "stats", "name", "id", parsed["stat"])
                bonus_type_id = _lookup_id(
                    conn, "bonus_types", "name", "id", parsed["bonus_type"]
                )
                name = f"{parsed['stat']} +{parsed['value']}"
                conn.execute(
                    """
                    INSERT OR IGNORE INTO bonuses
                        (source_type, source_id, min_rank, min_pieces, sort_order,
                         name, stat_id, bonus_type_id, value)
                    VALUES ('item', ?, NULL, NULL, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id,
                        pass_a_count + bonus_offset,
                        name,
                        stat_id,
                        bonus_type_id,
                        parsed["value"],
                    ),
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
                            (item_id, effect_id, value, sort_order)
                        VALUES (?, ?, ?, ?)
                        """,
                        (item_id, effect_id, effect["value"], effect_offset),
                    )
                    effect_offset += 1
                continue

            # 3. Metadata — skip (augments, sets, materials already stored)
            if _is_metadata(enchantment):
                continue

            # 4. Fallback: truly unknown enchantments as name-only bonus
            conn.execute(
                """
                INSERT OR IGNORE INTO bonuses
                    (source_type, source_id, min_rank, min_pieces, sort_order, name,
                     stat_id, bonus_type_id, value)
                VALUES ('item', ?, NULL, NULL, ?, ?, NULL, NULL, NULL)
                """,
                (item_id, pass_a_count + bonus_offset, enchantment.strip()),
            )
            bonus_offset += 1

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
                dat_id, name, icon, description, prerequisite, note, cooldown,
                damage_dice_notation,
                is_free, is_passive, is_active, is_stance, is_metamagic, is_epic_destiny
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                feat.get("dat_id"),
                name,
                feat.get("icon"),
                feat.get("description"),
                feat.get("prerequisite"),
                feat.get("note"),
                feat.get("cooldown"),
                feat.get("damage_dice_notation"),
                _bool(feat, "free"),
                _bool(feat, "passive"),
                _bool(feat, "active"),
                _bool(feat, "stance"),
                _bool(feat, "metamagic"),
                _bool(feat, "epic_destiny"),
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
