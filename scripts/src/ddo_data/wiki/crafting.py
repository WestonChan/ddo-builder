"""Cannith Crafting wiki scraper — enchantment definitions, scaling values, and slot assignments."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

from .client import WikiClient

logger = logging.getLogger(__name__)

# Mapping from table_1b equipment slot names to our DB equipment_slot names
_SLOT_ALIAS = {
    "belts": "Waist",
    "boots": "Feet",
    "bracers": "Wrists",
    "cloaks": "Back",
    "gloves": "Arms",
    "goggles": "Goggles",
    "headgear": "Head",
    "helms": "Head",
    "necklaces": "Neck",
    "rings": "Ring",
    "trinkets": "Trinket",
    "armor": "Body",
    "armors": "Body",
    "shields": "Off Hand",
    "melee weapons": "Main Hand",
    "melee": "Main Hand",
    "ranged weapons": "Ranged",
    "ranged": "Ranged",
    "rune arms": "Runearm",
    "runearms": "Runearm",
    "orbs": "Off Hand",
    "weapons": "Main Hand",
}


def _clean_cell(text: str) -> str:
    """Strip wiki markup, class attributes, bold markers from a cell value."""
    text = re.sub(r'class="[^"]*"\s*\|', "", text)
    text = re.sub(r"style=\"[^\"]*\"\s*\|", "", text)
    text = re.sub(r"'''", "", text)
    text = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", text)
    text = re.sub(r"\{\{[^}]+\}\}", "", text)
    return text.strip()


def _parse_scaling_values(wikitext: str) -> dict[str, dict[int, str]]:
    """Parse table_3b: enchantment name -> {min_level: value}.

    Returns a dict mapping enchantment group name to a dict of ML -> value.
    """
    results: dict[str, dict[int, str]] = {}

    # Split into rows on |-
    rows = re.split(r"\n\|-", wikitext)

    for row in rows:
        # Normalize multiline rows: join continuation lines that start with
        # | class="highlight" | into a single line of || separated cells
        lines = row.strip().split("\n")
        normalized = ""
        for line in lines:
            line = line.strip()
            # Continuation lines start with | class="highlight" |
            cont = re.match(r'\|\s*class="highlight"\s*\|\s*(.*)', line)
            if cont:
                normalized += " || " + cont.group(1)
            elif line.startswith("|") and not line.startswith("|+") and not line.startswith("|}"):
                normalized += line
            # Skip header lines (!)
        if not normalized:
            continue

        cells = re.split(r"\|\|", normalized)
        if len(cells) < 2:
            continue

        # First cell: enchantment name (may have | prefix, bold, whitespace)
        first = cells[0]
        name_match = re.search(r"\|\s*(.*)", first)
        if not name_match:
            continue
        name = _clean_cell(name_match.group(1))
        if not name or name.startswith("Min Level") or name.startswith("!"):
            continue

        # Remove trailing * from system enchantments
        name = name.rstrip("*").strip()

        # Parse values for ML 1-34
        values: dict[int, str] = {}
        for i, cell in enumerate(cells[1:], start=1):
            if i > 34:
                break
            val = _clean_cell(cell)
            if val and val != "-" and val != "\u2013" and val != "??":
                values[i] = val

        if values:
            results[name] = values

    return results


def _parse_slot_assignments(wikitext: str) -> dict[str, list[tuple[str, str]]]:
    """Parse table_1b: enchantment name -> [(equipment_slot, affix_type), ...].

    Returns a dict mapping enchantment name to a list of (slot_name, affix_type) tuples.
    """
    assignments: dict[str, list[tuple[str, str]]] = {}

    # Split by section headers (==Equipment Slot==)
    sections = re.split(r"\n==([^=]+)==", wikitext)

    for i in range(1, len(sections), 2):
        slot_name_raw = sections[i].strip()
        section_body = sections[i + 1] if i + 1 < len(sections) else ""

        # Map wiki slot name to our DB name
        slot_name = _SLOT_ALIAS.get(slot_name_raw.lower(), slot_name_raw)

        # Find the table row with prefix/suffix/extra columns
        # The row starts with ! scope="row" and has 3 data cells
        # Split on top-level | that separates columns
        # Find each column by splitting the row

        for affix_idx, affix_type in enumerate(["prefix", "suffix", "extra"]):
            # Extract enchantment names from each column section
            # They're in {{div col}}...{{div col end}} blocks
            # Use a broader pattern: find bullet list items
            col_pattern = rf"(prefix|suffix|extra)"

            # Find all [[Link]] entries in the section
            pass

        # Simpler approach: split the table row into 3 data cells
        # Look for the data row after the header
        row_match = re.search(
            r'!\s*scope="row"[^|]*\|[^\n]*\n(.*?)(?:\n\|-|\n\|\})',
            section_body,
            re.DOTALL,
        )
        if not row_match:
            # Try splitting on | at the start of lines
            pass

        # Parse by finding div col blocks which separate prefix/suffix/extra
        div_blocks = re.split(r"\{\{div col end\}\}", section_body)

        affix_types = ["prefix", "suffix", "extra"]
        for block_idx, block in enumerate(div_blocks[:3]):
            if block_idx >= len(affix_types):
                break
            affix = affix_types[block_idx]

            # Extract all [[Link]] names from this block
            for link_match in re.finditer(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", block):
                ench_name = link_match.group(1).strip()
                if ench_name and ench_name not in (
                    "Cannith Crafting", "Enhancement bonus", "Augment",
                ):
                    if ench_name not in assignments:
                        assignments[ench_name] = []
                    assignments[ench_name].append((slot_name, affix))

    return assignments


def _parse_recipes(wikitext: str) -> list[dict]:
    """Parse table_2c/2b: enchantment recipes with crafting level and slot text.

    Returns list of dicts with: name, group, crafting_level, prefix_slots, suffix_slots, extra_slots.
    """
    recipes: list[dict] = []

    rows = re.split(r"\n\|-", wikitext)
    for row in rows:
        # Data rows have cells separated by ||
        cells = [c.strip() for c in re.split(r"\|\|", row)]
        if len(cells) < 18:
            continue

        # First cell may have leading |
        first = cells[0]
        group_match = re.search(r"\|\s*(.*)", first)
        if not group_match:
            continue
        group = _clean_cell(group_match.group(1))
        if not group or group.startswith("!") or group == "Group":
            continue

        name = _clean_cell(cells[1])
        if not name:
            continue

        # Crafting level is in cells[2] (bound level)
        crafting_level_str = _clean_cell(cells[2])
        try:
            crafting_level = int(crafting_level_str)
        except (ValueError, TypeError):
            crafting_level = None

        # Last 3 cells are prefix/suffix/extra slot assignments (text lists)
        prefix_text = _clean_cell(cells[-3]) if len(cells) >= 3 else ""
        suffix_text = _clean_cell(cells[-2]) if len(cells) >= 2 else ""
        extra_text = _clean_cell(cells[-1]) if len(cells) >= 1 else ""

        recipes.append({
            "name": name,
            "group": group,
            "crafting_level": crafting_level,
            "prefix_slots": prefix_text,
            "suffix_slots": suffix_text,
            "extra_slots": extra_text,
        })

    return recipes


def _parse_slot_text(slot_text: str) -> list[str]:
    """Parse comma-separated slot names from recipe table cells.

    E.g., "Helms, Trinkets, Armors, Shields" -> ["Head", "Trinket", "Body", "Off Hand"]
    """
    if not slot_text:
        return []
    slots = []
    for part in slot_text.split(","):
        part = part.strip()
        mapped = _SLOT_ALIAS.get(part.lower())
        if mapped:
            slots.append(mapped)
        elif part:
            logger.debug("Unknown slot name in recipe: %r", part)
    return slots


def collect_crafting(
    client: WikiClient,
    *,
    on_progress: Callable[[str], None] | None = None,
) -> dict:
    """Scrape Cannith Crafting data from wiki.

    Returns a dict with:
        enchantments: list of enchantment dicts
        values: dict of {name: {ml: value}}
        slots: dict of {name: [(equipment_slot, affix_type), ...]}
    """
    # 1. Fetch scaling values (table_3b)
    if on_progress:
        on_progress("  Fetching crafting scaling values...")
    wikitext_3b = client.get_wikitext("Cannith_Crafting/table_3b")
    scaling_values = _parse_scaling_values(wikitext_3b) if wikitext_3b else {}
    if on_progress:
        on_progress(f"  {len(scaling_values)} scaling enchantment groups parsed")

    # 2. Fetch recipes (table_2c for scaling, table_2b for non-scaling)
    if on_progress:
        on_progress("  Fetching crafting recipes...")
    wikitext_2c = client.get_wikitext("Cannith_Crafting/table_2c")
    scaling_recipes = _parse_recipes(wikitext_2c) if wikitext_2c else []

    wikitext_2b = client.get_wikitext("Cannith_Crafting/table_2b")
    non_scaling_recipes = _parse_recipes(wikitext_2b) if wikitext_2b else []

    if on_progress:
        on_progress(
            f"  {len(scaling_recipes)} scaling + {len(non_scaling_recipes)} "
            f"non-scaling recipes parsed"
        )

    # 3. Fetch slot assignments (table_1b)
    if on_progress:
        on_progress("  Fetching crafting slot assignments...")
    wikitext_1b = client.get_wikitext("Cannith_Crafting/table_1b")
    slot_assignments = _parse_slot_assignments(wikitext_1b) if wikitext_1b else {}
    if on_progress:
        on_progress(f"  {len(slot_assignments)} enchantments with slot assignments")

    # 4. Build unified enchantment list from recipes
    enchantments: list[dict] = []
    seen_names: set[str] = set()

    for recipe in scaling_recipes:
        name = recipe["name"]
        if name in seen_names:
            continue
        seen_names.add(name)

        # Build slot list from recipe text
        slots: list[tuple[str, str]] = []
        for slot_name in _parse_slot_text(recipe["prefix_slots"]):
            slots.append((slot_name, "prefix"))
        for slot_name in _parse_slot_text(recipe["suffix_slots"]):
            slots.append((slot_name, "suffix"))
        for slot_name in _parse_slot_text(recipe["extra_slots"]):
            slots.append((slot_name, "extra"))

        enchantments.append({
            "name": name,
            "group": recipe["group"],
            "crafting_level": recipe["crafting_level"],
            "is_scaling": True,
            "slots": slots,
        })

    for recipe in non_scaling_recipes:
        name = recipe["name"]
        if name in seen_names:
            continue
        seen_names.add(name)

        slots = []
        for slot_name in _parse_slot_text(recipe["prefix_slots"]):
            slots.append((slot_name, "prefix"))
        for slot_name in _parse_slot_text(recipe["suffix_slots"]):
            slots.append((slot_name, "suffix"))
        for slot_name in _parse_slot_text(recipe["extra_slots"]):
            slots.append((slot_name, "extra"))

        enchantments.append({
            "name": name,
            "group": recipe["group"],
            "crafting_level": recipe["crafting_level"],
            "is_scaling": False,
            "slots": slots,
        })

    # Merge slot data from table_1b as supplementary source
    for ench in enchantments:
        if not ench["slots"] and ench["name"] in slot_assignments:
            ench["slots"] = slot_assignments[ench["name"]]

    return {
        "enchantments": enchantments,
        "values": scaling_values,
        "slot_assignments": slot_assignments,
    }
