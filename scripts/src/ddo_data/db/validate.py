"""Post-import data validation assertions for the DDO game database.

Each assertion is a SQL query that should return 0 rows. If rows are returned,
they represent data integrity issues. Run after all insert_* calls complete.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """Result of a single validation check."""

    name: str
    description: str
    severity: str  # "error" or "warning"
    failures: list[dict]

    @property
    def passed(self) -> bool:
        return len(self.failures) == 0


# Each assertion: (name, description, severity, query, column_names)
# Query should return rows that FAIL the assertion (0 rows = pass).
_ASSERTIONS: list[tuple[str, str, str, str, list[str]]] = [
    # --- Enhancement integrity ---
    (
        "enhancement_ranks_match_max_ranks",
        "Enhancements with max_ranks > 1 should have that many rank rows",
        "warning",
        """
        SELECT e.name, et.name AS tree, e.max_ranks,
               COUNT(er.rank) AS actual_ranks
        FROM enhancements e
        JOIN enhancement_trees et ON et.id = e.tree_id
        LEFT JOIN enhancement_ranks er ON er.enhancement_id = e.id
        WHERE e.max_ranks > 1
        GROUP BY e.id
        HAVING actual_ranks < e.max_ranks
        LIMIT 20
        """,
        ["name", "tree", "max_ranks", "actual_ranks"],
    ),
    (
        "enhancement_bonus_stat_resolved",
        "Enhancement bonuses should have resolved stat_id (not NULL)",
        "warning",
        """
        SELECT b.name, b.description, e.name AS enhancement, et.name AS tree
        FROM enhancement_bonuses eb
        JOIN bonuses b ON b.id = eb.bonus_id
        JOIN enhancements e ON e.id = eb.enhancement_id
        JOIN enhancement_trees et ON et.id = e.tree_id
        WHERE b.stat_id IS NULL
        LIMIT 20
        """,
        ["bonus_name", "description", "enhancement", "tree"],
    ),
    # --- Item integrity ---
    (
        "items_have_equipment_slot",
        "Items should have equipment_slot or item_type set",
        "warning",
        """
        SELECT name, item_category, rarity
        FROM items
        WHERE equipment_slot IS NULL AND item_type IS NULL AND item_category IS NULL
        LIMIT 20
        """,
        ["name", "item_category", "rarity"],
    ),
    (
        "weapon_items_have_weapon_stats",
        "Wiki-matched Main Hand items should have weapon stats",
        "warning",
        """
        SELECT i.name, i.equipment_slot
        FROM items i
        LEFT JOIN item_weapon_stats ws ON ws.item_id = i.id
        WHERE i.equipment_slot = 'Main Hand'
          AND ws.item_id IS NULL
          AND i.wiki_url IS NOT NULL
        LIMIT 20
        """,
        ["name", "equipment_slot"],
    ),
    (
        "weapons_have_handedness",
        "Weapons should have handedness set",
        "warning",
        """
        SELECT i.name, ws.weapon_type, ws.proficiency
        FROM items i
        JOIN item_weapon_stats ws ON ws.item_id = i.id
        WHERE ws.handedness IS NULL
          AND i.wiki_url IS NOT NULL
        LIMIT 20
        """,
        ["name", "weapon_type", "proficiency"],
    ),
    (
        "item_bonus_stat_resolved",
        "Item bonuses from wiki should have resolved stat_id",
        "warning",
        """
        SELECT b.name, b.description, i.name AS item
        FROM item_bonuses ib
        JOIN bonuses b ON b.id = ib.bonus_id
        JOIN items i ON i.id = ib.item_id
        WHERE b.stat_id IS NULL AND ib.data_source = 'wiki'
        LIMIT 20
        """,
        ["bonus_name", "description", "item"],
    ),
    # --- Feat integrity ---
    (
        "feat_self_prereq",
        "Feats should not require themselves",
        "error",
        """
        SELECT f.name
        FROM feat_prereq_feats pf
        JOIN feats f ON f.id = pf.feat_id
        WHERE pf.feat_id = pf.required_feat_id
        """,
        ["name"],
    ),
    (
        "enhancement_self_prereq",
        "Enhancements should not require themselves",
        "error",
        """
        SELECT e.name, et.name AS tree
        FROM enhancement_prereqs ep
        JOIN enhancements e ON e.id = ep.enhancement_id
        JOIN enhancement_trees et ON et.id = e.tree_id
        WHERE ep.enhancement_id = ep.required_enhancement_id
        """,
        ["name", "tree"],
    ),
    # --- Referential sanity ---
    (
        "bonuses_have_name",
        "Every bonus should have a non-empty name",
        "error",
        """
        SELECT id, stat_id, bonus_type_id, value
        FROM bonuses
        WHERE name IS NULL OR name = ''
        LIMIT 10
        """,
        ["id", "stat_id", "bonus_type_id", "value"],
    ),
    (
        "set_bonus_items_resolve",
        "Set bonus items should reference existing items",
        "warning",
        """
        SELECT sb.name AS set_name, sbi.item_id
        FROM set_bonus_items sbi
        JOIN set_bonuses sb ON sb.id = sbi.set_id
        LEFT JOIN items i ON i.id = sbi.item_id
        WHERE i.id IS NULL
        LIMIT 20
        """,
        ["set_name", "item_id"],
    ),
    # --- Seed data staleness checks ---
    # These detect when wiki-scraped data references classes/races not in seed tables.
    (
        "enhancement_trees_class_seeded",
        "Class enhancement trees should reference classes that exist in seed data",
        "error",
        """
        SELECT name, tree_type FROM enhancement_trees
        WHERE tree_type = 'class' AND class_id IS NULL
        """,
        ["tree_name", "tree_type"],
    ),
    (
        "enhancement_trees_race_seeded",
        "Racial enhancement trees should reference races that exist in seed data",
        "error",
        """
        SELECT name, tree_type FROM enhancement_trees
        WHERE tree_type = 'racial' AND race_id IS NULL
        """,
        ["tree_name", "tree_type"],
    ),
    (
        "classes_have_skills",
        "Every base class should have class skills (archetypes inherit from parent)",
        "error",
        """
        SELECT c.name FROM classes c
        LEFT JOIN class_skills cs ON cs.class_id = c.id
        WHERE cs.class_id IS NULL AND c.is_archetype = 0
        """,
        ["class_name"],
    ),
    (
        "races_have_ability_bonuses",
        "Standard races should have ability bonuses (Human/Half-Elf exempt: player chooses)",
        "warning",
        """
        SELECT r.name FROM races r
        LEFT JOIN race_ability_bonuses rab ON rab.race_id = r.id
        WHERE rab.race_id IS NULL
          AND r.name NOT IN ('Human', 'Half-Elf')
          AND r.id <= 17
        """,
        ["race_name"],
    ),
    # --- Past life cross-reference ---
    (
        "past_life_classes_seeded",
        "Past Life feat names should match seeded classes/archetypes",
        "error",
        """
        SELECT REPLACE(f.name, 'Past Life: ', '') AS past_life_name
        FROM feats f
        WHERE f.name LIKE 'Past Life: %'
          AND REPLACE(f.name, 'Past Life: ', '') NOT IN (SELECT name FROM classes)
          AND REPLACE(f.name, 'Past Life: ', '') NOT IN (
              'Arcane Initiate', 'Arcane Prodigy', 'Bardic Dilettante',
              'Berserker''s Fury', 'Delver of the Forbidden',
              'Disciple of the Fist', 'Harbinger of Nature''s Wrath',
              'Initiate of the Faith', 'Mixer of Magics',
              'Sneak of Shadows', 'Soldier of the Faith',
              'Student of Artifice', 'Student of the Sword',
              'Warrior of the Wild', 'Acolyte of Divine Secrets'
          )
        """,
        ["past_life_name"],
    ),
    # --- Icon coverage checks ---
    (
        "feats_have_icons",
        "Feats should have icon filenames (>95% expected)",
        "warning",
        """
        SELECT name FROM feats WHERE icon IS NULL OR icon = ''
        LIMIT 20
        """,
        ["name"],
    ),
    (
        "enhancements_have_icons",
        "Enhancements should have icon filenames (100% expected)",
        "warning",
        """
        SELECT name FROM enhancements WHERE icon IS NULL OR icon = ''
        LIMIT 20
        """,
        ["name"],
    ),
    # --- Population checks ---
    (
        "tables_not_empty",
        "Core tables should have data",
        "error",
        """
        SELECT t, n FROM (
            SELECT 'items' AS t, (SELECT COUNT(*) FROM items) AS n
            UNION ALL SELECT 'feats', (SELECT COUNT(*) FROM feats)
            UNION ALL SELECT 'enhancements', (SELECT COUNT(*) FROM enhancements)
            UNION ALL SELECT 'spells', (SELECT COUNT(*) FROM spells)
            UNION ALL SELECT 'augments', (SELECT COUNT(*) FROM augments)
        ) WHERE n = 0
        """,
        ["table", "count"],
    ),
]


def validate_database(conn: sqlite3.Connection) -> list[ValidationResult]:
    """Run all validation assertions and return results."""
    results = []
    for name, desc, severity, query, columns in _ASSERTIONS:
        try:
            rows = conn.execute(query).fetchall()
            failures = [dict(zip(columns, row)) for row in rows]
        except sqlite3.OperationalError as e:
            # Table might not exist if build-db was run with --type filter
            failures = [{"error": str(e)}]
        results.append(ValidationResult(
            name=name, description=desc, severity=severity, failures=failures,
        ))
    return results


def validate_seed_against_wiki(conn: sqlite3.Connection) -> list[ValidationResult]:
    """Check that seed data covers all classes/races discovered from wiki.

    Queries DDO wiki category pages to discover what classes and races
    exist, then compares against the classes/races seed tables.
    Returns errors for any wiki-known class/race missing from seed.
    """
    results = []
    try:
        from ..wiki.client import WikiClient

        client = WikiClient(use_cache=True)

        # Discover classes from Category:Base classes
        wiki_classes: set[str] = set()
        for title in client.iter_category_members("Base classes"):
            if not title.startswith("Category:"):
                wiki_classes.add(title)

        # Discover races from Category:Races (filter out non-race pages)
        wiki_races: set[str] = set()
        _NON_RACE_PAGES = {"Races", "Race", "Racial Variant differences"}
        # Wiki names that map to different seed names
        _RACE_ALIASES = {
            "Drow": "Drow Elf",
            "Sun Elf (Morninglord)": "Morninglord",
            "Purple Dragon Knight (Iconic)": "Purple Dragon Knight",
            "PDK": "Purple Dragon Knight",
        }
        _SKIP_RACES = {"Kalashtar", "Elven Arcane Archer"}  # not playable races
        for title in client.iter_category_members("Races"):
            if title.startswith("Category:") or title in _NON_RACE_PAGES:
                continue
            if "(speculation)" in title or title in _SKIP_RACES:
                continue
            wiki_races.add(_RACE_ALIASES.get(title, title))

        # Compare against DB seed
        db_classes = {row[0] for row in conn.execute("SELECT name FROM classes").fetchall()}
        db_races = {row[0] for row in conn.execute("SELECT name FROM races").fetchall()}

        missing_classes = wiki_classes - db_classes
        missing_races = wiki_races - db_races

        results.append(ValidationResult(
            name="wiki_classes_seeded",
            description="All wiki-discovered classes should exist in seed data",
            severity="error",
            failures=[{"missing_class": c} for c in sorted(missing_classes)],
        ))
        results.append(ValidationResult(
            name="wiki_races_seeded",
            description="All wiki-discovered races should exist in seed data",
            severity="error",
            failures=[{"missing_race": r} for r in sorted(missing_races)],
        ))

    except Exception as e:
        results.append(ValidationResult(
            name="wiki_seed_check",
            description="Wiki seed validation (requires network)",
            severity="warning",
            failures=[{"error": f"Skipped: {e}"}],
        ))

    return results


def format_validation(results: list[ValidationResult]) -> str:
    """Format validation results as a human-readable report."""
    lines = []
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    errors = sum(1 for r in results if not r.passed and r.severity == "error")
    warnings = sum(1 for r in results if not r.passed and r.severity == "warning")

    lines.append(f"Validation: {passed}/{len(results)} passed")
    if errors:
        lines.append(f"  {errors} error(s)")
    if warnings:
        lines.append(f"  {warnings} warning(s)")

    for r in results:
        if r.passed:
            continue
        icon = "X" if r.severity == "error" else "!"
        lines.append(f"\n  [{icon}] {r.name}: {r.description}")
        for f in r.failures[:5]:
            lines.append(f"      {f}")
        if len(r.failures) > 5:
            lines.append(f"      ... and {len(r.failures) - 5} more")

    return "\n".join(lines)
