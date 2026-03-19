"""Effect entry census and wiki-correlation mapper for DDO item bonuses.

Scans all 0x70XXXXXX effect entries to build histograms of stat_def_id
and bonus_type_code values, then correlates with wiki enchantment strings
to discover stat and bonus type mappings.

The census provides the data landscape; the mapper uses wiki enchantment
strings (e.g., "+7 Enhancement bonus to Strength") as a Rosetta Stone to
link binary stat_def_id/bonus_type_code values to known stat and bonus
type names from the db/schema.py seed tables.
"""

from __future__ import annotations

import html
import logging
import re
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .archive import DatArchive, FileEntry
from .extract import read_entry_data

logger = logging.getLogger(__name__)

# Bonus type spelling variants found in wiki enchantment strings.
# Maps wiki wording -> canonical name matching the bonus_types seed table.
_BONUS_TYPE_ALIASES: dict[str, str] = {
    "Insightful": "Insight",
}

# Regex for parsing standard enchantment strings like:
#   "+7 Enhancement bonus to Strength"
#   "+6 Insightful bonus to Magical Resistance Rating"
#   "+4 Quality bonus to Fire Spell Power"
_ENCHANTMENT_RE = re.compile(
    r"\+(\d+)\s+"             # magnitude
    r"(\S+)\s+"               # bonus type word
    r"bonus\s+to\s+"          # literal "bonus to"
    r"(.+)",                  # stat name (greedy, to capture multi-word)
    re.IGNORECASE,
)

# Regex for wiki {{Stat|...}} template:
#   {{Stat|STR|7}}           → +7 Enhancement bonus to Strength
#   {{Stat|INT|6|Insightful}} → +6 Insight bonus to Intelligence
#   {{Stat|CON|13}}          → +13 Enhancement bonus to Constitution
#   {{Stat|Well Rounded|2|Profane}} → +2 Profane bonus to Well Rounded
_STAT_TEMPLATE_RE = re.compile(
    r"\{\{Stat\|"             # template start
    r"([^|}]+)\|"             # stat name or abbreviation
    r"(\d+)"                  # magnitude
    r"(?:\|([^|}]+))?"        # optional bonus type
    r"\}\}",                  # template end
    re.IGNORECASE,
)

# Stat abbreviations used in DDO wiki {{Stat}} templates.
_STAT_ABBREVS: dict[str, str] = {
    "STR": "Strength",
    "DEX": "Dexterity",
    "CON": "Constitution",
    "INT": "Intelligence",
    "WIS": "Wisdom",
    "CHA": "Charisma",
}

# Regex for wiki {{Sheltering|...}} template:
#   {{Sheltering|33|Enhancement|Physical}}  → +33 Enhancement Physical Sheltering
#   {{Sheltering|26|Insightful|Magical}}    → +26 Insight Magical Sheltering
_SHELTERING_TEMPLATE_RE = re.compile(
    r"\{\{Sheltering\|"
    r"(\d+)\|"                # magnitude
    r"([^|}]+)\|"             # bonus type
    r"([^|}]+)"               # physical or magical
    r"\}\}",
    re.IGNORECASE,
)

# Regex for wiki {{SpellPower|...}} template:
#   {{SpellPower|Devotion|30}} → +30 Devotion (Universal Spell Power variant)
_SPELLPOWER_TEMPLATE_RE = re.compile(
    r"\{\{SpellPower\|"
    r"([^|}]+)\|"             # spell power name (Devotion, Impulse, etc.)
    r"(\d+)"                  # magnitude
    r"(?:\|([^|}]+))?"        # optional bonus type
    r"\}\}",
    re.IGNORECASE,
)

# Regex for wiki {{Seeker|...}} template:
#   {{Seeker|3}}     → +3 Enhancement Seeker
#   {{Seeker|4|Insightful}} → +4 Insightful Seeker
_SEEKER_TEMPLATE_RE = re.compile(
    r"\{\{Seeker\|"
    r"(\d+)"                  # magnitude
    r"(?:\|([^|}]+))?"        # optional bonus type
    r"\}\}",
    re.IGNORECASE,
)

# Regex for wiki {{Deadly|...}} template:
#   {{Deadly|4|Insightful}} → +4 Insightful Deadly
_DEADLY_TEMPLATE_RE = re.compile(
    r"\{\{Deadly\|"
    r"(\d+)"                  # magnitude
    r"(?:\|([^|}]+))?"        # optional bonus type
    r"\}\}",
    re.IGNORECASE,
)

# Regex for wiki {{Fortification|...}} template:
#   {{Fortification|100}} → +100 Fortification
_FORTIFICATION_TEMPLATE_RE = re.compile(
    r"\{\{Fortification\|"
    r"(\d+)"                  # magnitude
    r"(?:\|([^|}]+))?"        # optional bonus type
    r"\}\}",
    re.IGNORECASE,
)

# Regex for wiki {{Save|...}} template:
#   {{Save|r|11}} → +11 Reflex Save
_SAVE_TEMPLATE_RE = re.compile(
    r"\{\{Save\|"
    r"([^|}]+)\|"             # save type abbreviation
    r"(\d+)"                  # magnitude
    r"(?:\|([^|}]+))?"        # optional bonus type
    r"\}\}",
    re.IGNORECASE,
)

# Save abbreviations
_SAVE_ABBREVS: dict[str, str] = {
    "f": "Fortitude Save",
    "r": "Reflex Save",
    "w": "Will Save",
}

# Stat names from {{Stat}} templates that are valid for type-17 correlation.
# These are ability scores and well-known stats — not combat effects like
# Seeker, Deadly, or Sheltering which map to different binary structures.
_STAT_NAMES_FOR_TYPE17: frozenset[str] = frozenset({
    "Strength", "Dexterity", "Constitution", "Intelligence", "Wisdom", "Charisma",
    "Well Rounded",
})

# Skill abbreviations used in {{Skills}} templates
_SKILL_ABBREVS: dict[str, str] = {
    "intim": "Intimidate",
    "haggle": "Haggle",
    "concentration": "Concentration",
    "spellcraft": "Spellcraft",
    "spot": "Spot",
    "listen": "Listen",
    "search": "Search",
    "hide": "Hide",
    "move silently": "Move Silently",
    "balance": "Balance",
    "tumble": "Tumble",
    "jump": "Jump",
    "swim": "Swim",
    "heal": "Heal",
    "repair": "Repair",
    "diplomacy": "Diplomacy",
    "bluff": "Bluff",
    "disable device": "Disable Device",
    "open lock": "Open Lock",
    "perform": "Perform",
    "umd": "Use Magic Device",
    "use magic device": "Use Magic Device",
    "command": "Intimidate",  # Command = Intimidate variant
}

# Simple numeric-value templates: {{Name|value}} or {{Name|value|bonus_type}}
# Parsed into stat=Name, value=N, bonus_type=Enhancement or specified.
_SIMPLE_NUMERIC_RE = re.compile(
    r"\{\{"
    r"(Accuracy|Deception|Speed|Resistance|Wizardry|Sheltering MRR"
    r"|Dodge|Doublestrike|Doubleshot|Concealment)"
    r"\|(\d+)"
    r"(?:\|([^|}]+))?"
    r"\}\}",
    re.IGNORECASE,
)

# {{Skills|name|value}} or {{Skills|name|value|bonus_type}}
_SKILLS_TEMPLATE_RE = re.compile(
    r"\{\{Skills\|"
    r"([^|}]+)\|"             # skill name or abbreviation
    r"(\d+)"                  # value
    r"(?:\|([^|}]+))?"        # optional bonus type
    r"(?:\|[^}]*)?"           # optional extra params (prefix= etc)
    r"\}\}",
    re.IGNORECASE,
)

# {{Elemental Resistance|Element|value}}
_ELEMENTAL_RESIST_RE = re.compile(
    r"\{\{Elemental Resistance\|"
    r"([^|}]+)\|"             # element name
    r"(\d+)"                  # value
    r"\}\}",
    re.IGNORECASE,
)

# {{Absorption|Element|value}}
_ABSORPTION_RE = re.compile(
    r"\{\{Absorption\|"
    r"([^|}]+)\|"             # element name
    r"(\d+)"                  # value
    r"\}\}",
    re.IGNORECASE,
)

# {{Spell Focus|School|N}} or {{Spell Focus|Spell Focus Mastery|II|Sacred}}
_SPELL_FOCUS_RE = re.compile(
    r"\{\{Spell Focus\|"
    r"([^|}]+)\|"             # school or "Spell Focus Mastery" / "Spell"
    r"(\d+)"                  # numeric value
    r"(?:\|([^|}]+))?"        # optional bonus type
    r"(?:\|[^}]*)?"           # optional extra params
    r"\}\}",
    re.IGNORECASE,
)

# {{Hp|type|value}} where type is "Vitality", "False Life", etc.
_HP_TEMPLATE_RE = re.compile(
    r"\{\{Hp\|"
    r"[^|}]+\|"              # hp type name (Vitality, False Life, etc.)
    r"(\d+)"                 # value
    r"(?:\|([^|}]+))?"       # optional extra
    r"\}\}",
    re.IGNORECASE,
)

# {{HealingAmp|value|type|bonus_type}}
_HEALINGAMP_RE = re.compile(
    r"\{\{HealingAmp\|"
    r"(\d+)"                  # value
    r"(?:\|([^|}]+))?"        # type (h=healing, R=repair, etc.)
    r"(?:\|([^|}]+))?"        # optional bonus type
    r"\}\}",
    re.IGNORECASE,
)

# Spell power display names → stat table names
_SPELLPOWER_STATS: dict[str, str] = {
    "Devotion": "Positive Spell Power",
    "Impulse": "Force Spell Power",
    "Combustion": "Fire Spell Power",
    "Glaciation": "Cold Spell Power",
    "Magnetism": "Electric Spell Power",
    "Corrosion": "Acid Spell Power",
    "Resonance": "Sonic Spell Power",
    "Radiance": "Light Spell Power",
    "Nullification": "Negative Spell Power",
    "Reconstruction": "Repair Spell Power",
    "Potency": "Universal Spell Power",
    "Devotion,Heal": "Positive Spell Power",  # alternate form
}


# ---------------------------------------------------------------------------
# Effect Census
# ---------------------------------------------------------------------------


@dataclass
class EffectCensusResult:
    """Aggregated statistics from scanning 0x70XXXXXX effect entries."""

    total_effects: int = 0
    by_entry_type: dict[int, int] = field(default_factory=dict)
    type53_stat_histogram: dict[int, int] = field(default_factory=dict)
    type53_bonus_type_histogram: dict[int, int] = field(default_factory=dict)
    type53_magnitude_range: dict[int, tuple[int, int]] = field(default_factory=dict)
    type17_stat_histogram: dict[int, int] = field(default_factory=dict)
    type17_bonus_type_histogram: dict[int, int] = field(default_factory=dict)
    errors: int = 0


def build_effect_census(
    archive: DatArchive,
    entries: dict[int, FileEntry],
) -> EffectCensusResult:
    """Scan all 0x70XXXXXX entries and build stat/bonus histograms.

    Args:
        archive: Open DatArchive (client_gamelogic.dat).
        entries: File table entries (from traverse_btree or scan_file_table).

    Returns:
        EffectCensusResult with per-entry_type histograms.
    """
    result = EffectCensusResult()

    for file_id, entry in entries.items():
        if (file_id >> 24) & 0xFF != 0x70:
            continue

        result.total_effects += 1

        try:
            data = read_entry_data(archive, entry)
        except (ValueError, OSError):
            result.errors += 1
            continue

        if len(data) < 20:
            result.errors += 1
            continue

        entry_type = struct.unpack_from("<I", data, 5)[0]
        result.by_entry_type[entry_type] = result.by_entry_type.get(entry_type, 0) + 1

        bonus_type_code = struct.unpack_from("<H", data, 13)[0]
        stat_def_id = struct.unpack_from("<H", data, 16)[0]

        if entry_type == 0x35:  # 53 — primary bonus with magnitude
            if len(data) < 72:
                continue
            magnitude = struct.unpack_from("<I", data, 68)[0]

            result.type53_stat_histogram[stat_def_id] = (
                result.type53_stat_histogram.get(stat_def_id, 0) + 1
            )
            result.type53_bonus_type_histogram[bonus_type_code] = (
                result.type53_bonus_type_histogram.get(bonus_type_code, 0) + 1
            )

            # Track magnitude range per stat_def_id
            prev = result.type53_magnitude_range.get(stat_def_id)
            if prev is None:
                result.type53_magnitude_range[stat_def_id] = (magnitude, magnitude)
            else:
                result.type53_magnitude_range[stat_def_id] = (
                    min(prev[0], magnitude),
                    max(prev[1], magnitude),
                )

        elif entry_type == 0x11:  # 17 — no magnitude, implicit 1
            if len(data) < 28:
                continue
            result.type17_stat_histogram[stat_def_id] = (
                result.type17_stat_histogram.get(stat_def_id, 0) + 1
            )
            result.type17_bonus_type_histogram[bonus_type_code] = (
                result.type17_bonus_type_histogram.get(bonus_type_code, 0) + 1
            )

    return result


def format_effect_census(result: EffectCensusResult) -> str:
    """Format an EffectCensusResult as a human-readable report."""
    lines: list[str] = []

    lines.append("Effect Entry Census (0x70XXXXXX)")
    lines.append("=" * 32)
    lines.append(f"Total effects: {result.total_effects:,}  (errors: {result.errors})")
    lines.append("")

    # Entry type breakdown
    lines.append("Entry types:")
    for et in sorted(result.by_entry_type, key=lambda k: result.by_entry_type[k], reverse=True):
        count = result.by_entry_type[et]
        pct = 100 * count / max(result.total_effects, 1)
        lines.append(f"  type={et:<4d} (0x{et:02X})  {count:>8,}  ({pct:5.1f}%)")
    lines.append("")

    # Type-53 stat_def_id histogram
    lines.append(f"entry_type=53 stat_def_ids ({len(result.type53_stat_histogram)} unique):")
    lines.append(f"  {'stat_def_id':>12s}  {'Count':>6s}  {'Magnitude':>12s}")
    lines.append(f"  {'-' * 12}  {'-' * 6}  {'-' * 12}")
    for sid in sorted(
        result.type53_stat_histogram,
        key=lambda k: result.type53_stat_histogram[k],
        reverse=True,
    )[:50]:
        count = result.type53_stat_histogram[sid]
        mag_range = result.type53_magnitude_range.get(sid, (0, 0))
        lines.append(f"  {sid:>12d}  {count:>6,}  {mag_range[0]:>5d}-{mag_range[1]:<5d}")
    if len(result.type53_stat_histogram) > 50:
        lines.append(f"  ... and {len(result.type53_stat_histogram) - 50} more")
    lines.append("")

    # Type-53 bonus_type_code histogram
    lines.append(f"entry_type=53 bonus_type_codes ({len(result.type53_bonus_type_histogram)} unique):")
    for btc in sorted(
        result.type53_bonus_type_histogram,
        key=lambda k: result.type53_bonus_type_histogram[k],
        reverse=True,
    ):
        count = result.type53_bonus_type_histogram[btc]
        lines.append(f"  0x{btc:04X}  {count:>8,}")
    lines.append("")

    # Type-17 stat_def_id histogram (for reference)
    lines.append(f"entry_type=17 stat_def_ids ({len(result.type17_stat_histogram)} unique):")
    for sid in sorted(
        result.type17_stat_histogram,
        key=lambda k: result.type17_stat_histogram[k],
        reverse=True,
    )[:20]:
        count = result.type17_stat_histogram[sid]
        lines.append(f"  {sid:>12d}  {count:>6,}")
    if len(result.type17_stat_histogram) > 20:
        lines.append(f"  ... and {len(result.type17_stat_histogram) - 20} more")

    return "\n".join(lines)


def format_effect_census_json(result: EffectCensusResult) -> dict:
    """Format an EffectCensusResult as a JSON-serializable dict."""
    return {
        "summary": {
            "total_effects": result.total_effects,
            "errors": result.errors,
        },
        "by_entry_type": {
            str(et): count
            for et, count in sorted(result.by_entry_type.items(), key=lambda kv: -kv[1])
        },
        "type53_stat_histogram": {
            str(sid): {
                "count": count,
                "magnitude_min": result.type53_magnitude_range.get(sid, (0, 0))[0],
                "magnitude_max": result.type53_magnitude_range.get(sid, (0, 0))[1],
            }
            for sid, count in sorted(
                result.type53_stat_histogram.items(), key=lambda kv: -kv[1]
            )
        },
        "type53_bonus_type_histogram": {
            f"0x{btc:04X}": count
            for btc, count in sorted(
                result.type53_bonus_type_histogram.items(), key=lambda kv: -kv[1]
            )
        },
        "type17_stat_histogram": {
            str(sid): count
            for sid, count in sorted(
                result.type17_stat_histogram.items(), key=lambda kv: -kv[1]
            )
        },
        "type17_bonus_type_histogram": {
            f"0x{btc:04X}": count
            for btc, count in sorted(
                result.type17_bonus_type_histogram.items(), key=lambda kv: -kv[1]
            )
        },
    }


# ---------------------------------------------------------------------------
# Enchantment string parser
# ---------------------------------------------------------------------------


def parse_enchantment_string(text: str) -> dict | None:
    """Parse a wiki enchantment string into stat/bonus_type/value components.

    Handles two formats:

    1. Plain text: "+7 Enhancement bonus to Strength"
    2. Wiki templates:
       - ``{{Stat|STR|7}}`` → +7 Enhancement bonus to Strength
       - ``{{Stat|INT|6|Insightful}}`` → +6 Insight bonus to Intelligence
       - ``{{Sheltering|33|Enhancement|Physical}}`` → Physical Sheltering +33
       - ``{{SpellPower|Devotion|30}}`` → Positive Spell Power +30
       - ``{{Seeker|3}}`` → Seeker +3
       - ``{{Deadly|4|Insightful}}`` → Deadly +4 Insightful
       - ``{{Fortification|100}}`` → Fortification +100
       - ``{{Save|r|11}}`` → Reflex Save +11

    Returns a dict with keys: value (int), bonus_type (str), stat (str).
    Returns None if the string doesn't match any known pattern.
    """
    text = text.strip()

    # Try wiki {{Stat}} template first (most common for stat bonuses)
    match = _STAT_TEMPLATE_RE.search(text)
    if match:
        raw_stat = match.group(1).strip()
        value = int(match.group(2))
        raw_bonus_type = (match.group(3) or "Enhancement").strip()
        stat = _STAT_ABBREVS.get(raw_stat.upper(), raw_stat)
        bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
        return {"value": value, "bonus_type": bonus_type, "stat": stat}

    # {{Sheltering|33|Enhancement|Physical}}
    match = _SHELTERING_TEMPLATE_RE.search(text)
    if match:
        value = int(match.group(1))
        raw_bonus_type = match.group(2).strip()
        sheltering_type = match.group(3).strip()
        bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
        stat = f"{sheltering_type} Sheltering"
        return {"value": value, "bonus_type": bonus_type, "stat": stat}

    # {{SpellPower|Devotion|30}}
    match = _SPELLPOWER_TEMPLATE_RE.search(text)
    if match:
        sp_name = match.group(1).strip()
        value = int(match.group(2))
        raw_bonus_type = (match.group(3) or "Enhancement").strip()
        bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
        stat = _SPELLPOWER_STATS.get(sp_name, f"{sp_name} Spell Power")
        return {"value": value, "bonus_type": bonus_type, "stat": stat}

    # {{Seeker|3}} or {{Seeker|4|Insightful}}
    match = _SEEKER_TEMPLATE_RE.search(text)
    if match:
        value = int(match.group(1))
        raw_bonus_type = (match.group(2) or "Enhancement").strip()
        bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
        return {"value": value, "bonus_type": bonus_type, "stat": "Seeker"}

    # {{Deadly|4|Insightful}}
    match = _DEADLY_TEMPLATE_RE.search(text)
    if match:
        value = int(match.group(1))
        raw_bonus_type = (match.group(2) or "Enhancement").strip()
        bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
        return {"value": value, "bonus_type": bonus_type, "stat": "Deadly"}

    # {{Fortification|100}}
    match = _FORTIFICATION_TEMPLATE_RE.search(text)
    if match:
        value = int(match.group(1))
        raw_bonus_type = (match.group(2) or "Enhancement").strip()
        bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
        return {"value": value, "bonus_type": bonus_type, "stat": "Fortification"}

    # {{Save|r|11}}
    match = _SAVE_TEMPLATE_RE.search(text)
    if match:
        save_abbr = match.group(1).strip().lower()
        value = int(match.group(2))
        raw_bonus_type = (match.group(3) or "Resistance").strip()
        bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
        stat = _SAVE_ABBREVS.get(save_abbr, f"{save_abbr} Save")
        return {"value": value, "bonus_type": bonus_type, "stat": stat}

    # {{Skills|intim|3}} or {{Skills|Command|5|Insight}}
    match = _SKILLS_TEMPLATE_RE.search(text)
    if match:
        raw_skill = match.group(1).strip()
        value = int(match.group(2))
        raw_bonus_type = (match.group(3) or "Enhancement").strip()
        bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
        stat = _SKILL_ABBREVS.get(raw_skill.lower(), raw_skill)
        return {"value": value, "bonus_type": bonus_type, "stat": stat}

    # Simple numeric templates: {{Accuracy|7}}, {{Deception|3}}, {{Speed|30}}, etc.
    match = _SIMPLE_NUMERIC_RE.search(text)
    if match:
        stat = match.group(1).strip()
        value = int(match.group(2))
        raw_bonus_type = (match.group(3) or "Enhancement").strip()
        bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
        return {"value": value, "bonus_type": bonus_type, "stat": stat}

    # {{Elemental Resistance|Acid|30}}
    match = _ELEMENTAL_RESIST_RE.search(text)
    if match:
        element = match.group(1).strip()
        value = int(match.group(2))
        return {"value": value, "bonus_type": "Enhancement", "stat": f"{element} Resistance"}

    # {{Absorption|Fire|26}}
    match = _ABSORPTION_RE.search(text)
    if match:
        element = match.group(1).strip()
        value = int(match.group(2))
        return {"value": value, "bonus_type": "Enhancement", "stat": f"{element} Absorption"}

    # {{Spell Focus|Abjuration|3}} or {{Spell Focus|Spell Focus Mastery|2|Sacred}}
    match = _SPELL_FOCUS_RE.search(text)
    if match:
        school = match.group(1).strip()
        value = int(match.group(2))
        raw_bonus_type = (match.group(3) or "Enhancement").strip()
        bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
        stat = f"{school} Spell Focus" if "mastery" not in school.lower() and "spell" not in school.lower() else school
        return {"value": value, "bonus_type": bonus_type, "stat": stat}

    # {{Hp|Vitality|25}} (hit point bonus with numeric value)
    match = _HP_TEMPLATE_RE.search(text)
    if match:
        value = int(match.group(1))
        return {"value": value, "bonus_type": "Enhancement", "stat": "Hit Points"}

    # {{HealingAmp|53|R}} or {{HealingAmp|17|h|Competence}}
    match = _HEALINGAMP_RE.search(text)
    if match:
        value = int(match.group(1))
        amp_type = (match.group(2) or "h").strip().lower()
        raw_bonus_type = (match.group(3) or "Enhancement").strip()
        bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
        stat = "Repair Amplification" if amp_type == "r" else "Healing Amplification"
        return {"value": value, "bonus_type": bonus_type, "stat": stat}

    # Fallback: plain text "+7 Enhancement bonus to Strength"
    match = _ENCHANTMENT_RE.match(text)
    if match:
        value = int(match.group(1))
        raw_bonus_type = match.group(2).strip()
        stat = match.group(3).strip()
        bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
        return {"value": value, "bonus_type": bonus_type, "stat": stat}

    return None


# ---------------------------------------------------------------------------
# Wiki-Correlation Mapper
# ---------------------------------------------------------------------------


@dataclass
class StatMapping:
    """Confirmed or candidate mapping from stat_def_id to stat name."""

    stat_def_id: int
    stat_name: str
    confirmations: int = 0
    conflicts: int = 0
    conflict_names: set[str] = field(default_factory=set)


@dataclass
class BonusTypeMapping:
    """Confirmed or candidate mapping from bonus_type_code to bonus type name."""

    bonus_type_code: int
    bonus_type_name: str
    confirmations: int = 0
    conflicts: int = 0
    conflict_names: set[str] = field(default_factory=set)


@dataclass
class EffectMapResult:
    """Results from wiki-correlation mapping of effect entries."""

    stat_mappings: dict[int, StatMapping] = field(default_factory=dict)
    bonus_type_mappings: dict[int, BonusTypeMapping] = field(default_factory=dict)
    items_processed: int = 0
    items_with_both: int = 0
    correlations_attempted: int = 0
    correlations_matched: int = 0
    unmatched_enchantments: list[str] = field(default_factory=list)


def build_effect_map(
    ddo_path: Path,
    wiki_items: list[dict],
    *,
    on_progress: Callable[[str], None] | None = None,
) -> EffectMapResult:
    """Correlate wiki enchantment strings with binary effect entries.

    For each wiki item that has both enchantments and a matching binary
    entry with effect_refs, attempts to match enchantment strings to
    decoded effects by magnitude, discovering stat_def_id and bonus_type_code
    mappings.

    Args:
        ddo_path: DDO installation directory containing .dat files.
        wiki_items: List of wiki item dicts (from collect_items or JSON).
        on_progress: Optional callback for status messages.

    Returns:
        EffectMapResult with discovered stat and bonus type mappings.
    """
    from .btree import traverse_btree
    from .namemap import DISCOVERED_KEYS, decode_dup_triple
    from .probe import decode_effect_entry
    from .strings import load_string_table

    result = EffectMapResult()

    # Load archives
    english_path = ddo_path / "client_local_English.dat"
    gamelogic_path = ddo_path / "client_gamelogic.dat"
    if not english_path.exists() or not gamelogic_path.exists():
        logger.warning("Required .dat archives not found at %s", ddo_path)
        return result

    if on_progress:
        on_progress("Loading string table...")
    english_archive = DatArchive(english_path)
    english_archive.read_header()
    string_table = load_string_table(english_archive)

    if on_progress:
        on_progress("Loading gamelogic entries...")
    gamelogic_archive = DatArchive(gamelogic_path)
    gamelogic_archive.read_header()
    entries = traverse_btree(gamelogic_archive)
    if on_progress:
        on_progress(f"  {len(entries):,} entries loaded")

    # Build effect_ref key set (same pattern as items.py)
    effect_ref_keys: frozenset[int] = frozenset(
        key for key, info in DISCOVERED_KEYS.items()
        if info["name"].startswith("effect_ref")
    )

    # Build name -> (file_id, entry) index for 0x79 entries
    binary_by_name: dict[str, tuple[int, FileEntry]] = {}
    for file_id, entry in entries.items():
        if (file_id >> 24) & 0xFF != 0x79:
            continue
        lower = file_id & 0x00FFFFFF
        str_id = 0x25000000 | lower
        name = string_table.get(str_id)
        if name:
            norm = name.strip().replace("_", " ").lower()
            if norm not in binary_by_name:
                binary_by_name[norm] = (file_id, entry)

    if on_progress:
        on_progress(f"  {len(binary_by_name):,} named binary entries indexed")

    # Process each wiki item
    for wiki_item in wiki_items:
        result.items_processed += 1
        wiki_name = wiki_item.get("name")
        if not wiki_name:
            continue

        enchantments = wiki_item.get("enchantments") or []
        if not enchantments:
            continue

        # Parse wiki enchantment strings
        parsed_enchantments: list[dict] = []
        for ench_str in enchantments:
            parsed = parse_enchantment_string(ench_str)
            if parsed:
                parsed_enchantments.append(parsed)
            elif ench_str.strip():
                if len(result.unmatched_enchantments) < 100:
                    result.unmatched_enchantments.append(ench_str)

        if not parsed_enchantments:
            continue

        # Find matching binary entry (decode HTML entities, try Legendary prefix)
        clean_name = html.unescape(wiki_name).strip().replace("_", " ")
        norm = clean_name.lower()
        binary_match = binary_by_name.get(norm)
        if binary_match is None and not norm.startswith("legendary "):
            binary_match = binary_by_name.get("legendary " + norm)
        if binary_match is None and norm.startswith("legendary "):
            binary_match = binary_by_name.get(norm[len("legendary "):])
        if binary_match is None:
            continue

        file_id, entry = binary_match

        # Decode binary entry to extract effect_refs
        try:
            data = read_entry_data(gamelogic_archive, entry)
        except (ValueError, OSError):
            continue

        properties = decode_dup_triple(data)
        if not properties:
            continue

        # Collect effect refs from properties
        effect_ref_ids: list[int] = []
        for prop in properties:
            if prop.key in effect_ref_keys and not prop.is_array:
                if isinstance(prop.value, int) and (prop.value >> 24) & 0xFF == 0x70:
                    effect_ref_ids.append(prop.value)

        if not effect_ref_ids:
            continue

        result.items_with_both += 1

        # Decode each effect entry
        decoded_effects: list[dict] = []
        for ref_id in effect_ref_ids:
            effect_entry = entries.get(ref_id)
            if effect_entry is None:
                continue
            try:
                effect_data = read_entry_data(gamelogic_archive, effect_entry)
            except (ValueError, OSError):
                continue
            effect_desc = decode_effect_entry(effect_data)
            if effect_desc is not None:
                decoded_effects.append(effect_desc)

        if not decoded_effects:
            continue

        # Correlate: magnitude matching first, then 1:1 type-17 fallback
        _correlate_item_effects(result, parsed_enchantments, decoded_effects)

    if on_progress:
        confirmed_stats = sum(
            1 for m in result.stat_mappings.values()
            if m.confirmations >= 3 and m.conflicts == 0
        )
        on_progress(
            f"Processed {result.items_with_both:,} items with both data sources. "
            f"Discovered {confirmed_stats} confirmed stat mappings."
        )

    return result


def _correlate_item_effects(
    result: EffectMapResult,
    parsed_enchantments: list[dict],
    decoded_effects: list[dict],
) -> None:
    """Match wiki enchantments to binary effects within a single item.

    Strategy 1: Match by magnitude (works for type-53 entries).
    Strategy 2: 1:1 type-17 fallback — when an item has exactly N {{Stat}}
    enchantments and exactly N type-17 effects, match them positionally.
    If N=1, the mapping is unambiguous.
    """
    # --- Strategy 1: magnitude matching (type-53 entries) ---
    effects_by_magnitude: dict[int, list[dict]] = {}
    for effect in decoded_effects:
        mag = effect.get("magnitude")
        if mag is not None and mag > 0:
            effects_by_magnitude.setdefault(mag, []).append(effect)

    used_effects: set[int] = set()

    for parsed in parsed_enchantments:
        result.correlations_attempted += 1
        magnitude = parsed["value"]
        candidates = effects_by_magnitude.get(magnitude, [])

        if not candidates:
            continue

        available = [
            (i, e) for i, e in enumerate(candidates)
            if id(e) not in used_effects
        ]
        if not available:
            continue

        if len(available) == 1:
            _, effect = available[0]
            used_effects.add(id(effect))
            result.correlations_matched += 1
            _record_stat_mapping(result, effect["stat_def_id"], parsed["stat"])
            _record_bonus_type_mapping(result, effect["bonus_type_code"], parsed["bonus_type"])
        else:
            matched = False
            for _, effect in available:
                existing = result.bonus_type_mappings.get(effect["bonus_type_code"])
                if existing and existing.bonus_type_name == parsed["bonus_type"]:
                    used_effects.add(id(effect))
                    result.correlations_matched += 1
                    _record_stat_mapping(result, effect["stat_def_id"], parsed["stat"])
                    matched = True
                    break

            if not matched and len(available) <= 3:
                _, effect = available[0]
                used_effects.add(id(effect))
                result.correlations_matched += 1
                _record_stat_mapping(result, effect["stat_def_id"], parsed["stat"])
                _record_bonus_type_mapping(
                    result, effect["bonus_type_code"], parsed["bonus_type"]
                )

    # --- Strategy 2: 1:1 type-17 fallback ---
    # Type-17 entries have implicit magnitude=1, so magnitude matching only
    # works for +1 bonuses. Instead, when the item has exactly 1 stat
    # enchantment and exactly 1 type-17 effect, correlate directly.
    type17_effects = [
        e for e in decoded_effects
        if e.get("entry_type") == 0x11 and id(e) not in used_effects
    ]
    stat_enchantments = [
        p for p in parsed_enchantments
        if p["stat"] in _STAT_NAMES_FOR_TYPE17
    ]

    if len(type17_effects) == 1 and len(stat_enchantments) == 1:
        effect = type17_effects[0]
        parsed = stat_enchantments[0]
        result.correlations_attempted += 1
        result.correlations_matched += 1
        _record_stat_mapping(result, effect["stat_def_id"], parsed["stat"])
        _record_bonus_type_mapping(result, effect["bonus_type_code"], parsed["bonus_type"])


def _record_stat_mapping(
    result: EffectMapResult,
    stat_def_id: int,
    stat_name: str,
) -> None:
    """Record a stat_def_id -> stat_name correlation."""
    existing = result.stat_mappings.get(stat_def_id)
    if existing is None:
        result.stat_mappings[stat_def_id] = StatMapping(
            stat_def_id=stat_def_id,
            stat_name=stat_name,
            confirmations=1,
        )
    elif existing.stat_name == stat_name:
        existing.confirmations += 1
    else:
        existing.conflicts += 1
        existing.conflict_names.add(stat_name)


def _record_bonus_type_mapping(
    result: EffectMapResult,
    bonus_type_code: int,
    bonus_type_name: str,
) -> None:
    """Record a bonus_type_code -> bonus_type_name correlation."""
    existing = result.bonus_type_mappings.get(bonus_type_code)
    if existing is None:
        result.bonus_type_mappings[bonus_type_code] = BonusTypeMapping(
            bonus_type_code=bonus_type_code,
            bonus_type_name=bonus_type_name,
            confirmations=1,
        )
    elif existing.bonus_type_name == bonus_type_name:
        existing.confirmations += 1
    else:
        existing.conflicts += 1
        existing.conflict_names.add(bonus_type_name)


def format_effect_map(result: EffectMapResult, min_confidence: float = 0.95) -> str:
    """Format an EffectMapResult as a human-readable report."""
    lines: list[str] = []

    lines.append("Effect Stat/Bonus Mapping Report")
    lines.append("=" * 32)
    lines.append(
        f"Items processed: {result.items_processed:,}"
        f"  (with both sources: {result.items_with_both:,})"
    )
    lines.append(
        f"Correlations: {result.correlations_matched:,} matched"
        f" / {result.correlations_attempted:,} attempted"
    )
    lines.append("")

    # Stat mappings
    confirmed = []
    uncertain = []
    for m in sorted(result.stat_mappings.values(), key=lambda m: -m.confirmations):
        total = m.confirmations + m.conflicts
        confidence = m.confirmations / max(total, 1)
        if m.confirmations >= 3 and confidence >= min_confidence:
            confirmed.append(m)
        else:
            uncertain.append(m)

    lines.append(f"Confirmed stat_def_id mappings ({len(confirmed)}):")
    lines.append(f"  {'stat_def_id':>12s}  {'Stat Name':<35s}  {'Conf':>4s}  {'Conflicts':>9s}")
    lines.append(f"  {'-' * 12}  {'-' * 35}  {'-' * 4}  {'-' * 9}")
    for m in confirmed:
        lines.append(
            f"  {m.stat_def_id:>12d}  {m.stat_name:<35s}  {m.confirmations:>4d}  {m.conflicts:>9d}"
        )
    lines.append("")

    if uncertain:
        lines.append(f"Uncertain stat_def_id mappings ({len(uncertain)}):")
        for m in uncertain[:20]:
            conflict_str = ""
            if m.conflict_names:
                conflict_str = f"  conflicts: {', '.join(sorted(m.conflict_names))}"
            lines.append(
                f"  {m.stat_def_id:>12d}  {m.stat_name:<35s}"
                f"  conf={m.confirmations} conflicts={m.conflicts}{conflict_str}"
            )
        lines.append("")

    # Bonus type mappings
    confirmed_bt = []
    for m in sorted(result.bonus_type_mappings.values(), key=lambda m: -m.confirmations):
        total = m.confirmations + m.conflicts
        confidence = m.confirmations / max(total, 1)
        if m.confirmations >= 3 and confidence >= min_confidence:
            confirmed_bt.append(m)

    lines.append(f"Confirmed bonus_type_code mappings ({len(confirmed_bt)}):")
    lines.append(f"  {'Code':>8s}  {'Bonus Type':<20s}  {'Conf':>4s}")
    lines.append(f"  {'-' * 8}  {'-' * 20}  {'-' * 4}")
    for m in confirmed_bt:
        lines.append(f"  0x{m.bonus_type_code:04X}  {m.bonus_type_name:<20s}  {m.confirmations:>4d}")
    lines.append("")

    # Suggested code
    if confirmed:
        lines.append("Suggested STAT_DEF_IDS update:")
        lines.append("STAT_DEF_IDS: dict[int, str] = {")
        for m in sorted(confirmed, key=lambda m: m.stat_def_id):
            lines.append(f'    {m.stat_def_id:>5d}: "{m.stat_name}",')
        lines.append("}")
        lines.append("")

    if confirmed_bt:
        lines.append("Suggested BONUS_TYPE_CODES update:")
        lines.append("BONUS_TYPE_CODES: dict[int, str] = {")
        for m in sorted(confirmed_bt, key=lambda m: m.bonus_type_code):
            lines.append(f'    0x{m.bonus_type_code:04X}: "{m.bonus_type_name}",')
        lines.append("}")

    return "\n".join(lines)


def format_effect_map_json(result: EffectMapResult, min_confidence: float = 0.95) -> dict:
    """Format an EffectMapResult as a JSON-serializable dict."""
    confirmed_stats = {}
    uncertain_stats = {}
    for sid, m in sorted(result.stat_mappings.items(), key=lambda kv: -kv[1].confirmations):
        total = m.confirmations + m.conflicts
        confidence = m.confirmations / max(total, 1)
        entry = {
            "stat_name": m.stat_name,
            "confirmations": m.confirmations,
            "conflicts": m.conflicts,
            "confidence": round(confidence, 3),
        }
        if m.conflict_names:
            entry["conflict_names"] = sorted(m.conflict_names)
        if m.confirmations >= 3 and confidence >= min_confidence:
            confirmed_stats[str(sid)] = entry
        else:
            uncertain_stats[str(sid)] = entry

    confirmed_bonus = {}
    for btc, m in sorted(
        result.bonus_type_mappings.items(), key=lambda kv: -kv[1].confirmations
    ):
        total = m.confirmations + m.conflicts
        confidence = m.confirmations / max(total, 1)
        if m.confirmations >= 3 and confidence >= min_confidence:
            confirmed_bonus[f"0x{btc:04X}"] = {
                "bonus_type_name": m.bonus_type_name,
                "confirmations": m.confirmations,
                "confidence": round(confidence, 3),
            }

    return {
        "summary": {
            "items_processed": result.items_processed,
            "items_with_both": result.items_with_both,
            "correlations_matched": result.correlations_matched,
            "correlations_attempted": result.correlations_attempted,
            "confirmed_stat_mappings": len(confirmed_stats),
            "confirmed_bonus_mappings": len(confirmed_bonus),
        },
        "confirmed_stat_mappings": confirmed_stats,
        "uncertain_stat_mappings": uncertain_stats,
        "confirmed_bonus_type_mappings": confirmed_bonus,
        "unmatched_enchantments": result.unmatched_enchantments[:50],
    }
