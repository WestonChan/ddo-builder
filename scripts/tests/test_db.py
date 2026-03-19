"""Integration tests for the DDO game database module."""

from __future__ import annotations

import sqlite3

import pytest

from ddo_data.db import GameDB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tables(conn: sqlite3.Connection) -> set[str]:
    """Return set of table names in the database."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return {r[0] for r in rows}


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_create_schema_tables() -> None:
    """create_schema() creates all expected core tables."""
    with GameDB(":memory:") as db:
        db.create_schema()
        tables = _tables(db.conn)

    expected = {
        "stats", "bonus_types", "skills", "damage_types",
        "weapon_proficiencies", "weapon_types", "equipment_slots", "spell_schools",
        "classes", "races", "items", "feats", "enhancements", "enhancement_trees",
        "effects", "item_effects",
        "bonuses", "item_weapon_stats", "item_armor_stats", "item_augment_slots",
        "feat_bonus_classes", "feat_past_life_stats", "schema_version",
    }
    assert expected.issubset(tables)


def test_create_schema_seeds_reference_data() -> None:
    """create_schema() seeds reference tables with DDO game data."""
    with GameDB(":memory:") as db:
        db.create_schema()
        conn = db.conn
        assert _count(conn, "stats") >= 6        # at least 6 ability scores
        assert _count(conn, "skills") == 21      # 21 DDO skills
        assert _count(conn, "bonus_types") >= 10
        assert _count(conn, "damage_types") >= 10
        assert _count(conn, "weapon_proficiencies") == 3
        assert _count(conn, "spell_schools") == 9


def test_create_schema_idempotent() -> None:
    """Calling create_schema() twice does not raise and does not duplicate seed data."""
    with GameDB(":memory:") as db:
        db.create_schema()
        first_stats = _count(db.conn, "stats")
        db.create_schema()
        assert _count(db.conn, "stats") == first_stats


# ---------------------------------------------------------------------------
# insert_items tests
# ---------------------------------------------------------------------------


MINIMAL_ITEM: dict = {
    "name": "Ring of the Stalker",
    "minimum_level": 10,
    "description": "A ring for stalkers.",
    "enchantments": [],
    "augment_slots": [],
}


def test_insert_items_basic() -> None:
    """Basic item fields round-trip through items table."""
    with GameDB(":memory:") as db:
        db.create_schema()
        count = db.insert_items([MINIMAL_ITEM])
        assert count == 1
        row = db.conn.execute(
            "SELECT name, minimum_level, description FROM items WHERE name = ?",
            ("Ring of the Stalker",),
        ).fetchone()
    assert row is not None
    assert row[0] == "Ring of the Stalker"
    assert row[1] == 10
    assert row[2] == "A ring for stalkers."


def test_insert_items_weapon() -> None:
    """Weapon fields go to item_weapon_stats."""
    weapon = {
        "name": "Sword of Fire",
        "item_type": "Weapon",
        "damage": "1d8+5",
        "critical": "19-20/x2",
        "weapon_type": "Longsword",
        "proficiency": "Martial",
        "handedness": "One-handed",
        "enchantments": [],
        "augment_slots": [],
    }
    with GameDB(":memory:") as db:
        db.create_schema()
        count = db.insert_items([weapon])
        assert count == 1
        row = db.conn.execute(
            "SELECT damage, critical, weapon_type, proficiency, handedness "
            "FROM item_weapon_stats iws "
            "JOIN items i ON iws.item_id = i.id "
            "WHERE i.name = ?",
            ("Sword of Fire",),
        ).fetchone()
    assert row is not None
    assert row[0] == "1d8+5"
    assert row[2] == "Longsword"
    assert row[4] == "One-handed"


def test_insert_items_weapon_handedness_normalised() -> None:
    """Handedness strings are normalised to schema CHECK values."""
    weapon = {
        "name": "Big Axe",
        "damage": "1d12",
        "handedness": "two-handed",  # lowercase, hyphenated
        "enchantments": [],
        "augment_slots": [],
    }
    with GameDB(":memory:") as db:
        db.create_schema()
        db.insert_items([weapon])
        row = db.conn.execute(
            "SELECT handedness FROM item_weapon_stats iws "
            "JOIN items i ON iws.item_id = i.id WHERE i.name = ?",
            ("Big Axe",),
        ).fetchone()
    assert row is not None
    assert row[0] == "Two-handed"


def test_insert_items_armor() -> None:
    """Armor fields go to item_armor_stats."""
    armor = {
        "name": "Full Plate",
        "item_type": "Armor",
        "armor_bonus": 8,
        "max_dex_bonus": 1,
        "enchantments": [],
        "augment_slots": [],
    }
    with GameDB(":memory:") as db:
        db.create_schema()
        db.insert_items([armor])
        row = db.conn.execute(
            "SELECT armor_bonus, max_dex_bonus "
            "FROM item_armor_stats ias "
            "JOIN items i ON ias.item_id = i.id WHERE i.name = ?",
            ("Full Plate",),
        ).fetchone()
    assert row is not None
    assert row[0] == 8
    assert row[1] == 1


def test_insert_items_augment_slots() -> None:
    """augment_slots list creates item_augment_slots rows with correct sort_order."""
    item = {
        "name": "Augmented Ring",
        "augment_slots": ["Blue", "Yellow", "Colorless"],
        "enchantments": [],
    }
    with GameDB(":memory:") as db:
        db.create_schema()
        db.insert_items([item])
        rows = db.conn.execute(
            "SELECT sort_order, slot_type FROM item_augment_slots ias "
            "JOIN items i ON ias.item_id = i.id "
            "WHERE i.name = ? ORDER BY sort_order",
            ("Augmented Ring",),
        ).fetchall()
    assert len(rows) == 3
    assert rows[0] == (0, "Blue")
    assert rows[1] == (1, "Yellow")
    assert rows[2] == (2, "Colorless")


def test_insert_items_enchantments_go_to_bonuses() -> None:
    """enchantments list creates bonuses rows with source_type='item'."""
    item = {
        "name": "Magic Ring",
        "enchantments": ["Strength +6", "Insightful Dexterity +3"],
        "augment_slots": [],
    }
    with GameDB(":memory:") as db:
        db.create_schema()
        db.insert_items([item])
        rows = db.conn.execute(
            "SELECT b.name, b.source_type, b.sort_order "
            "FROM bonuses b JOIN items i ON b.source_id = i.id "
            "WHERE i.name = ? AND b.source_type = 'item' ORDER BY b.sort_order",
            ("Magic Ring",),
        ).fetchall()
    assert len(rows) == 2
    assert rows[0][0] == "Strength +6"
    assert rows[0][1] == "item"
    assert rows[0][2] == 0
    assert rows[1][0] == "Insightful Dexterity +3"
    assert rows[1][2] == 1


def test_insert_items_item_category_mapped() -> None:
    """item_type 'ring' is mapped to item_category 'Jewelry'."""
    item = {
        "name": "Some Ring",
        "item_type": "Ring",
        "enchantments": [],
        "augment_slots": [],
    }
    with GameDB(":memory:") as db:
        db.create_schema()
        db.insert_items([item])
        row = db.conn.execute(
            "SELECT item_category FROM items WHERE name = ?", ("Some Ring",)
        ).fetchone()
    assert row is not None
    assert row[0] == "Jewelry"


def test_insert_items_idempotent() -> None:
    """Inserting the same item twice does not raise or create duplicate rows."""
    with GameDB(":memory:") as db:
        db.create_schema()
        db.insert_items([MINIMAL_ITEM])
        db.insert_items([MINIMAL_ITEM])
        assert _count(db.conn, "items") == 1


def test_insert_items_skips_missing_name() -> None:
    """Items with no name are skipped without raising."""
    with GameDB(":memory:") as db:
        db.create_schema()
        count = db.insert_items([{"name": None, "enchantments": [], "augment_slots": []}])
    assert count == 0


def test_insert_items_slot_id_resolved_from_equipment_slot() -> None:
    """equipment_slot name is resolved to slot_id FK via equipment_slots seed."""
    item = {
        "name": "Sword of Testing",
        "equipment_slot": "Main Hand",
        "enchantments": [],
        "augment_slots": [],
    }
    with GameDB(":memory:") as db:
        db.create_schema()
        db.insert_items([item])
        row = db.conn.execute(
            "SELECT slot_id, equipment_slot FROM items WHERE name = ?",
            ("Sword of Testing",),
        ).fetchone()
        # Confirm the FK resolved to the seeded "Main Hand" row
        main_hand_id = db.conn.execute(
            "SELECT id FROM equipment_slots WHERE name = 'Main Hand'"
        ).fetchone()[0]
    assert row is not None
    assert row[0] == main_hand_id
    assert row[1] == "Main Hand"


def test_insert_items_slot_id_null_when_slot_unknown() -> None:
    """equipment_slot with no matching seed row leaves slot_id NULL."""
    item = {
        "name": "Mystery Item",
        "equipment_slot": "Unknown Slot",
        "enchantments": [],
        "augment_slots": [],
    }
    with GameDB(":memory:") as db:
        db.create_schema()
        db.insert_items([item])
        row = db.conn.execute(
            "SELECT slot_id FROM items WHERE name = ?", ("Mystery Item",)
        ).fetchone()
    assert row is not None
    assert row[0] is None


def test_insert_items_slot_id_null_when_slot_absent() -> None:
    """Item with no equipment_slot key at all gets slot_id NULL (not an error)."""
    item = {
        "name": "Slotless Gem",
        "enchantments": [],
        "augment_slots": [],
    }
    with GameDB(":memory:") as db:
        db.create_schema()
        db.insert_items([item])
        row = db.conn.execute(
            "SELECT slot_id, equipment_slot FROM items WHERE name = ?", ("Slotless Gem",)
        ).fetchone()
    assert row is not None
    assert row[0] is None
    assert row[1] is None


def test_insert_items_off_hand_codes_resolve_to_same_slot() -> None:
    """Binary slot codes 13 and 16 both map to 'Off Hand' and share the same slot_id FK."""
    shield = {"name": "Tower Shield", "equipment_slot": "Off Hand", "enchantments": [], "augment_slots": []}
    offhand = {"name": "Orb of Fire", "equipment_slot": "Off Hand", "enchantments": [], "augment_slots": []}
    with GameDB(":memory:") as db:
        db.create_schema()
        db.insert_items([shield, offhand])
        rows = db.conn.execute(
            "SELECT slot_id FROM items WHERE name IN ('Tower Shield', 'Orb of Fire') ORDER BY name"
        ).fetchall()
    assert len(rows) == 2
    assert rows[0][0] == rows[1][0]   # both resolve to the same slot_id
    assert rows[0][0] is not None


def test_insert_items_bonus_pass_a_with_known_stat() -> None:
    """_bonuses with a resolvable stat name creates a bonuses row with stat_id set."""
    item = {
        "name": "Ring of Haggling",
        "enchantments": [],
        "augment_slots": [],
        "_bonuses": [
            {
                "entry_type": 53,
                "stat_def_id": 376,
                "stat": "Haggle",
                "magnitude": 15,
                "bonus_type_code": 0x0100,
                "bonus_type": "Enhancement",
            }
        ],
    }
    with GameDB(":memory:") as db:
        db.create_schema()
        db.insert_items([item])
        row = db.conn.execute(
            """
            SELECT b.name, b.value, b.stat_id, b.bonus_type_id
            FROM bonuses b JOIN items i ON b.source_id = i.id
            WHERE i.name = ? AND b.source_type = 'item'
            """,
            ("Ring of Haggling",),
        ).fetchone()
        haggle_stat_id = db.conn.execute(
            "SELECT id FROM stats WHERE name = 'Haggle'"
        ).fetchone()[0]
        enhancement_bt_id = db.conn.execute(
            "SELECT id FROM bonus_types WHERE name = 'Enhancement'"
        ).fetchone()[0]
    assert row is not None
    assert row[0] == "Haggle +15"
    assert row[1] == 15
    assert row[2] == haggle_stat_id
    assert row[3] == enhancement_bt_id


def test_insert_items_pass_b_sort_order_offset() -> None:
    """Pass B enchantments start at sort_order = len(_bonuses), not 0."""
    item = {
        "name": "Fancy Glove",
        "enchantments": ["Fire Resistance +20", "Proof Against Poison"],
        "augment_slots": [],
        "_bonuses": [
            {
                "entry_type": 53,
                "stat_def_id": 376,
                "stat": "Haggle",
                "magnitude": 5,
                "bonus_type_code": 0x0100,
                "bonus_type": "Enhancement",
            },
            {
                "entry_type": 53,
                "stat_def_id": 1941,
                "stat": "Spell Points",
                "magnitude": 50,
                "bonus_type_code": 0x0100,
                "bonus_type": "Enhancement",
            },
        ],
    }
    with GameDB(":memory:") as db:
        db.create_schema()
        db.insert_items([item])
        rows = db.conn.execute(
            """
            SELECT b.sort_order, b.name, b.stat_id
            FROM bonuses b JOIN items i ON b.source_id = i.id
            WHERE i.name = ? AND b.source_type = 'item'
            ORDER BY b.sort_order
            """,
            ("Fancy Glove",),
        ).fetchall()
    # Pass A: sort_orders 0 and 1 (both stats known)
    assert rows[0][0] == 0
    assert rows[0][2] is not None   # stat_id resolved
    assert rows[1][0] == 1
    assert rows[1][2] is not None
    # Pass B: sort_orders 2 and 3 (offset past len(_bonuses)=2)
    assert rows[2][0] == 2
    assert rows[2][1] == "Fire Resistance +20"
    assert rows[2][2] is None       # stat_id NULL for wiki strings
    assert rows[3][0] == 3
    assert rows[3][1] == "Proof Against Poison"


def test_insert_items_pass_b_parses_stat_template() -> None:
    """Wiki {{Stat|STR|7}} enchantment resolves to structured bonus with stat_id."""
    item = {
        "name": "Belt of Power",
        "enchantments": ["{{Stat|STR|7}}", "{{Ghostly}}"],
        "augment_slots": [],
    }
    with GameDB(":memory:") as db:
        db.create_schema()
        db.insert_items([item])
        rows = db.conn.execute(
            """
            SELECT b.name, b.stat_id, b.bonus_type_id, b.value
            FROM bonuses b JOIN items i ON b.source_id = i.id
            WHERE i.name = ? AND b.source_type = 'item'
            ORDER BY b.sort_order
            """,
            ("Belt of Power",),
        ).fetchall()
        # {{Stat|STR|7}} → bonuses table with resolved stat_id
        assert len(rows) == 1
        assert rows[0][0] == "Strength +7"
        stat_id = rows[0][1]
        assert stat_id is not None  # resolved from stats seed
        stat_name = db.conn.execute(
            "SELECT name FROM stats WHERE id = ?", (stat_id,)
        ).fetchone()[0]
        assert stat_name == "Strength"
        assert rows[0][2] is not None  # bonus_type_id (Enhancement)
        assert rows[0][3] == 7  # value
        # {{Ghostly}} → item_effects table (weapon effect, not a stat bonus)
        effect_rows = db.conn.execute(
            """
            SELECT e.name FROM item_effects ie
            JOIN effects e ON ie.effect_id = e.id
            JOIN items i ON ie.item_id = i.id
            WHERE i.name = ?
            """,
            ("Belt of Power",),
        ).fetchall()
        assert len(effect_rows) == 1
        assert effect_rows[0][0] == "Ghostly"


def test_insert_items_pass_b_parses_spellpower_template() -> None:
    """Wiki {{SpellPower|Devotion|30}} resolves to Positive Spell Power +30."""
    item = {
        "name": "Healing Focus",
        "enchantments": ["{{SpellPower|Devotion|30}}"],
        "augment_slots": [],
    }
    with GameDB(":memory:") as db:
        db.create_schema()
        db.insert_items([item])
        rows = db.conn.execute(
            """
            SELECT b.name, b.value
            FROM bonuses b JOIN items i ON b.source_id = i.id
            WHERE i.name = ? AND b.source_type = 'item'
            """,
            ("Healing Focus",),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "Positive Spell Power +30"
    assert rows[0][1] == 30


def test_insert_items_effects_table() -> None:
    """Weapon effect templates create rows in effects + item_effects tables."""
    item = {
        "name": "Epic Sword",
        "enchantments": ["{{Vorpal}}", "{{Bane|Evil Outsider|4}}"],
        "augment_slots": [],
    }
    with GameDB(":memory:") as db:
        db.create_schema()
        db.insert_items([item])
        # Check effects reference table
        effects = db.conn.execute(
            "SELECT name, modifier FROM effects ORDER BY name"
        ).fetchall()
        assert ("Bane", "Evil Outsider") in effects
        assert ("Vorpal", None) in effects
        # Check item_effects junction
        rows = db.conn.execute(
            """
            SELECT e.name, e.modifier, ie.value, ie.sort_order
            FROM item_effects ie
            JOIN effects e ON ie.effect_id = e.id
            JOIN items i ON ie.item_id = i.id
            WHERE i.name = ?
            ORDER BY ie.sort_order
            """,
            ("Epic Sword",),
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][0] == "Vorpal"
        assert rows[0][1] is None  # no modifier
        assert rows[0][2] is None  # no value
        assert rows[1][0] == "Bane"
        assert rows[1][1] == "Evil Outsider"
        assert rows[1][2] == 4  # value


def test_insert_items_pass_b_skips_metadata() -> None:
    """Metadata templates (augments, sets) don't go to bonuses or item_effects."""
    item = {
        "name": "Test Ring",
        "enchantments": [
            "{{Augment|Red}}",
            "{{Named item sets|Slave Lords}}",
            "{{Stat|STR|7}}",
        ],
        "augment_slots": [],
    }
    with GameDB(":memory:") as db:
        db.create_schema()
        db.insert_items([item])
        # Only the Stat template should create a bonus
        bonus_count = db.conn.execute(
            "SELECT COUNT(*) FROM bonuses WHERE source_type = 'item'"
        ).fetchone()[0]
        assert bonus_count == 1
        # No effects should be created
        effect_count = db.conn.execute(
            "SELECT COUNT(*) FROM item_effects"
        ).fetchone()[0]
        assert effect_count == 0


# ---------------------------------------------------------------------------
# insert_feats tests
# ---------------------------------------------------------------------------


MINIMAL_FEAT: dict = {
    "name": "Power Attack",
    "description": "Trade attack bonus for damage.",
    "free": False,
    "passive": False,
    "active": True,
    "stance": False,
    "metamagic": False,
    "epic_destiny": False,
    "bonus_classes": [],
}


def test_insert_feats_basic() -> None:
    """Basic feat fields round-trip through feats table."""
    with GameDB(":memory:") as db:
        db.create_schema()
        count = db.insert_feats([MINIMAL_FEAT])
        assert count == 1
        row = db.conn.execute(
            "SELECT name, is_active, is_passive FROM feats WHERE name = ?",
            ("Power Attack",),
        ).fetchone()
    assert row is not None
    assert row[0] == "Power Attack"
    assert row[1] == 1   # is_active = True
    assert row[2] == 0   # is_passive = False


def test_insert_feats_boolean_flags() -> None:
    """All boolean flag fields are stored as 0/1 integers."""
    feat = {
        "name": "Empower Spell",
        "free": True,
        "passive": True,
        "active": False,
        "stance": False,
        "metamagic": True,
        "epic_destiny": False,
        "bonus_classes": [],
    }
    with GameDB(":memory:") as db:
        db.create_schema()
        db.insert_feats([feat])
        row = db.conn.execute(
            "SELECT is_free, is_passive, is_active, is_stance, is_metamagic, is_epic_destiny "
            "FROM feats WHERE name = ?",
            ("Empower Spell",),
        ).fetchone()
    assert row == (1, 1, 0, 0, 1, 0)


def test_insert_feats_bonus_classes_with_known_class() -> None:
    """bonus_classes entries create feat_bonus_classes rows when class exists."""
    with GameDB(":memory:") as db:
        db.create_schema()
        # Seed a class so the FK resolves
        db.conn.execute(
            "INSERT INTO classes (name) VALUES (?)", ("Fighter",)
        )
        feat = {
            "name": "Cleave",
            "active": True,
            "free": False, "passive": False, "stance": False,
            "metamagic": False, "epic_destiny": False,
            "bonus_classes": ["Fighter"],
        }
        db.insert_feats([feat])
        row = db.conn.execute(
            "SELECT f.name, c.name FROM feat_bonus_classes fbc "
            "JOIN feats f ON fbc.feat_id = f.id "
            "JOIN classes c ON fbc.class_id = c.id",
        ).fetchone()
    assert row is not None
    assert row[0] == "Cleave"
    assert row[1] == "Fighter"


def test_insert_feats_bonus_classes_unknown_class() -> None:
    """Unknown class names in bonus_classes are silently skipped."""
    feat = {
        "name": "Weapon Focus",
        "active": False, "free": False, "passive": True,
        "stance": False, "metamagic": False, "epic_destiny": False,
        "bonus_classes": ["Fighter", "Paladin"],  # neither class seeded
    }
    with GameDB(":memory:") as db:
        db.create_schema()
        count = db.insert_feats([feat])
        assert count == 1   # feat itself inserted
        bonus_count = _count(db.conn, "feat_bonus_classes")
    assert bonus_count == 0   # no junction rows (classes not in DB)


def test_insert_feats_past_life_subtype() -> None:
    """Past life feats populate feat_past_life_stats; class_id resolved by name."""
    with GameDB(":memory:") as db:
        db.create_schema()
        db.conn.execute("INSERT INTO classes (name) VALUES (?)", ("Fighter",))
        feat = {
            "name": "Past Life: Fighter",
            "passive": True,
            "free": False, "active": False, "stance": False,
            "metamagic": False, "epic_destiny": False,
            "past_life_type": "heroic",
            "past_life_class": "Fighter",
            "past_life_max_stacks": 3,
        }
        db.insert_feats([feat])
        row = db.conn.execute(
            """
            SELECT pls.past_life_type, pls.max_stacks, c.name
            FROM feat_past_life_stats pls
            JOIN feats f ON f.id = pls.feat_id
            LEFT JOIN classes c ON c.id = pls.class_id
            WHERE f.name = ?
            """,
            ("Past Life: Fighter",),
        ).fetchone()
    assert row == ("heroic", 3, "Fighter")


def test_insert_feats_idempotent() -> None:
    """Inserting the same feat twice does not raise or duplicate rows."""
    with GameDB(":memory:") as db:
        db.create_schema()
        db.insert_feats([MINIMAL_FEAT])
        db.insert_feats([MINIMAL_FEAT])
        assert _count(db.conn, "feats") == 1


# ---------------------------------------------------------------------------
# insert_enhancement_trees tests
# ---------------------------------------------------------------------------


KENSEI_TREE: dict = {
    "name": "Kensei",
    "type": "class",
    "class_or_race": "Fighter",
    "enhancements": [
        {
            "name": "Weapon Specialization",
            "icon": "icon_kensei.png",
            "description": "You gain Weapon Specialization.",
            "ranks": 3,
            "ap_cost": 1,
            "progression": 0,
            "level": "Fighter Level 1",
            "prerequisite": None,
            "tier": "core",
        },
        {
            "name": "Strike With No Thought",
            "icon": None,
            "description": "Your attacks are faster.",
            "ranks": 1,
            "ap_cost": 2,
            "progression": 5,
            "level": "Fighter Level 3",
            "prerequisite": "Weapon Specialization",
            "tier": "1",
        },
    ],
}


def test_insert_enhancement_trees_basic() -> None:
    """Enhancement tree and its enhancements are inserted correctly."""
    with GameDB(":memory:") as db:
        db.create_schema()
        count = db.insert_enhancement_trees([KENSEI_TREE])
        assert count == 1
        tree = db.conn.execute(
            "SELECT name, tree_type, ap_pool FROM enhancement_trees WHERE name = ?",
            ("Kensei",),
        ).fetchone()
        assert tree is not None
        assert tree[0] == "Kensei"
        # Without Fighter in classes table, falls back to 'universal'
        assert tree[1] == "universal"
        assert tree[2] == "heroic"
        enh_count = _count(db.conn, "enhancements")
    assert enh_count == 2


def test_insert_enhancement_trees_class_link_resolved() -> None:
    """tree_type='class' links to class_id when class exists in classes table."""
    with GameDB(":memory:") as db:
        db.create_schema()
        db.conn.execute("INSERT INTO classes (name) VALUES (?)", ("Fighter",))
        db.insert_enhancement_trees([KENSEI_TREE])
        row = db.conn.execute(
            "SELECT t.tree_type, c.name FROM enhancement_trees t "
            "LEFT JOIN classes c ON t.class_id = c.id WHERE t.name = ?",
            ("Kensei",),
        ).fetchone()
    assert row is not None
    assert row[0] == "class"
    assert row[1] == "Fighter"


def test_insert_enhancement_trees_ranks() -> None:
    """Each enhancement gets an enhancement_ranks row (rank=1) from its description."""
    with GameDB(":memory:") as db:
        db.create_schema()
        db.insert_enhancement_trees([KENSEI_TREE])
        ranks = db.conn.execute(
            "SELECT er.rank, er.description FROM enhancement_ranks er "
            "JOIN enhancements e ON er.enhancement_id = e.id "
            "WHERE e.name = ?",
            ("Weapon Specialization",),
        ).fetchall()
    assert len(ranks) == 1
    assert ranks[0][0] == 1
    assert ranks[0][1] == "You gain Weapon Specialization."


def test_insert_enhancement_trees_max_ranks() -> None:
    """The ranks field from the dict maps to max_ranks column."""
    with GameDB(":memory:") as db:
        db.create_schema()
        db.insert_enhancement_trees([KENSEI_TREE])
        row = db.conn.execute(
            "SELECT max_ranks FROM enhancements WHERE name = ?",
            ("Weapon Specialization",),
        ).fetchone()
    assert row is not None
    assert row[0] == 3


def test_insert_enhancement_trees_universal() -> None:
    """Universal trees have ap_pool='heroic' and no class_id/race_id."""
    tree = {
        "name": "Harper Agent",
        "type": "universal",
        "class_or_race": None,
        "enhancements": [],
    }
    with GameDB(":memory:") as db:
        db.create_schema()
        db.insert_enhancement_trees([tree])
        row = db.conn.execute(
            "SELECT tree_type, ap_pool, class_id, race_id "
            "FROM enhancement_trees WHERE name = ?",
            ("Harper Agent",),
        ).fetchone()
    assert row is not None
    assert row[0] == "universal"
    assert row[1] == "heroic"
    assert row[2] is None
    assert row[3] is None


def test_insert_enhancement_trees_racial() -> None:
    """Racial trees have ap_pool='racial'."""
    tree = {
        "name": "Deepwood Stalker",
        "type": "racial",
        "class_or_race": "Elf",
        "enhancements": [],
    }
    with GameDB(":memory:") as db:
        db.create_schema()
        db.conn.execute("INSERT INTO races (name) VALUES (?)", ("Elf",))
        db.insert_enhancement_trees([tree])
        row = db.conn.execute(
            "SELECT tree_type, ap_pool FROM enhancement_trees WHERE name = ?",
            ("Deepwood Stalker",),
        ).fetchone()
    assert row is not None
    assert row[0] == "racial"
    assert row[1] == "racial"


def test_insert_enhancement_trees_idempotent() -> None:
    """Inserting the same tree twice does not raise or duplicate rows."""
    with GameDB(":memory:") as db:
        db.create_schema()
        db.insert_enhancement_trees([KENSEI_TREE])
        db.insert_enhancement_trees([KENSEI_TREE])
        assert _count(db.conn, "enhancement_trees") == 1
        assert _count(db.conn, "enhancements") == 2
