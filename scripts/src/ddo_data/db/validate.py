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
        "Items with equipment_slot='Main Hand' should have weapon stats",
        "warning",
        """
        SELECT i.name, i.equipment_slot
        FROM items i
        LEFT JOIN item_weapon_stats ws ON ws.item_id = i.id
        WHERE i.equipment_slot = 'Main Hand'
          AND ws.item_id IS NULL
        LIMIT 20
        """,
        ["name", "equipment_slot"],
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
