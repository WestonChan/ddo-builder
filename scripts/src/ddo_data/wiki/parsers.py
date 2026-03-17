"""Wikitext template extraction and item field parsing for DDO Wiki."""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Template extraction (MediaWiki {{Template|key=value|...}} syntax)
# ---------------------------------------------------------------------------

_LINK_RE = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_TEMPLATE_RE = re.compile(r"\{\{[^}]*\}\}")


def extract_template(
    wikitext: str, template_name: str,
) -> dict[str, str] | None:
    """Extract fields from the first {{template_name|...}} occurrence.

    Returns dict of field_name -> raw_value. Handles nested {{...}} via
    brace counting. First positional arg (before any key=value) is stored
    with key ``_positional_1``.

    Returns None if the template is not found.
    """
    # Find the template start (case-insensitive)
    lower = wikitext.lower()
    marker = "{{" + template_name.lower()
    start = lower.find(marker)
    if start == -1:
        return None

    # Move past the "{{template_name" prefix
    pos = start + len(marker)

    # The next character should be | or whitespace or }}
    # Skip to the first | at depth 0 (the template's own pipe)
    depth = 1  # we're inside the outer {{ already
    bracket_depth = 0  # track [[...]] wiki links
    fields_raw: list[str] = []
    current: list[str] = []

    while pos < len(wikitext) and depth > 0:
        ch = wikitext[pos]

        if ch == "[" and pos + 1 < len(wikitext) and wikitext[pos + 1] == "[":
            bracket_depth += 1
            current.append("[[")
            pos += 2
            continue

        if ch == "]" and pos + 1 < len(wikitext) and wikitext[pos + 1] == "]":
            bracket_depth = max(0, bracket_depth - 1)
            current.append("]]")
            pos += 2
            continue

        if ch == "{" and pos + 1 < len(wikitext) and wikitext[pos + 1] == "{":
            depth += 1
            current.append("{{")
            pos += 2
            continue

        if ch == "}" and pos + 1 < len(wikitext) and wikitext[pos + 1] == "}":
            depth -= 1
            if depth == 0:
                # End of template
                fields_raw.append("".join(current))
                break
            current.append("}}")
            pos += 2
            continue

        if ch == "|" and depth == 1 and bracket_depth == 0:
            fields_raw.append("".join(current))
            current = []
            pos += 1
            continue

        current.append(ch)
        pos += 1

    if depth != 0:
        return None  # Unclosed template

    result: dict[str, str] = {}
    positional_index = 0

    for field_str in fields_raw:
        field_str = field_str.strip()
        if not field_str:
            continue

        eq_pos = field_str.find("=")
        if eq_pos > 0 and not field_str[:eq_pos].strip().startswith("{"):
            key = field_str[:eq_pos].strip().lower()
            value = field_str[eq_pos + 1:].strip()
            result[key] = value
        else:
            # Positional argument
            positional_index += 1
            result[f"_positional_{positional_index}"] = field_str

    return result


def extract_all_templates(
    wikitext: str, template_name: str,
) -> list[dict[str, str]]:
    """Extract fields from ALL occurrences of a template."""
    results: list[dict[str, str]] = []
    remaining = wikitext
    while True:
        fields = extract_template(remaining, template_name)
        if fields is None:
            break
        results.append(fields)
        # Find and skip past this occurrence to look for the next
        lower = remaining.lower()
        marker = "{{" + template_name.lower()
        start = lower.find(marker)
        if start == -1:
            break
        remaining = remaining[start + len(marker):]
    return results


def clean_wikitext(value: str) -> str:
    """Strip wiki markup from a field value.

    Converts [[Target|Display]] to Display, [[Simple]] to Simple.
    Removes HTML tags. Strips leading/trailing whitespace.
    """
    # Handle wiki links: [[target|display]] -> display, [[simple]] -> simple
    text = _LINK_RE.sub(r"\1", value)
    # Replace HTML tags with space (preserves word boundaries around <br/> etc.)
    text = _HTML_TAG_RE.sub(" ", text)
    # Remove remaining template markers (simple ones)
    text = _TEMPLATE_RE.sub("", text)
    # Collapse whitespace
    text = " ".join(text.split())
    return text.strip()


# ---------------------------------------------------------------------------
# Item parser
# ---------------------------------------------------------------------------


def _parse_int(value: str) -> int | None:
    """Try to parse an integer from a wiki field value."""
    cleaned = clean_wikitext(value).strip()
    # Handle common patterns like "10" or "ML:10"
    match = re.search(r"\d+", cleaned)
    if match:
        return int(match.group())
    return None


def _parse_float(value: str) -> float | None:
    """Try to parse a float from a wiki field value."""
    cleaned = clean_wikitext(value).strip()
    match = re.search(r"[\d.]+", cleaned)
    if match:
        try:
            return float(match.group())
        except ValueError:
            pass
    return None


def _parse_list(value: str) -> list[str]:
    """Parse a bulleted or newline-separated list from a wiki field.

    Handles:
    - Lines starting with * (wiki bullet lists)
    - Newline-separated items
    - Comma-separated items as fallback
    """
    lines = value.split("\n")
    items: list[str] = []
    for line in lines:
        line = line.strip().lstrip("*").strip()
        if not line:
            continue
        cleaned = clean_wikitext(line)
        if cleaned:
            items.append(cleaned)

    if not items and value.strip():
        # Fallback: try comma separation
        for part in value.split(","):
            cleaned = clean_wikitext(part)
            if cleaned:
                items.append(cleaned)

    return items


def parse_item_wikitext(wikitext: str) -> dict[str, Any] | None:
    """Parse a DDO Wiki item page's wikitext into a structured dict.

    Extracts data from the ``{{Named item|TYPE|...}}`` template.
    Returns None if the template is not found.
    """
    fields = extract_template(wikitext, "Named item")
    if fields is None:
        return None

    item: dict[str, Any] = {}

    # Name (required)
    name = fields.get("name", "")
    item["name"] = clean_wikitext(name) if name else None

    # Item category from positional arg (Weapon, Armor, Jewelry, etc.)
    item["item_type"] = fields.get("_positional_1", "").strip() or None

    # Numeric fields
    item["minimum_level"] = _parse_int(fields.get("minlevel", ""))
    item["enhancement_bonus"] = _parse_int(fields.get("enchantmentbonus", ""))
    item["durability"] = _parse_int(fields.get("durability", ""))
    item["hardness"] = _parse_int(fields.get("hardness", ""))
    item["armor_bonus"] = _parse_int(fields.get("armorbonus", ""))
    item["max_dex_bonus"] = _parse_int(fields.get("maxdex", ""))

    # Float fields
    item["weight"] = _parse_float(fields.get("weight", ""))

    # String fields
    for key, field_name in [
        ("damage", "damage"),
        ("critical", "critical"),
        ("weapon_type", "weapontype"),
        ("proficiency", "proficiency"),
        ("handedness", "handedness"),
        ("material", "material"),
        ("binding", "bind"),
        ("base_value", "basevalue"),
        ("quest", "quest"),
        ("set_name", "set"),
        ("description", "description"),
    ]:
        raw = fields.get(field_name, "")
        item[key] = clean_wikitext(raw) if raw.strip() else None

    # List fields
    item["enchantments"] = _parse_list(fields.get("enchantments", ""))
    item["augment_slots"] = _parse_list(fields.get("augmentslot", ""))

    # Use the page name as fallback for item name
    if not item["name"]:
        item["name"] = clean_wikitext(fields.get("_positional_1", "")) or None

    return item


# ---------------------------------------------------------------------------
# Feat parser
# ---------------------------------------------------------------------------

# Boolean flag fields in the {{Feat}} template
_FEAT_FLAG_FIELDS = [
    "free", "passive", "active", "stance", "metamagic",
]

# Class bonus feat eligibility fields
_FEAT_BONUS_FEAT_CLASSES = [
    "alchemist", "artificer", "barbarian", "bard", "cleric",
    "dark hunter", "druid", "favored soul", "fighter", "monk",
    "paladin", "ranger", "rogue", "sorcerer", "stormsinger",
    "trickster", "warlock", "wizard",
]


def _parse_bool(value: str) -> bool:
    """Parse a wiki boolean field ('yes'/'no'/empty)."""
    return value.strip().lower() == "yes"


def parse_feat_wikitext(wikitext: str) -> dict[str, Any] | None:
    """Parse a DDO Wiki feat page's wikitext into a structured dict.

    Extracts data from the ``{{Feat|...}}`` template.
    Returns None if the template is not found.
    """
    fields = extract_template(wikitext, "Feat")
    if fields is None:
        return None

    feat: dict[str, Any] = {}

    # Name
    name = fields.get("name", "")
    feat["name"] = clean_wikitext(name) if name else None

    # Icon
    icon = fields.get("icon", "")
    feat["icon"] = icon.strip() or None

    # Description and notes
    for key, field_name in [
        ("description", "description"),
        ("note", "note"),
        ("prerequisite", "prerequisite"),
        ("cooldown", "cooldown"),
    ]:
        raw = fields.get(field_name, "")
        feat[key] = clean_wikitext(raw) if raw.strip() else None

    # Boolean flags
    for flag in _FEAT_FLAG_FIELDS:
        feat[flag] = _parse_bool(fields.get(flag, ""))

    # Epic destiny flag
    feat["epic_destiny"] = _parse_bool(fields.get("epic destiny", ""))

    # Class bonus feat eligibility
    bonus_set: set[str] = set()
    for cls in _FEAT_BONUS_FEAT_CLASSES:
        # Check both "fighter=yes" and "fighter bonus feat=yes"
        if _parse_bool(fields.get(cls, "")) or _parse_bool(
            fields.get(f"{cls} bonus feat", "")
        ):
            bonus_set.add(cls)
    # Monk sub-type feats (martial arts, dragon arts)
    if _parse_bool(fields.get("martial arts feat", "")):
        bonus_set.add("monk")
    if _parse_bool(fields.get("dragon arts feat", "")):
        bonus_set.add("monk")

    feat["bonus_classes"] = sorted(bonus_set)

    return feat
