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
    # Strip bold/italic markup (''' and '')
    text = text.replace("'''", "").replace("''", "")
    # Remove HTML comments (<!-- ... -->)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    # Replace HTML tags with space (preserves word boundaries around <br/> etc.)
    text = _HTML_TAG_RE.sub(" ", text)
    # Remove remaining template markers (simple ones)
    text = _TEMPLATE_RE.sub("", text)
    # Collapse whitespace
    text = " ".join(text.split())
    return text.strip()


_NOPIC_RE = re.compile(r"\{\{[Nn]opic\|([^|}]+)")


def _extract_icon(raw: str) -> str | None:
    """Extract icon filename from a wiki field, handling {{Nopic|file|...}}."""
    if not raw or not raw.strip():
        return None
    # Check for {{Nopic|filename|...}} wrapper (icon exists but not uploaded)
    m = _NOPIC_RE.search(raw)
    if m:
        return m.group(1).strip()
    # Normal: just clean the wikitext
    cleaned = clean_wikitext(raw)
    return cleaned if cleaned else None


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


def _parse_enchantment_list(value: str) -> list[str]:
    """Parse an enchantment list, preserving wiki template syntax.

    Unlike _parse_list, this does NOT strip ``{{...}}`` templates, because
    enchantment templates like ``{{Stat|STR|7}}`` encode the enchantment
    data itself.  Only wiki links and HTML tags are cleaned.
    """
    lines = value.split("\n")
    items: list[str] = []
    for line in lines:
        line = line.strip().lstrip("*").strip()
        if not line:
            continue
        # Clean links and HTML but keep templates
        text = _LINK_RE.sub(r"\1", line)
        text = _HTML_TAG_RE.sub(" ", text)
        text = " ".join(text.split()).strip()
        if text:
            items.append(text)
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
    # Field mappings: (output_key, [template_field_names...])
    # Multiple names support both old and current wiki template conventions.
    for key, field_names in [
        ("damage", ["damage"]),
        ("critical", ["crit", "critical"]),
        ("weapon_type", ["type", "weapontype"]),
        ("proficiency", ["prof", "proficiency"]),
        ("handedness", ["hand", "handedness"]),
        ("material", ["material"]),
        ("binding", ["bind"]),
        ("base_value", ["basevalue"]),
        ("quest", ["quest"]),
        ("set_name", ["set"]),
        ("description", ["description"]),
        ("slot", ["slot"]),
        ("damage_class", ["class"]),
        ("attack_mod", ["attackmod"]),
        ("damage_mod", ["damagemod"]),
        ("race_required", ["race"]),
    ]:
        raw = ""
        for fn in field_names:
            raw = fields.get(fn, "")
            if raw.strip():
                break
        item[key] = clean_wikitext(raw) if raw.strip() else None

    # Icon (separate: needs Nopic template handling)
    for fn in ("picdesc", "pic", "icon"):
        raw = fields.get(fn, "")
        if raw.strip():
            item["icon"] = _extract_icon(raw)
            break
    else:
        item["icon"] = None

    # List fields
    # Wiki template field is "enhancements"; our dict key is "enchantments" (DDO term).
    raw_enchantments = _parse_enchantment_list(fields.get("enhancements", ""))

    # Extract {{Augment|Color}} templates from enchantments into augment_slots.
    # DDO wiki embeds augment slots in the enhancements list, not a separate field.
    augment_slots: list[str] = []
    enchantments: list[str] = []
    for entry in raw_enchantments:
        m = re.search(r"\{\{[Aa]ugment\|(\w+)\}\}", entry)
        if m:
            augment_slots.append(m.group(1).lower())
        else:
            enchantments.append(entry)
    item["enchantments"] = enchantments

    # Also check the explicit augmentslot= field (older wiki format).
    explicit_slots = _parse_list(fields.get("augmentslot", ""))
    if explicit_slots:
        augment_slots.extend(explicit_slots)
    item["augment_slots"] = augment_slots

    # Use the page name as fallback for item name
    if not item["name"]:
        item["name"] = clean_wikitext(fields.get("_positional_1", "")) or None

    return item


# ---------------------------------------------------------------------------
# Augment parser
# ---------------------------------------------------------------------------

# Slot color normalization
_AUGMENT_COLORS: dict[str, str] = {
    "red": "red", "blue": "blue", "green": "green", "yellow": "yellow",
    "orange": "orange", "purple": "purple", "colorless": "colorless", "white": "white",
}


def parse_augment_wikitext(wikitext: str) -> dict[str, Any] | None:
    """Parse a DDO Wiki augment page's wikitext into a structured dict.

    Extracts data from the ``{{Item Augment|...}}`` template.
    Returns None if the template is not found.
    """
    fields = extract_template(wikitext, "Item Augment")
    if fields is None:
        return None

    augment: dict[str, Any] = {}

    # Name (required)
    name = fields.get("name", "")
    augment["name"] = clean_wikitext(name) if name else None

    # Slot color
    raw_color = fields.get("type", "").strip().lower()
    augment["slot_color"] = _AUGMENT_COLORS.get(raw_color, raw_color)

    # Minimum level
    augment["minimum_level"] = _parse_int(fields.get("minimum level", ""))

    # Icon
    augment["icon"] = _extract_icon(fields.get("icon", "")) or _extract_icon(fields.get("image", "")) or None

    # Enchantments (same format as items — wiki templates)
    augment["enchantments"] = _parse_enchantment_list(fields.get("enhancements", "")
                                                       or fields.get("enchantments", ""))

    # Description
    raw_desc = fields.get("description", "")
    augment["description"] = clean_wikitext(raw_desc) if raw_desc.strip() else None

    return augment


# ---------------------------------------------------------------------------
# Spell parser
# ---------------------------------------------------------------------------

# DDO class names as they appear in Infobox-spell template field keys
_SPELL_CLASS_FIELDS: dict[str, str] = {
    "sor n wiz": "Sorcerer",
    "bard": "Bard",
    "cleric": "Cleric",
    "paladin": "Paladin",
    "ranger": "Ranger",
    "druid": "Druid",
    "favored soul": "Favored Soul",
    "artificer": "Artificer",
    "warlock": "Warlock",
    "alchemist": "Alchemist",
    "wild mage": "Sorcerer",    # Wild Mage = Sorcerer variant
    "dark apostate": "Cleric",   # Dark Apostate = Cleric variant
    "stormsinger": "Bard",       # Stormsinger = Bard variant
    "sacred fist": "Paladin",    # Sacred Fist = Paladin variant
}

# Metamagic flag fields in the spell template
_SPELL_METAMAGIC_FIELDS = [
    "empower", "maximize", "quicken", "heighten", "enlarge",
    "eschew", "intensify", "embolden", "empower healing",
]


def parse_spell_wikitext(wikitext: str) -> dict[str, Any] | None:
    """Parse a DDO Wiki spell page's wikitext into a structured dict.

    Extracts data from the ``{{Infobox-spell|...}}`` template.
    Returns None if the template is not found.
    """
    fields = extract_template(wikitext, "Infobox-spell")
    if fields is None:
        return None

    spell: dict[str, Any] = {}

    # Name
    name = fields.get("name", "")
    spell["name"] = clean_wikitext(name) if name else None

    # School
    spell["school"] = clean_wikitext(fields.get("school", "")) or None

    # Spell level (the primary level shown in the infobox)
    level_str = fields.get("level", "").strip()
    spell["level"] = _parse_int(level_str) if level_str else None

    # Spell cost and cooldown
    cost_str = fields.get("cost", "").strip()
    spell["spell_points"] = _parse_int(cost_str) if cost_str else None
    spell["cooldown"] = clean_wikitext(fields.get("cooldown", "")) or None

    # Icon — handle {{Nopic|filename|icon}} wrapper for missing uploads
    spell["icon"] = _extract_icon(fields.get("icon", "")) or _extract_icon(fields.get("image", "")) or None

    # Description, components, range, target, duration, save, SR
    for key, field_name in [
        ("description", "description"),
        ("components", "components"),
        ("range", "range"),
        ("target", "target"),
        ("duration", "duration"),
        ("saving_throw", "save"),
        ("spell_resistance", "sr"),
    ]:
        raw = fields.get(field_name, "")
        spell[key] = clean_wikitext(raw) if raw.strip() else None

    # Damage types
    damage_types = []
    for i in range(1, 5):
        dt = fields.get(f"type{i}", "").strip()
        if dt:
            damage_types.append(dt)
    spell["damage_types"] = damage_types

    # Class spell levels: extract from class-specific fields
    class_levels: dict[str, int] = {}
    for field_key, class_name in _SPELL_CLASS_FIELDS.items():
        val = fields.get(field_key, "").strip()
        if val:
            level = _parse_int(val)
            if level is not None and class_name not in class_levels:
                class_levels[class_name] = level
    spell["class_levels"] = class_levels

    # Metamagic flags
    metamagics = []
    for meta_field in _SPELL_METAMAGIC_FIELDS:
        val = fields.get(meta_field, "").strip().lower()
        if val in ("y", "yes", "true", "1"):
            metamagics.append(meta_field.replace(" ", "_"))
    spell["metamagics"] = metamagics

    return spell


# ---------------------------------------------------------------------------
# Class page parser
# ---------------------------------------------------------------------------

_WIKI_TABLE_ROW_RE = re.compile(r"^\|\s*'''?(.+?)'''?\s*$", re.MULTILINE)
_ORDINAL_RE = re.compile(r"^(\d+)(?:st|nd|rd|th)$")


def parse_class_wikitext(wikitext: str, class_name: str) -> dict[str, Any] | None:
    """Parse a DDO Wiki class page into structured progression data.

    Returns a dict with:
        name, hit_die, levels (list of dicts with level/bab/fort/ref/will/feats/sp/spell_slots)
    """
    result: dict[str, Any] = {"name": class_name}

    # Hit die: look for "d4", "d6", "d8", "d10", "d12" near "Hit die/dice"
    hd_match = re.search(r"[Hh]it\s+[Dd]ic?e[^d]*?d(\d+)", wikitext[:2000])
    if not hd_match:
        # Handle wiki link: [[Hit dice]]
        hd_match = re.search(r"\[\[Hit dic?e\]\][^d]*?d(\d+)", wikitext[:2000], re.IGNORECASE)
    if not hd_match:
        hd_match = re.search(r"d(\d+)\s+(?:per|hit)", wikitext[:2000], re.IGNORECASE)
    if not hd_match:
        hd_match = re.search(r"'''d(\d+)'''", wikitext[:2000])
    if hd_match:
        result["hit_die"] = int(hd_match.group(1))

    # Determine if spell columns are "Spells Known" (spontaneous) or "Preparable"
    result["spells_known_type"] = (
        "known" if re.search(r"Spells Known", wikitext) else "preparable"
    )

    # Try template-based advancement table first (Wizard style)
    template_rows = extract_all_templates(wikitext, "Class advancement table")
    if template_rows:
        result["levels"] = _parse_template_advancement(template_rows)
        return result

    # Fall back to wiki table parsing
    wiki_levels = _parse_wiki_table_advancement(wikitext)
    if wiki_levels:
        result["levels"] = wiki_levels

    return result


def _parse_template_advancement(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Parse {{Class advancement table}} template rows."""
    levels = []
    for row in rows:
        level_str = row.get("level", "")
        if not level_str.strip():
            continue
        level = _parse_int(level_str)
        if level is None or level < 1:
            continue

        entry: dict[str, Any] = {"level": level}

        # Saves (0 = poor, 1 = good)
        for save in ("fort", "ref", "will"):
            val = row.get(save, "").strip()
            if val in ("0", "1"):
                entry[save] = val

        # SP
        sp = row.get("sp", "").strip().replace(",", "")
        if sp:
            entry["sp"] = _parse_int(sp)

        # Feats
        feats_raw = row.get("feats", "").strip()
        if feats_raw and feats_raw != "-":
            entry["feats"] = [
                clean_wikitext(f).strip()
                for f in feats_raw.split(",")
                if clean_wikitext(f).strip() and clean_wikitext(f).strip() != "-"
            ]

        # Spell slots (level 1 through level 9)
        spell_slots = {}
        for i in range(1, 10):
            val = row.get(f"level {i}", "").strip()
            if val:
                parsed = _parse_int(val)
                if parsed is not None:
                    spell_slots[i] = parsed
        if spell_slots:
            entry["spell_slots"] = spell_slots

        levels.append(entry)
    return levels


def _parse_wiki_table_advancement(wikitext: str) -> list[dict[str, Any]]:
    """Parse advancement data from a wiki table (Fighter/Bard/Sorcerer style).

    Uses the header row to determine column semantics rather than relying
    on fixed positional indices.  Handles both ``|`` and ``!`` cell markers
    as well as inline ``||`` / ``!!`` separators.
    """
    # Find the advancement table (contains "Base Attack Bonus" header)
    tables = list(re.finditer(r'\{\|.*?\|\}', wikitext, re.DOTALL))
    adv_table = None
    for m in tables:
        if "Base Attack Bonus" in m.group() or "BAB" in m.group():
            adv_table = m.group()
            break
    if not adv_table:
        return []

    rows = re.split(r'\|-', adv_table)

    # --- Identify the header row and build column mapping ---
    header_idx: dict[str, int] = {}
    spell_slot_cols: dict[int, int] = {}  # col_index -> spell level
    header_found = False

    for row in rows:
        cells = _extract_wiki_cells(row)
        # The header row contains "Level" and "Base Attack Bonus" (or "BAB")
        cell_lower = [c.lower().strip() for c in cells]
        if not any("level" == cl for cl in cell_lower):
            continue
        if not any("base attack" in cl or "bab" in cl for cl in cell_lower):
            continue
        header_found = True
        for i, raw in enumerate(cells):
            # Strip wiki style attrs like "width=100|..." before matching
            cl = re.sub(r'^[^|]*\|', '', raw).lower().strip()
            if cl == "level":
                header_idx["level"] = i
            elif "base attack" in cl or cl == "bab":
                header_idx["bab"] = i
            elif "fort" in cl:
                header_idx["fort"] = i
            elif "ref" in cl:
                header_idx["ref"] = i
            elif "will" in cl:
                header_idx["will"] = i
            elif "special" in cl or "auto-granted" in cl or "granted feat" in cl:
                header_idx["special"] = i
            elif "spell point" in cl or cl == "sp":
                header_idx["sp"] = i
            else:
                # Check for spell level headers like "1st", "2nd", ... "9th"
                sl_match = re.search(r'(\d+)(?:st|nd|rd|th)', cl)
                if sl_match:
                    spell_slot_cols[i] = int(sl_match.group(1))
        break

    if not header_found:
        return []

    # --- Parse data rows using the column map ---
    levels = []
    for row in rows:
        cells = _extract_wiki_cells(row)
        if len(cells) < 5:
            continue

        # Level
        li = header_idx.get("level", 0)
        if li >= len(cells):
            continue
        level_text = cells[li].strip()
        m = _ORDINAL_RE.match(level_text)
        if not m:
            continue
        level = int(m.group(1))
        entry: dict[str, Any] = {"level": level}

        # BAB
        bi = header_idx.get("bab")
        if bi is not None and bi < len(cells):
            bab_match = re.search(r'\+?(\d+)', cells[bi])
            if bab_match:
                entry["bab"] = int(bab_match.group(1))

        # Saves
        for save in ("fort", "ref", "will"):
            si = header_idx.get(save)
            if si is not None and si < len(cells):
                save_match = re.search(r'\+?(\d+)', cells[si])
                if save_match:
                    entry[save] = save_match.group(0)

        # Special / feats
        fi = header_idx.get("special")
        if fi is not None and fi < len(cells):
            feats_raw = cells[fi]
            if feats_raw and feats_raw != "-":
                entry["feats"] = [
                    f.strip() for f in re.split(r',\s*', feats_raw)
                    if f.strip() and f.strip() != "-"
                ]

        # SP
        spi = header_idx.get("sp")
        if spi is not None and spi < len(cells):
            sp_val = _parse_int(cells[spi].replace(",", ""))
            if sp_val is not None:
                entry["sp"] = sp_val

        # Spell slots (keyed by header-identified spell level)
        # Handle "N+M" format (base + bonus slots) by summing
        spell_slots = {}
        for col_idx, spell_level in spell_slot_cols.items():
            if col_idx < len(cells):
                cell_text = cells[col_idx].strip()
                # Handle "2+2" format: sum the parts
                parts = cell_text.split("+")
                total = 0
                valid = False
                for part in parts:
                    p = _parse_int(part.strip())
                    if p is not None:
                        total += p
                        valid = True
                if valid and total > 0:
                    spell_slots[spell_level] = total
        if spell_slots:
            entry["spell_slots"] = spell_slots

        levels.append(entry)
    return levels


def _extract_wiki_cells(row_text: str) -> list[str]:
    """Extract cells from a wiki table row, handling | and ! markers."""
    cells = []
    for line in row_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Skip structural lines
        if line.startswith("{|") or line.startswith("|}"):
            continue
        # Handle header cells (!) and data cells (|)
        if line.startswith("|") or line.startswith("!"):
            # Determine separator
            sep = "||" if "||" in line else ("!!" if "!!" in line else None)
            if sep:
                parts = line.split(sep)
                for part in parts:
                    part = part.strip().lstrip("|!").strip()
                    if part.startswith("colspan") or part.startswith("style") or part.startswith("class="):
                        continue
                    cells.append(clean_wikitext(part))
            else:
                cell = line.lstrip("|!").strip()
                if cell.startswith("colspan") or cell.startswith("style") or cell.startswith("class="):
                    continue
                cells.append(clean_wikitext(cell))
    return cells


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
    """Parse a wiki boolean field ('yes'/'no'/empty).

    Handles HTML comments after the value (e.g., ``yes\\n<!--class-->``).
    """
    cleaned = re.sub(r"<!--.*?-->", "", value).strip().lower()
    return cleaned == "yes"


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


# ---------------------------------------------------------------------------
# Enhancement parser
# ---------------------------------------------------------------------------

_TIER_HEADER_RE = re.compile(
    r"^=+\s*(Core abilities|Tier\s+(One|Two|Three|Four|Five))\s*=+",
    re.MULTILINE | re.IGNORECASE,
)

_TIER_WORD_MAP = {
    "one": "1", "two": "2", "three": "3",
    "four": "4", "five": "5",
}

# Template names used for enhancement/destiny entries on DDO Wiki.
# Longer name first: "itemwlvl" must be checked before "item" since
# "item" is a prefix match that would also capture "itemwlvl" entries.
_ENHANCEMENT_TEMPLATES = [
    "Enhancement table/itemwlvl",
    "Enhancement table/item",
    "Epic destiny table/itemwlvl",
    "Epic destiny table/item",
]

def _detect_tier_sections(wikitext: str) -> list[tuple[int, str]]:
    """Find tier section boundaries in enhancement tree wikitext.

    Returns a list of ``(char_offset, tier_label)`` pairs, sorted by offset.
    Tier labels are ``"core"``, ``"1"`` through ``"5"``.
    """
    sections: list[tuple[int, str]] = []
    for match in _TIER_HEADER_RE.finditer(wikitext):
        header_text = match.group(1).strip().lower()
        if header_text == "core abilities":
            sections.append((match.start(), "core"))
        else:
            # "Tier One" -> extract the word after "Tier "
            tier_word = match.group(2)
            if tier_word:
                label = _TIER_WORD_MAP.get(tier_word.lower())
                if label:
                    sections.append((match.start(), label))
    return sections


def parse_enhancement_fields(fields: dict[str, str]) -> dict[str, Any]:
    """Parse extracted template fields into an enhancement dict."""
    name = fields.get("name", "")
    description = fields.get("description", "")
    prereq = fields.get("prereq", "")
    level_raw = fields.get("level", "").strip()

    return {
        "name": clean_wikitext(name) if name.strip() else None,
        "icon": fields.get("image", "").strip() or None,
        "description": clean_wikitext(description) if description.strip() else None,
        "ranks": _parse_int(fields.get("ranks", "")) or 1,
        "ap_cost": _parse_int(fields.get("ap", "")) or 1,
        "progression": _parse_int(fields.get("pg", "")) or 0,
        "level": clean_wikitext(level_raw) if level_raw else None,
        "prerequisite": clean_wikitext(prereq) if prereq.strip() else None,
    }


def parse_enhancement_tree_wikitext(
    wikitext: str, page_title: str,
) -> dict[str, Any] | None:
    """Parse an enhancement tree wiki page into a structured tree dict.

    Each tree page contains multiple ``{{Enhancement table/item|...}}``
    templates organized under tier section headers. Returns None if no
    enhancement templates are found.
    """
    # Collect all enhancement templates with their character positions.
    # Templates are checked longest-name-first to avoid prefix collisions
    # ("item" is a prefix of "itemwlvl"). Dedup by position ensures each
    # template instance is only parsed once, by the most specific match.
    positioned: list[tuple[int, dict[str, str]]] = []
    seen_positions: set[int] = set()
    for tmpl_name in _ENHANCEMENT_TEMPLATES:
        remaining = wikitext
        offset = 0
        while True:
            fields = extract_template(remaining, tmpl_name)
            if fields is None:
                break
            lower = remaining.lower()
            marker = "{{" + tmpl_name.lower()
            start = lower.find(marker)
            if start == -1:
                break
            abs_pos = offset + start
            if abs_pos not in seen_positions:
                seen_positions.add(abs_pos)
                positioned.append((abs_pos, fields))
            remaining = remaining[start + len(marker):]
            offset += start + len(marker)

    if not positioned:
        return None

    positioned.sort(key=lambda x: x[0])

    # Detect tier sections
    sections = _detect_tier_sections(wikitext)

    # Assign tier to each enhancement based on its position
    enhancements: list[dict[str, Any]] = []
    for pos, fields in positioned:
        tier = "unknown"
        # Find the last section header before this template
        for sec_offset, sec_label in reversed(sections):
            if sec_offset <= pos:
                tier = sec_label
                break
        enh = parse_enhancement_fields(fields)
        enh["tier"] = tier
        enhancements.append(enh)

    # Derive tree name from page title
    tree_name = page_title
    if tree_name.lower().endswith(" enhancements"):
        tree_name = tree_name[: -len(" enhancements")]
    tree_name = tree_name.replace("_", " ")

    return {
        "name": tree_name,
        "enhancements": enhancements,
    }


def parse_tree_index_wikitext(
    wikitext: str,
) -> list[dict[str, str]]:
    """Parse an enhancement index page to extract tree page references.

    Handles two formats found on DDO Wiki:

    **Class/Racial index** -- parent header + tree links::

        * '''[[Fighter]]'''
        ** Enhancements: [[Kensei enhancements|Kensei]], ...

    **Universal index** -- bare bold links (redirect to ``X enhancements``)::

        * '''[[Falconry]]'''

    Returns a list of dicts with ``page_title``, ``display_name``, and
    ``parent`` keys. Skips anchor links (Reaper subtrees) and non-content
    links (File:, Category:).
    """
    results: list[dict[str, str]] = []
    current_parent = ""

    for line in wikitext.split("\n"):
        stripped = line.strip()

        # Detect parent headers: * '''[[ClassName]]'''
        # These are bold wiki links that don't contain "enhancements"
        parent_match = re.match(
            r"^\*\s*'{2,3}\[\[([^\]|#]+)\]\]'{2,3}\s*$", stripped,
        )
        if parent_match:
            name = parent_match.group(1).strip()
            if "enhancements" not in name.lower():
                current_parent = name
                continue

        # Find piped enhancement tree links: [[Page|Display]]
        for match in re.finditer(
            r"\[\[([^\]#|]+)\|([^\]]+)\]\]", stripped,
        ):
            page_title = match.group(1).strip()
            display_name = match.group(2).strip()

            # Skip non-content links
            if page_title.startswith(("File:", "Category:")):
                continue

            results.append({
                "page_title": page_title,
                "display_name": display_name,
                "parent": current_parent,
            })

    return results


def parse_universal_tree_index(wikitext: str) -> list[dict[str, str]]:
    """Parse the Universal enhancements index page.

    Universal trees use bare bold links ``'''[[TreeName]]'''`` that
    redirect to ``TreeName enhancements`` pages. Returns tree refs
    with ``page_title`` set to the redirect target (appending
    `` enhancements`` suffix).
    """
    results: list[dict[str, str]] = []
    for match in re.finditer(
        r"'{2,3}\[\[([^\]|#]+)\]\]'{2,3}", wikitext,
    ):
        name = match.group(1).strip()
        if name.startswith(("File:", "Category:")):
            continue
        # Universal tree pages redirect to "Name enhancements"
        results.append({
            "page_title": f"{name} enhancements",
            "display_name": name,
            "parent": "",
        })
    return results
