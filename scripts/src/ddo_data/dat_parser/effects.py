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
    "ins": "Insight",
    "Equipment": "Enhancement",
    "enh": "Enhancement",
    "comp": "Competence",
    "qual": "Quality",
    "resist": "Resistance",
    # "Legendary" is a tier marker, not a bonus type — but some wiki text
    # uses it where the actual bonus type is unspecified. Keep as-is.
}

# Roman numeral → integer conversion for wiki template values.
_ROMAN_NUMERALS: dict[str, int] = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
    "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
    "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15,
    "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20,
    "M": 1000,  # Wizardry M = 1000 spell points
}


def _parse_int(value: str) -> int | None:
    """Parse an integer from a wiki template value, handling +/- prefix and %."""
    value = value.strip().lstrip("+").rstrip("%")
    roman = _ROMAN_NUMERALS.get(value.upper())
    if roman is not None:
        return roman
    try:
        return int(value)
    except ValueError:
        return None

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
    r"([^|}]+)"               # magnitude (may have +/- prefix)
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
    r"([^|}]+)"               # magnitude
    r"(?:\|([^|}]+))?"        # optional bonus type
    r"(?:\|([^|}]+))?"        # optional physical/magical
    r"\}\}",
    re.IGNORECASE,
)

# Regex for wiki {{SpellPower|...}} template:
#   {{SpellPower|Devotion|30}} → +30 Devotion (Universal Spell Power variant)
_SPELLPOWER_TEMPLATE_RE = re.compile(
    r"\{\{SpellPower\|"
    r"([^|}]+)\|"             # spell power name (Devotion, Impulse, etc.)
    r"([^|}]+)"               # magnitude
    r"(?:\|([^|}]+))?"        # optional bonus type
    r"(?:\|[^}]*)?"           # optional extra params
    r"\}\}",
    re.IGNORECASE,
)

# Regex for wiki {{Seeker|...}} template:
#   {{Seeker|3}}     → +3 Enhancement Seeker
#   {{Seeker|4|Insightful}} → +4 Insightful Seeker
_SEEKER_TEMPLATE_RE = re.compile(
    r"\{\{Seeker\|"
    r"([^|}]+)"               # magnitude
    r"(?:\|([^|}]+))?"        # optional bonus type
    r"(?:\|[^}]*)?"           # optional extra params (nocat=, etc.)
    r"\}\}",
    re.IGNORECASE,
)

# Regex for wiki {{Deadly|...}} template:
#   {{Deadly|4|Insightful}} → +4 Insightful Deadly
_DEADLY_TEMPLATE_RE = re.compile(
    r"\{\{Deadly\|"
    r"([^|}]+)"               # magnitude (numeric or roman)
    r"(?:\|([^|}]+))?"        # optional bonus type
    r"\}\}",
    re.IGNORECASE,
)

# Regex for wiki {{Fortification|...}} template:
#   {{Fortification|100}} → +100 Fortification
_FORTIFICATION_TEMPLATE_RE = re.compile(
    r"\{\{Fortification\|"
    r"([^|}]+)"               # magnitude (numeric or word like "heavy")
    r"(?:\|([^|}]+))?"        # optional bonus type
    r"\}\}",
    re.IGNORECASE,
)

# Regex for wiki {{Save|...}} template:
#   {{Save|r|11}} → +11 Reflex Save
_SAVE_TEMPLATE_RE = re.compile(
    r"\{\{Save\|"
    r"([^|}]+)\|"             # save type abbreviation
    r"([^|}]+)"               # magnitude
    r"(?:\|([^|}]+))?"        # optional bonus type
    r"(?:\|[^}]*)?"           # optional extra params
    r"\}\}",
    re.IGNORECASE,
)

# Save abbreviations
_SAVE_ABBREVS: dict[str, str] = {
    "e": "Enchantment Save",
    "s": "Sleep Save",
    "a": "Saving Throws",
    "all": "Saving Throws",
    "f": "Fortitude Save",
    "r": "Reflex Save",
    "w": "Will Save",
    "will": "Will Save",
    "fort": "Fortitude Save",
    "ref": "Reflex Save",
    "fortitude": "Fortitude Save",
    "reflex": "Reflex Save",
    "spell": "Spell Resistance",
    "enchantment": "Enchantment Save",
    "illusion": "Illusion Save",
    "fear": "Fear Save",
    "poison": "Poison Save",
    "disease": "Disease Save",
    "trap": "Trap Save",
    "curse": "Curse Save",
    "sleep": "Sleep Save",
    "curse": "Curse Save",
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
    "intimidate": "Intimidate",
    "haggle": "Haggle",
    # Ability abbreviations sometimes appear in {{Skills}} template
    "str": "Strength",
    "dex": "Dexterity",
    "con": "Constitution",
    "int": "Intelligence",
    "wis": "Wisdom",
    "cha": "Charisma",
    "command": "Command",  # Bonus to all Charisma-based skills
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
    "command": "Command",  # Bonus to all CHA-based skills (not just Intimidate)
    "dd": "Disable Device",
    "ms": "Move Silently",
    "ol": "Open Lock",
    "bal": "Balance",
    "diplo": "Diplomacy",
    "persuasion": "Persuasion",  # Bonus to all Charisma-based skills
}

# Stat name normalization for simple numeric templates
_SIMPLE_STAT_NAMES: dict[str, str] = {
    "naturalarmor": "Natural Armor",
    "protectionbonus": "Protection",
    "spellpen": "Spell Penetration",
}

# Simple numeric-value templates: {{Name|value}} or {{Name|value|bonus_type}}
# Parsed into stat=Name, value=N, bonus_type=Enhancement or specified.
_SIMPLE_NUMERIC_RE = re.compile(
    r"\{\{"
    r"(Accuracy|Deception|Speed|Resistance|Wizardry|Sheltering MRR"
    r"|Dodge|Doublestrike|Doubleshot|Concealment"
    r"|NaturalArmor|ProtectionBonus|Spellpen)"
    r"\|([^|}]+)"
    r"(?:\|([^|}]+))?"
    r"(?:\|[^}]*)?"
    r"\}\}",
    re.IGNORECASE,
)

# {{Skills|name|value}} or {{Skills|name|value|bonus_type}}
_SKILLS_TEMPLATE_RE = re.compile(
    r"\{\{Skills\|"
    r"([^|}]+)"               # skill name or abbreviation (may be only param)
    r"(?:\|([^|}]+))?"        # optional value
    r"(?:\|([^|}]+))?"        # optional bonus type
    r"(?:\|[^}]*)?"           # optional extra params (prefix= etc)
    r"\}\}",
    re.IGNORECASE,
)

# {{Elemental Resistance|Element|value}}
_ELEMENTAL_RESIST_RE = re.compile(
    r"\{\{Elemental Resistance\|"
    r"([^|}]+)\|"             # element name
    r"([^|}]+)"               # value
    r"(?:\|([^|}]+))?"        # optional bonus type
    r"\}\}",
    re.IGNORECASE,
)

# {{Absorption|Element|value}}
_ABSORPTION_RE = re.compile(
    r"\{\{Absorption\|"
    r"([^|}]+)\|"             # element name
    r"([^|}]+)"               # value
    r"(?:\|[^}]*)?"           # optional extra params
    r"\}\}",
    re.IGNORECASE,
)

# {{Spell Focus|School|N}} or {{Spell Focus|Spell Focus Mastery|II|Sacred}}
_SPELL_FOCUS_RE = re.compile(
    r"\{\{Spell Focus\|"
    r"([^|}]+)\|"             # school or "Spell Focus Mastery" / "Spell" / "Mastery"
    r"([^|}]+)"               # value (numeric or roman)
    r"(?:\|([^|}]+))?"        # optional bonus type
    r"(?:\|[^}]*)?"           # optional extra params
    r"\}\}",
    re.IGNORECASE,
)

# {{Hp|type|value}} where type is "Vitality", "False Life", etc.
_HP_TEMPLATE_RE = re.compile(
    r"\{\{Hp\|"
    r"[^|}]+\|"              # hp type name (Vitality, False Life, etc.)
    r"([^|}]+)"              # value
    r"(?:\|[^}]*)?"          # optional extra
    r"\}\}",
    re.IGNORECASE,
)

# {{HealingAmp|value|type|bonus_type}}
_HEALINGAMP_RE = re.compile(
    r"\{\{HealingAmp\|"
    r"([^|}]+)"               # value
    r"(?:\|([^|}]*))?"        # type (h=healing, R=repair, empty, etc.)
    r"(?:\|([^|}]+))?"        # optional bonus type
    r"\}\}",
    re.IGNORECASE,
)

# Spell power display names → stat table names
_SPELLPOWER_STATS: dict[str, str] = {
    # Standard DDO spell power names (single-element map to primary element;
    # some affect secondary elements too but those are handled via game engine,
    # not stored as separate DB rows)
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
    "Potency": "Potency",  # composite: split in COMPOSITE_SPELLPOWER
    "Devotion,Heal": "Positive Spell Power",
    "Universal Spell Power": "Universal Spell Power",
    # Lowercase variants
    "corrosion": "Acid Spell Power",
    "combustion": "Fire Spell Power",
    "glaciation": "Cold Spell Power",
    "magnetism": "Electric Spell Power",
    "resonance": "Sonic Spell Power",
    "radiance": "Light Spell Power",
    "devotion": "Positive Spell Power",
    "nullification": "Negative Spell Power",
    "impulse": "Force Spell Power",
    "potency": "Potency",
    "reconstruction": "Repair Spell Power",
}

# Named set spell powers/lore that affect MULTIPLE elements (composite).
# These can't be stored as a single stat — the writer should split them.
# Format: name -> list of stat names
COMPOSITE_SPELLPOWER: dict[str, list[str]] = {
    # Potency = all element spell powers (stacking via bonus_type)
    "Potency": [
        "Fire Spell Power", "Cold Spell Power", "Electric Spell Power",
        "Acid Spell Power", "Sonic Spell Power", "Light Spell Power",
        "Negative Spell Power", "Positive Spell Power", "Force Spell Power",
        "Repair Spell Power",
    ],
    # Named set spell powers (from ddowiki.com/page/Spell_Power)
    "Power of the Silver Flame": ["Light Spell Power", "Positive Spell Power"],
    "Power of the Frozen Depths": ["Cold Spell Power", "Negative Spell Power"],
    "Power of the Firestorm": ["Fire Spell Power", "Electric Spell Power"],
    "Power of the Flames of Purity": ["Light Spell Power", "Positive Spell Power"],
    "Power of the Blight": ["Acid Spell Power", "Negative Spell Power"],
    "Power of Creeping Dust": ["Acid Spell Power", "Cold Spell Power"],
    "Power of the Frozen Storm": ["Cold Spell Power", "Electric Spell Power"],
    "Power of the Thunderstorm": ["Electric Spell Power", "Sonic Spell Power"],
    "Power of the Dark Restoration": ["Positive Spell Power", "Negative Spell Power"],
    "Power of the Sacred Ground": ["Acid Spell Power", "Light Spell Power"],
}

COMPOSITE_SPELLLORE: dict[str, list[str]] = {
    # Named set spell lore (same elements as corresponding spell power)
    "Silver Flame": ["Light Spell Lore", "Positive Spell Lore"],
    "Frozen Depths": ["Cold Spell Lore", "Negative Spell Lore"],
    "Firestorm": ["Fire Spell Lore", "Electric Spell Lore"],
    "Flames of Purity": ["Light Spell Lore", "Positive Spell Lore"],
    "Blighted": ["Acid Spell Lore", "Negative Spell Lore"],
    "Blight": ["Acid Spell Lore", "Negative Spell Lore"],
    "Creeping Dust": ["Acid Spell Lore", "Cold Spell Lore"],
    "Frozen Storm": ["Cold Spell Lore", "Electric Spell Lore"],
    "Thunderstorm": ["Electric Spell Lore", "Sonic Spell Lore"],
    "Dark Restoration": ["Positive Spell Lore", "Negative Spell Lore"],
    "Sacred Ground": ["Acid Spell Lore", "Light Spell Lore"],
}

# Wiki element name aliases → canonical seed names
# Named enchantment effects — fixed bonuses/penalties from enchantment wiki pages.
# These are effects that AREN'T encoded in the item's {{template}} enchantment list
# but ARE part of the enchantment's definition on its own wiki page.
# Verified against ddowiki.com/page/Category:Unique_item_enchantments
# Format: enchantment_name -> list of {stat, value, bonus_type, is_penalty}
NAMED_ENCHANTMENT_EFFECTS: dict[str, list[dict]] = {
    "Command": [
        {"stat": "Command", "value": None, "bonus_type": "Competence"},  # +X from template
        {"stat": "Hide", "value": -6, "bonus_type": "Enhancement", "is_penalty": True},
    ],
    "Deception": [
        {"stat": "Sneak Attack", "value": None, "bonus_type": "Enhancement"},  # +X attack from template
        {"stat": "Sneak Attack Damage", "value": None, "bonus_type": "Enhancement"},  # +1.5X damage
        {"stat": None, "value": None, "bonus_type": None,
         "description": "5% chance on hit: target is Bluffed for 4s (sneak attackable)"},
    ],
    "Persuasion": [
        {"stat": "Persuasion", "value": None, "bonus_type": "Competence"},  # +X from template
    ],
    "Blood": [
        {"stat": "Healing Amplification", "value": 20, "bonus_type": "Enhancement"},
    ],
    # Bloodrage Defense: CONDITIONAL (two-handed weapon only). Removed.
    # Conditional/proc effects — stored as description-only (stat_id=NULL in DB).
    # Value=None signals the writer to store as description, not a numeric bonus.
    "Cannith Combat Infusion": [
        {"stat": None, "value": None, "bonus_type": None,
         "description": "Proc: +4 Alchemical STR/CON/DEX, +2 Alchemical AC, +5% Doublestrike for 10s on hit (1.5% chance)"},
    ],
    "Soul of the Elements": [
        {"stat": None, "value": None, "bonus_type": None,
         "description": "Mountain Stance: +10 Insight AC and Reflex saves"},
    ],
    "Bloodrage Defense": [
        {"stat": None, "value": None, "bonus_type": None,
         "description": "Two-handed weapon: +10 Profane PRR and MRR"},
    ],
    "Faeryfire Curse": [
        {"stat": None, "value": None, "bonus_type": None,
         "description": "Proc on Illusion spells: -40 Hide for 30s, dispels stealth"},
    ],
    "Sea Attunement": [
        {"stat": None, "value": None, "bonus_type": None,
         "description": "Water Elemental form: +10 Exceptional Cold Spell Power"},
    ],
    "Sky Attunement": [
        {"stat": None, "value": None, "bonus_type": None,
         "description": "Fire Elemental form: +10 Exceptional Fire Spell Power"},
    ],
    "Spell Resonance": [
        {"stat": None, "value": None, "bonus_type": None,
         "description": "Proc on Sonic cast: +20 Alchemical Sonic Spell Power for 30s"},
    ],
    "Embrace of the Spider Queen": [
        {"stat": "Poison Save", "value": 6, "bonus_type": "Enhancement"},  # +6, not -6
    ],
    "Dragonshard Focus: Sentinel": [
        {"stat": "Armor Class", "value": 1, "bonus_type": "Insight"},
        {"stat": "Fortitude Save", "value": 1, "bonus_type": "Insight"},
    ],
    "Finesse": [
        {"stat": "Dexterity", "value": 2, "bonus_type": "Enhancement"},
    ],
    # Litany of the Dead: UNCERTAIN. Removed pending verification.
    "Overfocus": [
        {"stat": "Search", "value": -10, "bonus_type": "Enhancement", "is_penalty": True},
        {"stat": "Spot", "value": -10, "bonus_type": "Enhancement", "is_penalty": True},
    ],
    # Sea/Sky/Static Attunement: CONDITIONAL (elemental form only). Removed.
    "Songblade": [
        {"stat": "Perform", "value": 2, "bonus_type": "Enhancement"},
    ],
    # Soul of the Elements: CONDITIONAL (Mountain Stance only). Removed.
    # Spell Resonance: CONDITIONAL (30s proc on Sonic cast). Removed.
    "Voice of Deceit": [
        {"stat": "Bluff", "value": 20, "bonus_type": "Competence"},
    ],
    "Strength of Purpose": [
        {"stat": "Unconsciousness Range", "value": 128, "bonus_type": "Enhancement"},
    ],
    "Undying": [
        {"stat": "Unconsciousness Range", "value": 100, "bonus_type": "Enhancement"},
    ],
    # Weighty Asset: +100 unconsciousness range — appears permanent, but needs verification.
    # Keeping for now.
    # Proficiency penalties (always active when wielding weapon without proficiency)
    "Proficiency: Bastard Sword": [
        {"stat": "Attack Bonus", "value": -4, "bonus_type": "Enhancement", "is_penalty": True},
    ],
    "Proficiency: Greatclub": [
        {"stat": "Attack Bonus", "value": -4, "bonus_type": "Enhancement", "is_penalty": True},
    ],
    "Proficiency: Longbow": [
        {"stat": "Attack Bonus", "value": -4, "bonus_type": "Enhancement", "is_penalty": True},
    ],
    "Proficiency: Longsword": [
        {"stat": "Attack Bonus", "value": -4, "bonus_type": "Enhancement", "is_penalty": True},
    ],
    "Proficiency: Shortbow": [
        {"stat": "Attack Bonus", "value": -4, "bonus_type": "Enhancement", "is_penalty": True},
    ],
    # Specific item enchantments (always active)
    "Marksmanship": [
        {"stat": "Ranged Power", "value": None, "bonus_type": "Competence"},  # +X from template
    ],
    "Life-Devouring": [
        {"stat": None, "value": None, "bonus_type": None,
         "description": "-6 to all ability scores while equipped"},
    ],
    "Spellcasting Implement": [
        {"stat": None, "value": None, "bonus_type": None,
         "description": "+1 Implement Spell Power per ML, +3 per Enhancement Bonus"},
    ],
    # Enemy debuffs (description-only)
    "Chaotic Curse": [
        {"stat": None, "value": None, "bonus_type": None,
         "description": "On hit: -4 to target's attack rolls"},
    ],
    "Dazing": [
        {"stat": None, "value": None, "bonus_type": None,
         "description": "On hit: -1 Will Save to target for 6 seconds"},
    ],
    "Destruction": [
        {"stat": None, "value": None, "bonus_type": None,
         "description": "On hit: -1 AC to target (stacks)"},
    ],
    "Magma Surge": [
        {"stat": None, "value": None, "bonus_type": None,
         "description": "On hit: -1 to target's attack rolls"},
    ],
    "Overwhelming Despair": [
        {"stat": None, "value": None, "bonus_type": None,
         "description": "On hit: -2 to target's attack rolls"},
    ],
}


_ELEMENT_ALIASES: dict[str, str] = {
    "lightning": "Electric",
    "ice": "Cold",
    "poison": "Poison",
    "healing": "Positive",
    "void": "Negative",
    "kinetic": "Force",
    "radiance": "Light",
    "chaos": "Chaos",
    "electricity": "Electric",
    "electrical": "Electric",
    "elemental": "Elemental",
    "spell": "Spell",
    "negative energy": "Negative Energy",
    "negative": "Negative Energy",
    "alignment": "Alignment",
    "law": "Law",
    "cold": "Cold",
    "fire": "Fire",
    "acid": "Acid",
    "sonic": "Sonic",
    "light": "Light",
    "good": "Good",
    "evil": "Evil",
    "curse": "Curse",
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

    # Strip wiki links: [[Quality bonus]] -> Quality bonus, [[target|display]] -> display
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", text)

    # Try wiki {{Stat}} template first (most common for stat bonuses)
    match = _STAT_TEMPLATE_RE.search(text)
    if match:
        raw_stat = match.group(1).strip()
        value = _parse_int(match.group(2))
        if value is not None:
            raw_bonus_type = (match.group(3) or "Enhancement").strip()
            stat = _STAT_ABBREVS.get(raw_stat.upper(), raw_stat)
            bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
            return {"value": value, "bonus_type": bonus_type, "stat": stat}

    # {{Sheltering|33|Enhancement|Physical}} or {{Sheltering|33}} or {{Sheltering|5|Insightful}}
    match = _SHELTERING_TEMPLATE_RE.search(text)
    if match:
        value = _parse_int(match.group(1))
        if value is not None:
            param2 = (match.group(2) or "").strip()
            param3 = (match.group(3) or "").strip()
            if param3:
                # 3-param: value|bonus_type|physical_or_magical
                bonus_type = _BONUS_TYPE_ALIASES.get(param2, param2) if param2 else "Enhancement"
                stat = f"{param3.title()} Sheltering"
            elif param2 and _parse_int(param2) is None:
                # 2-param: value|bonus_type (no physical/magical specified)
                bonus_type = _BONUS_TYPE_ALIASES.get(param2, param2)
                stat = "Sheltering"
            else:
                bonus_type = "Enhancement"
                stat = "Sheltering"
            return {"value": value, "bonus_type": bonus_type, "stat": stat}

    # {{SpellPower|Devotion|30}}
    match = _SPELLPOWER_TEMPLATE_RE.search(text)
    if match:
        sp_name = match.group(1).strip()
        value = _parse_int(match.group(2))
        if value is not None:
            raw_bonus_type = (match.group(3) or "Enhancement").strip()
            # Filter wiki metadata params (nocat=TRUE, etc.)
            if "=" in raw_bonus_type:
                raw_bonus_type = "Enhancement"
            bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
            stat = _SPELLPOWER_STATS.get(sp_name, f"{sp_name} Spell Power")
            return {"value": value, "bonus_type": bonus_type, "stat": stat}

    # {{Seeker|3}} or {{Seeker|4|Insightful}}
    match = _SEEKER_TEMPLATE_RE.search(text)
    if match:
        value = _parse_int(match.group(1))
        if value is not None:
            raw_bonus_type = (match.group(2) or "Enhancement").strip()
            bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
            return {"value": value, "bonus_type": bonus_type, "stat": "Seeker"}

    # {{Deadly|4|Insightful}} or {{Deadly|III}}
    match = _DEADLY_TEMPLATE_RE.search(text)
    if match:
        value = _parse_int(match.group(1))
        if value is not None:
            raw_bonus_type = (match.group(2) or "Enhancement").strip()
            bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
            return {"value": value, "bonus_type": bonus_type, "stat": "Deadly"}

    # {{Fortification|100}} or {{Fortification|heavy}}
    match = _FORTIFICATION_TEMPLATE_RE.search(text)
    if match:
        value = _parse_int(match.group(1))
        if value is not None:
            raw_bonus_type = (match.group(2) or "Enhancement").strip()
            bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
            return {"value": value, "bonus_type": bonus_type, "stat": "Fortification"}

    # {{Save|r|11}} or {{Save|Will|3|Insight}}
    match = _SAVE_TEMPLATE_RE.search(text)
    if match:
        save_abbr = match.group(1).strip().lower()
        value = _parse_int(match.group(2))
        if value is not None:
            raw_bonus_type = (match.group(3) or "Resistance").strip()
            bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
            stat = _SAVE_ABBREVS.get(save_abbr, f"{save_abbr} Save")
            return {"value": value, "bonus_type": bonus_type, "stat": stat}

    # {{Skills|intim|3}} or {{Skills|Command|5|Insight}}
    match = _SKILLS_TEMPLATE_RE.search(text)
    if match:
        raw_skill = match.group(1).strip()
        raw_value = match.group(2)
        if raw_value:
            value = _parse_int(raw_value)
            if value is not None:
                raw_bonus_type = (match.group(3) or "Enhancement").strip()
                bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
                stat = _SKILL_ABBREVS.get(raw_skill.lower(), raw_skill.title())
                return {"value": value, "bonus_type": bonus_type, "stat": stat}

    # Simple numeric templates: {{Accuracy|7}}, {{Deception|3}}, {{Speed|30}}, etc.
    match = _SIMPLE_NUMERIC_RE.search(text)
    if match:
        raw_stat = match.group(1).strip()
        value = _parse_int(match.group(2))
        if value is not None:
            raw_bonus_type = (match.group(3) or "Enhancement").strip()
            bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
            stat = _SIMPLE_STAT_NAMES.get(raw_stat.lower(), raw_stat)
            return {"value": value, "bonus_type": bonus_type, "stat": stat}

    # {{Elemental Resistance|Acid|30}} or {{Elemental Resistance|Electric|5|Insight}}
    match = _ELEMENTAL_RESIST_RE.search(text)
    if match:
        raw_element = match.group(1).strip()
        value = _parse_int(match.group(2))
        if value is not None:
            element = _ELEMENT_ALIASES.get(raw_element.lower(), raw_element)
            raw_bonus_type = (match.group(3) or "Enhancement").strip()
            bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
            return {"value": value, "bonus_type": bonus_type, "stat": f"{element} Resistance"}

    # {{Absorption|Fire|26}}
    match = _ABSORPTION_RE.search(text)
    if match:
        raw_element = match.group(1).strip()
        value = _parse_int(match.group(2))
        if value is not None:
            element = _ELEMENT_ALIASES.get(raw_element.lower(), raw_element)
            return {"value": value, "bonus_type": "Enhancement", "stat": f"{element} Absorption"}

    # {{Spell Focus|Abjuration|3}} or {{Spell Focus|Mastery|+2|Quality}}
    match = _SPELL_FOCUS_RE.search(text)
    if match:
        school = match.group(1).strip()
        value = _parse_int(match.group(2))
        if value is not None:
            raw_bonus_type = (match.group(3) or "Enhancement").strip()
            bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
            school_lower = school.lower()
            if school_lower == "mastery":
                stat = "Spell Focus Mastery"
            elif school_lower == "spell":
                stat = "Universal Spell Focus"
            elif "mastery" in school_lower:
                stat = school
            else:
                stat = f"{school} Spell Focus"
            return {"value": value, "bonus_type": bonus_type, "stat": stat}

    # {{Spelllore|Fire|III}} → Fire Spell Lore +3
    match = re.search(r"\{\{Spelllore\|([^|}]+)\|([^|}]+)", text, re.IGNORECASE)
    if match:
        raw_school = match.group(1).strip()
        value = _parse_int(match.group(2))
        if value is not None:
            # Named lore → element-based lore
            _LORE_NAMES: dict[str, str] = {
                "silver flame": "Light",
                "frozen depths": "Cold",
                "firestorm": "Fire",
                "flames of purity": "Light",
                "blighted": "Acid",
                "creeping dust": "Acid",
                "frozen storm": "Cold",
                "thunderstorm": "Electric",
                "dark restoration": "Negative",
                "sacred ground": "Positive",
            }
            school_lower = raw_school.lower()
            mapped = _LORE_NAMES.get(school_lower)
            if mapped:
                stat = f"{mapped} Spell Lore"
            else:
                school = _ELEMENT_ALIASES.get(school_lower, raw_school)
                if school.lower() in ("spell", "universal", "universal spell"):
                    stat = "Universal Spell Lore"
                else:
                    stat = f"{school} Spell Lore"
            return {"value": value, "bonus_type": "Enhancement", "stat": stat}

    # {{Tactics|Combat Mastery|6|Insight}} → Combat Mastery +6
    match = re.search(r"\{\{Tactics\|([^|}]+)\|([^|}]+)(?:\|([^|}]+))?", text, re.IGNORECASE)
    if match:
        tactic = match.group(1).strip()
        value = _parse_int(match.group(2))
        if value is not None:
            raw_bonus_type = (match.group(3) or "Enhancement").strip()
            bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
            return {"value": value, "bonus_type": bonus_type, "stat": tactic}

    # {{Spell Power|Devotion|80}} (space in name, variant of SpellPower)
    match = re.search(r"\{\{Spell Power\|([^|}]+)\|([^|}]+)(?:\|([^|}]+))?", text, re.IGNORECASE)
    if match:
        sp_name = match.group(1).strip()
        value = _parse_int(match.group(2))
        if value is not None:
            raw_bonus_type = (match.group(3) or "Enhancement").strip()
            bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
            stat = _SPELLPOWER_STATS.get(sp_name, f"{sp_name} Spell Power")
            return {"value": value, "bonus_type": bonus_type, "stat": stat}

    # {{Hp|Vitality|25}} (hit point bonus with numeric value)
    match = _HP_TEMPLATE_RE.search(text)
    if match:
        value = _parse_int(match.group(1))
        if value is not None:
            return {"value": value, "bonus_type": "Enhancement", "stat": "Hit Points"}

    # {{HealingAmp|53|R}} or {{HealingAmp|17|h|Competence}} or {{HealingAmp|27||Competence}}
    match = _HEALINGAMP_RE.search(text)
    if match:
        value = _parse_int(match.group(1))
        if value is not None:
            amp_type = (match.group(2) or "h").strip().lower()
            raw_bonus_type = (match.group(3) or "Enhancement").strip()
            bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
            stat = "Repair Amplification" if amp_type == "r" else "Healing Amplification"
            return {"value": value, "bonus_type": bonus_type, "stat": stat}

    # Unwrap nested {{InlineWht|dark=y|{{HELstats|...}} text}} → {{HELstats|...}} text
    if "InlineWht" in text and "HELstats" in text:
        inner = re.search(r"\{\{InlineWht\|[^|]*\|(.*)\}\}", text, re.IGNORECASE)
        if inner:
            text = inner.group(1).strip()

    # {{HELstats|+5|L=+15}} Profane bonus to Melee and Ranged Power
    # Also handles: "Text before {{HELstats|...}} text after"
    # Extract highest tier value and parse the surrounding text for bonus_type + stat
    hel_match = re.search(
        r"(.*?)\{\{HELstats\|([^}]+)\}\}\s*(.*)", text, re.IGNORECASE
    )
    if hel_match:
        prefix = hel_match.group(1).strip()
        hel_params = hel_match.group(2)
        rest = hel_match.group(3).strip()
        # Combine prefix + rest for stat extraction
        # "Your MRR cap is raised by" + "" → use prefix
        # "" + "Profane bonus to Melee Power" → use rest
        if not rest and prefix:
            rest = prefix
        # Parse HEL values — take highest available (L > E > H)
        value = None
        for param in reversed(hel_params.split("|")):
            param = param.strip()
            # Named: L=+25, E=+10, H=+5
            if "=" in param:
                _, v = param.split("=", 1)
                v = _parse_int(v.strip())
            else:
                v = _parse_int(param)
            if v is not None:
                value = v
                break
        if value is not None and rest:
            # Strip wiki links from rest text
            rest = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", rest)
            # Strip '''bold notes''' and everything after them (Bug:, Note:, etc.)
            rest = re.sub(r"'''.*", "", rest)
            rest = rest.replace("''", "")
            rest = rest.strip()
            # Parse "Profane bonus to Melee and Ranged Power"
            # Also handles "Quality bonus bonus to Strength" (double "bonus")
            bt_stat_match = re.match(
                r"(\w+(?:\s+bonus)?)\s+[Bb]onus\s+to\s+(.*)", rest
            )
            if bt_stat_match:
                raw_bonus_type = bt_stat_match.group(1).strip()
                stat = bt_stat_match.group(2).strip()
                # Clean wiki markup from stat
                stat = re.sub(r"\[\[[^\]]*\|([^\]]+)\]\]", r"\1", stat)
                stat = re.sub(r"\[\[([^\]]+)\]\]", r"\1", stat)
                stat = re.sub(r"'''.*", "", stat)  # strip '''Bug:''' and everything after
                stat = re.sub(r"\s*''.*", "", stat)  # strip italic notes
                stat = re.sub(r"\s*\(.*?\)\s*$", "", stat)  # strip trailing (notes)
                stat = re.sub(r"\}\}+$", "", stat)  # strip trailing }}
                stat = re.sub(r"\{\{[^}]*$", "", stat)  # strip incomplete templates
                stat = stat.strip().rstrip(".")
                bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
                return {"value": value, "bonus_type": bonus_type, "stat": stat}
            # No "bonus to" — might be just a stat name (e.g., "Magical Resistance Rating Cap")
            stat = rest.strip()
            stat = re.sub(r"\[\[[^\]]*\|([^\]]+)\]\]", r"\1", stat)
            stat = re.sub(r"\[\[([^\]]+)\]\]", r"\1", stat)
            stat = re.sub(r"'''.*", "", stat)
            stat = re.sub(r"\s*\(.*?\)\s*$", "", stat)
            stat = stat.strip().rstrip(".")
            # Reject non-stat text (proc descriptions, narrative)
            _NON_STAT_WORDS = {"times", "seconds", "chance", "when", "each", "stack", "cast", "struck"}
            if stat and not any(w in stat.lower().split() for w in _NON_STAT_WORDS):
                return {"value": value, "bonus_type": "Enhancement", "stat": stat}

    # {{InlineWht|dark=y|+15% Legendary bonus to Universal Spell Critical Damage}}
    inline_match = re.search(
        r"\{\{InlineWht\|[^|]*\|([^}]+)\}\}", text, re.IGNORECASE
    )
    if inline_match:
        inner = inline_match.group(1).strip()
        # Parse "+15% Legendary bonus to ..."
        pct_match = re.match(r"[+]?(\d+)%?\s+(\w+)\s+[Bb]onus\s+to\s+(.*)", inner)
        if pct_match:
            value = int(pct_match.group(1))
            raw_bonus_type = pct_match.group(2).strip()
            stat = pct_match.group(3).strip()
            bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
            return {"value": value, "bonus_type": bonus_type, "stat": stat}

    # Fallback: plain text "+7 Enhancement bonus to Strength" or "+15% Artifact bonus to X"
    match = _ENCHANTMENT_RE.match(text)
    if match:
        value = int(match.group(1))
        raw_bonus_type = match.group(2).strip()
        stat = match.group(3).strip()
        bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
        return {"value": value, "bonus_type": bonus_type, "stat": stat}

    # Extended: handles +N% and "Bonus" (capital B) — "bonus to stat"
    pct_bonus = re.match(
        r"[+-]?(\d+)%?\s+(\w+)\s+[Bb]onus\s+to\s+(.+)",
        text, re.IGNORECASE,
    )
    if pct_bonus:
        value = int(pct_bonus.group(1))
        raw_bonus_type = pct_bonus.group(2).strip()
        stat = pct_bonus.group(3).strip().rstrip(".")
        stat = re.sub(r"\s*\(.*?\)\s*$", "", stat)  # strip trailing (notes)
        bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
        return {"value": value, "bonus_type": bonus_type, "stat": stat}

    # "+3 Insight Natural Armor Bonus" — bonus_type + stat + trailing "Bonus"
    trailing_bonus = re.match(
        r"[+-]?(\d+)%?\s+(\w+)\s+(.+?)\s+[Bb]onus$",
        text, re.IGNORECASE,
    )
    if trailing_bonus:
        value = int(trailing_bonus.group(1))
        raw_bonus_type = trailing_bonus.group(2).strip()
        stat = trailing_bonus.group(3).strip()
        bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
        return {"value": value, "bonus_type": bonus_type, "stat": stat}

    # "+30 Bonus to MRR Cap" — generic "Bonus to" without named type
    generic_bonus = re.match(
        r"[+-]?(\d+)%?\s+[Bb]onus\s+to\s+(.+)",
        text, re.IGNORECASE,
    )
    if generic_bonus:
        value = int(generic_bonus.group(1))
        stat = generic_bonus.group(2).strip().rstrip(".")
        return {"value": value, "bonus_type": "Enhancement", "stat": stat}

    # "-10% Enhancement discount to Spell Point Cost" → negative bonus
    discount = re.match(
        r"-(\d+)%?\s+(\w+)\s+discount\s+to\s+(.+)",
        text, re.IGNORECASE,
    )
    if discount:
        value = int(discount.group(1))
        raw_bonus_type = discount.group(2).strip()
        stat = discount.group(3).strip().rstrip(".")
        bonus_type = _BONUS_TYPE_ALIASES.get(raw_bonus_type, raw_bonus_type)
        return {"value": value, "bonus_type": bonus_type, "stat": f"{stat} Reduction"}

    # Last resort: "+N Stat" without "bonus to" — MUST start with + or -
    simple = re.match(r"[+-](\d+)%?\s+(.+)", text)
    if simple:
        value = int(simple.group(1))
        rest = simple.group(2).strip()
        # Try to extract bonus type from first word — ONLY if it's a known type
        words = rest.split()
        if len(words) >= 2 and words[0] in _BONUS_TYPE_ALIASES:
            bonus_type = _BONUS_TYPE_ALIASES[words[0]]
            stat = " ".join(words[1:]).strip().rstrip(".")
        else:
            bonus_type = "Enhancement"
            stat = rest.strip().rstrip(".")
        # Clean trailing parentheticals like "(all tier)"
        stat = re.sub(r"\s*\(.*?\)\s*$", "", stat).strip()
        if stat:
            return {"value": value, "bonus_type": bonus_type, "stat": stat}

    return None


# ---------------------------------------------------------------------------
# Stat name normalization and composite splitting
# ---------------------------------------------------------------------------

_SPELL_ELEMENTS = [
    "Fire", "Cold", "Electric", "Acid", "Sonic", "Light",
    "Negative", "Positive", "Force", "Repair", "Poison",
]
_ELEMENTAL_ELEMENTS = ["Fire", "Cold", "Electric", "Acid"]
_ALIGNMENT_ELEMENTS = ["Good", "Evil", "Law", "Chaos"]

_ALL_SPELL_POWERS = [f"{e} Spell Power" for e in _SPELL_ELEMENTS]
_ALL_SPELL_LORE = [f"{e} Spell Lore" for e in _SPELL_ELEMENTS]
_ALL_SPELL_SCHOOLS = [
    "Abjuration Spell Focus", "Conjuration Spell Focus",
    "Divination Spell Focus", "Enchantment Spell Focus",
    "Evocation Spell Focus", "Illusion Spell Focus",
    "Necromancy Spell Focus", "Transmutation Spell Focus",
]
_ALL_ABSORPTIONS = [f"{e} Absorption" for e in _SPELL_ELEMENTS]
_ALL_RESISTANCES = [f"{e} Resistance" for e in _SPELL_ELEMENTS]
_ELEMENTAL_ABSORPTIONS = [f"{e} Absorption" for e in _ELEMENTAL_ELEMENTS]
_ELEMENTAL_RESISTANCES = [f"{e} Resistance" for e in _ELEMENTAL_ELEMENTS]
_ALIGNMENT_ABSORPTIONS = [f"{e} Absorption" for e in _ALIGNMENT_ELEMENTS]
_ALIGNMENT_SPELL_POWERS = [f"{e} Spell Power" for e in _ALIGNMENT_ELEMENTS]
_ALIGNMENT_SPELL_LORE = [f"{e} Spell Lore" for e in _ALIGNMENT_ELEMENTS]

# Direct name aliases (lowercase key -> canonical name)
_STAT_ALIASES: dict[str, str] = {
    "ac": "Armor Class",
    "hp": "Hit Points",
    "sp": "Spell Points",
    "mr": "Magical Resistance Rating",
    "prr": "Physical Resistance Rating",
    "mrr": "Magical Resistance Rating",
    "maximum hitpoints": "Hit Points",
    "maximum hit points": "Hit Points",
    "hit points": "Hit Points",
    "universal spellpower": "Universal Spell Power",
    "spell dcs": "Spell DCs",
    "hit and damage": "Melee Power",
    "imbue dice": "Imbue Dice",
    "imbue dice.": "Imbue Dice",
    "sneak attack dice": "Sneak Attack Dice",
    "sneak attack": "Sneak Attack",
    "sneak attack damage": "Sneak Attack Damage",
    "fortification bypass": "Fortification Bypass",
    "spell penetration": "Spell Penetration",
    "spell critical chance": "Universal Spell Lore",
    "universal spell critical chance": "Universal Spell Lore",
    "universal spell critical damage": "Universal Spell Critical Damage",
    "spell critical damage": "Spell Critical Damage",
    "natural armor": "Natural Armor",
    "natural armor bonus": "Natural Armor",
    "armor class": "Armor Class",
    "critical range": "Critical Threat Range",
    "attack speed": "Attack Speed",
    "movement speed": "Movement Speed",
    "maximum spellpoints": "Maximum Spell Points",
    "maximum spell points": "Maximum Spell Points",
    # Set bonus common aliases
    "mrr cap": "Magical Resistance Rating Cap",
    "magical resistance rating cap": "Magical Resistance Rating Cap",
    "prr and mrr": "Physical and Magical Resistance Rating",
    "negative amplification": "Negative Healing Amplification",
    "positive amplification": "Positive Healing Amplification",
    "repair amplification": "Repair Amplification",
    "threat generation": "Threat Generation",
    "melee threat generation": "Melee Threat Generation",
    "threat reduction": "Threat Reduction",
    "threat reduction from all sources": "Threat Reduction",
    "threat from melee attacks": "Melee Threat Generation",
    "threat generation with melee attacks": "Melee Threat Generation",
    "melee threat reduction": "Threat Reduction",
    "threat decrease with both melee and ranged attacks": "Melee and Ranged Threat Reduction",
    "all spell dcs": "Spell DCs",
    "all tactical dcs": "Tactics",
    # "all tactical dcs and assassinate" handled as composite below
    "tactical feat dcs": "Tactics",
    "tactical abilities": "Tactics",
    "your tactical abilities": "Tactics",
    "all saving throws": "Saving Throws",
    "missile deflection": "Missile Deflection",
    "offhand strike chance": "Offhand Strike Chance",
    # "strike chance" removed — parser now keeps "Offhand" as part of stat name
    "strikethrough chance": "Strikethrough",
    "critical multiplier on a roll of 19-20": "Critical Multiplier (19-20)",
    "critical multiplier on a 19-20": "Critical Multiplier (19-20)",
    "critical damage": "Critical Damage",
    "shield armor class": "Shield Armor Class",
    "rune arm dcs": "Rune Arm DC",
    "assassinate dcs": "Assassinate DC",
    "assassinate spell focus": "Assassinate DC",
    "evocation spell dcs": "Evocation Spell Focus",
    "evocation spell focus": "Evocation Spell Focus",
    "dodge cap": "Dodge Cap",
    "helplessness damage": "Helpless Damage",
    "damage vs. helpless opponents": "Helpless Damage",
    "damage vs the helpless": "Helpless Damage",
    "damage versus the helpless": "Helpless Damage",
    "damage vs. helpless": "Helpless Damage",
    # "attack and damage" handled as composite below
    "attack": "Attack Bonus",
    "damage": "Damage Bonus",
    "ability stats": "all ability scores",
    "all of your ability scores": "all ability scores",
    "to all ability scores": "all ability scores",
    # Bare "DCs" kept as-is — context-dependent (could be spell or tactical)
    "dcs ''(note: tactical dcs are not affected, only spell dcs)": "Spell DCs",
    "spell power": "Potency",
    "spell crit chance": "Spell Lore",  # generic, not specifically universal
    "quality bonus": "Quality",
    # Amplification variants
    # amplification composites handled in _COMPOSITE_STATS below
    # Conditional bonuses
    "hit and damage vs. evil creatures": "Attack and Damage vs Evil",
    "saves vs. evil creatures": "Saves vs Evil",
    "hit on sneak attack": "Sneak Attack Hit",
    "spell saves": "Spell Resistance",
    "additional damage to helpless targets": "Helpless Damage",
    "damage on sneak attack": "Sneak Attack Damage",
    "your magical resistance rating cap is raised by": "Magical Resistance Rating Cap",
    "your maximum hit points": "Hit Points",
    "your maximum spell points": "Maximum Spell Points",
    # Spellpower/Spellcrit single-element variants (no space)
    "fire spellcrit chance": "Fire Spell Lore",
    "cold spellcrit chance": "Cold Spell Lore",
    "electric spellcrit chance": "Electric Spell Lore",
    "acid spellcrit chance": "Acid Spell Lore",
    "sonic spellcrit chance": "Sonic Spell Lore",
    "light spellcrit chance": "Light Spell Lore",
    "negative spellcrit chance": "Negative Spell Lore",
    "positive spellcrit chance": "Positive Spell Lore",
    "force spellcrit chance": "Force Spell Lore",
    "repair spellcrit chance": "Repair Spell Lore",
    "negative spell crit chance": "Negative Spell Lore",
    "acid spell crit chance": "Acid Spell Lore",
    "cold spell crit chance": "Cold Spell Lore",
    "electric spell crit chance": "Electric Spell Lore",
    "sonic spell crit chance": "Sonic Spell Lore",
    "light spell crit chance": "Light Spell Lore",
    "force spell crit chance": "Force Spell Lore",
    "positive spell crit chance": "Positive Spell Lore",
    "fire spell crit chance": "Fire Spell Lore",
    "repair spell crit chance": "Repair Spell Lore",
    "fire spellpower": "Fire Spell Power",
    "cold spellpower": "Cold Spell Power",
    "electric spellpower": "Electric Spell Power",
    "acid spellpower": "Acid Spell Power",
    "sonic spellpower": "Sonic Spell Power",
    "light spellpower": "Light Spell Power",
    "negative spellpower": "Negative Spell Power",
    "positive spellpower": "Positive Spell Power",
    "force spellpower": "Force Spell Power",
    "repair spellpower": "Repair Spell Power",
}

# Composite stats → split into multiple individual stat names
_COMPOSITE_STATS: dict[str, list[str]] = {
    "sheltering": ["Physical Sheltering", "Magical Sheltering"],
    "saving throws": ["Fortitude Save", "Reflex Save", "Will Save"],
    "melee and ranged power": ["Melee Power", "Ranged Power"],
    "physical and magical resistance rating": [
        "Physical Resistance Rating", "Magical Resistance Rating",
    ],
    "positive and negative spell power": [
        "Positive Spell Power", "Negative Spell Power",
    ],
    "positive and negative healing amplification": [
        "Positive Healing Amplification", "Negative Healing Amplification",
    ],
    "doublestrike and doubleshot": ["Doublestrike", "Doubleshot"],
    "all ability scores": [
        "Strength", "Dexterity", "Constitution",
        "Intelligence", "Wisdom", "Charisma",
    ],
    "positive, negative, and repair healing amplification": [
        "Positive Healing Amplification", "Negative Healing Amplification",
        "Repair Amplification",
    ],
    "positive, negative, and repair amplification": [
        "Positive Healing Amplification", "Negative Healing Amplification",
        "Repair Amplification",
    ],
    "healing, repair, and negative amplification": [
        "Positive Healing Amplification", "Negative Healing Amplification",
        "Repair Amplification",
    ],
    "positive and negative amplification": [
        "Positive Healing Amplification", "Negative Healing Amplification",
    ],
    "melee, ranged, and universal spell power": [
        "Melee Power", "Ranged Power", "Universal Spell Power",
    ],
    # Elemental / Spell / Alignment composites
    "elemental absorption": _ELEMENTAL_ABSORPTIONS,
    "elemental resistance": _ELEMENTAL_RESISTANCES,
    "spell absorption": _ALL_ABSORPTIONS,
    "alignment absorption": _ALIGNMENT_ABSORPTIONS,
    # Multi-element spell power/lore/crit from specific sets
    "intelligence, wisdom, and charisma": ["Intelligence", "Wisdom", "Charisma"],
    "int/wis/cha": ["Intelligence", "Wisdom", "Charisma"],
    "melee power/ranged power": ["Melee Power", "Ranged Power"],
    "mrr/prr": ["Magical Resistance Rating", "Physical Resistance Rating"],
    # "spell saves" moved to _STAT_ALIASES
    "sneak attack and sneak attack damage": ["Sneak Attack Dice", "Sneak Attack Damage"],
    "all tactical dcs and assassinate": ["Tactics", "Assassinate DC"],
    "attack and damage": ["Attack Bonus", "Damage Bonus"],
    "parrying": ["Armor Class", "Fortitude Save", "Reflex Save", "Will Save"],
    "critical confirmation and critical damage": ["Critical Confirmation", "Critical Damage"],
    "positive and light/alignment spell power":
        ["Positive Spell Power", "Light Spell Power"] + _ALIGNMENT_SPELL_POWERS,
    "positive and light/alignment spell crit chance":
        ["Positive Spell Lore", "Light Spell Lore"] + _ALIGNMENT_SPELL_LORE,
    "positive and light/alignment spellcrit chance":
        ["Positive Spell Lore", "Light Spell Lore"] + _ALIGNMENT_SPELL_LORE,
    "light, alignment, and positive spellpower":
        ["Light Spell Power", "Positive Spell Power"] + _ALIGNMENT_SPELL_POWERS,
    "light, alignment, and positive spellcrit chance":
        ["Light Spell Lore", "Positive Spell Lore"] + _ALIGNMENT_SPELL_LORE,
    "fire, force, light and positive spell crit chance": [
        "Fire Spell Lore", "Force Spell Lore", "Light Spell Lore", "Positive Spell Lore",
    ],
    "negative, poison, and force spell crit chance": [
        "Negative Spell Lore", "Poison Spell Lore", "Force Spell Lore",
    ],
    "electric, fire, force, and repair spell crit chance": [
        "Electric Spell Lore", "Fire Spell Lore", "Force Spell Lore", "Repair Spell Lore",
    ],
    "fire, cold, acid, and electric spell crit chance": [
        "Fire Spell Lore", "Cold Spell Lore", "Acid Spell Lore", "Electric Spell Lore",
    ],
    "fire, cold, electric, and acid spellcrit chance": [
        "Fire Spell Lore", "Cold Spell Lore", "Electric Spell Lore", "Acid Spell Lore",
    ],
    # (light/alignment/positive spellcrit variants handled above with _ALIGNMENT_SPELL_LORE)
    "sonic, force, light, acid spell power": [
        "Sonic Spell Power", "Force Spell Power", "Light Spell Power", "Acid Spell Power",
    ],
    "sonic, force, light, acid spell crit chance": [
        "Sonic Spell Lore", "Force Spell Lore", "Light Spell Lore", "Acid Spell Lore",
    ],
    "fire, cold, electric, and acid spellpower": [
        "Fire Spell Power", "Cold Spell Power", "Electric Spell Power", "Acid Spell Power",
    ],
    "negative and poison spellcrit chance": [
        "Negative Spell Lore", "Acid Spell Lore",
    ],
    # (light/alignment/positive spellpower variant handled above with _ALIGNMENT_SPELL_POWERS)
    # "additional damage to helpless targets" moved to _STAT_ALIASES
    # Potency / Universal = split into all elements
    "potency": _ALL_SPELL_POWERS,
    # Universal SP/Lore/Focus are NOT split — they're unique bonus types
    # that stack additively with everything. Only Potency splits.
    # "universal spell power" — stays as single stat
    # "universal spell lore" — stays as single stat
    # "universal spell focus" — stays as single stat
    "spell lore": _ALL_SPELL_LORE,  # generic "Spell Lore" = Potency equivalent for lore
    "spell focus": _ALL_SPELL_SCHOOLS,  # generic "Spell Focus" = all schools
}


def normalize_stat_name(raw: str) -> list[str]:
    """Normalize a stat name and split composites into individual stat names.

    Returns a list of stat names (usually 1, but multiple for composites).

    Examples::

        normalize_stat_name("Will Saving Throws") -> ["Will Save"]
        normalize_stat_name("Sheltering") -> ["Physical Sheltering", "Magical Sheltering"]
        normalize_stat_name("Potency") -> ["Fire Spell Power", "Cold Spell Power", ...]
        normalize_stat_name("AC") -> ["Armor Class"]
    """
    s = raw.strip()

    # Strip trailing parentheticals and wiki notes
    s = re.sub(r"\s*\(.*?\)\s*$", "", s).strip()
    s = re.sub(r"\s*''.*$", "", s).strip()

    lower = s.lower()

    # Aliases first — resolve to canonical name (may recurse into composites)
    if lower in _STAT_ALIASES:
        resolved = _STAT_ALIASES[lower]
        if resolved.lower() != lower:
            return normalize_stat_name(resolved)
        return [resolved]

    # Save normalization: "Will Saving Throws" -> "Will Save"
    save_match = re.match(r"(Will|Reflex|Fortitude)\s+[Ss]av(?:ing\s+[Tt]hrows?|es?)", s, re.IGNORECASE)
    if save_match:
        return [f"{save_match.group(1).title()} Save"]

    # DC normalization: "Conjuration DCs" -> "Conjuration Spell Focus"
    dc_match = re.match(r"(?:To\s+)?(.+?)\s+DCs\.?$", s, re.IGNORECASE)
    if dc_match:
        return [f"{dc_match.group(1).title()} Spell Focus"]

    # Composite splits (exact match on lowercase)
    if lower in _COMPOSITE_STATS:
        return _COMPOSITE_STATS[lower]

    # Named set composite spell powers: "Power of the Silver Flame Spell Power"
    for sp_name, stat_list in COMPOSITE_SPELLPOWER.items():
        if lower == f"{sp_name} spell power".lower():
            return stat_list

    # Named set composite spell lore: "Silver Flame Spell Lore"
    for lore_name, stat_list in COMPOSITE_SPELLLORE.items():
        if lower == f"{lore_name} spell lore".lower():
            return stat_list

    # Comma-separated list: "Fire, Cold, Acid, and Electric Spell Critical Chance"
    comma_match = re.match(
        r"((?:\w+,\s*)+(?:and\s+)?\w+)\s+(Spell (?:Power|Crit(?:ical)? Chance|Lore)|"
        r"Spellcrit Chance|Spellpower|Absorption|Amplification|Resistance)", s,
    )
    if comma_match:
        elements_str = comma_match.group(1).strip()
        suffix = comma_match.group(2).strip()
        suffix = suffix.replace("Spellcrit Chance", "Spell Lore")
        suffix = suffix.replace("Spell Crit Chance", "Spell Lore")
        suffix = suffix.replace("Spell Critical Chance", "Spell Lore")
        suffix = suffix.replace("Spellpower", "Spell Power")
        elements = [e.strip().rstrip(",") for e in re.split(r",\s*(?:and\s+)?|\s+and\s+", elements_str)]
        elements = [e for e in elements if e]
        if elements:
            return [f"{e} {suffix}" for e in elements]

    # Generic "X and Y <suffix>"
    and_match = re.match(
        r"(.+?)\s+and\s+(.+?)"
        r"(\s+Spell (?:Power|Critical Damage|Lore|Crit Chance)"
        r"|\s+Spellcrit Chance|\s+Spellpower|\s+Resistance|\s+Amplification)?$",
        s,
    )
    if and_match:
        left = and_match.group(1).strip()
        right = and_match.group(2).strip()
        suffix = (and_match.group(3) or "").strip()
        if suffix:
            suffix = suffix.replace("Spellcrit Chance", "Spell Lore")
            suffix = suffix.replace("Spellpower", "Spell Power")
            return [f"{left} {suffix}", f"{right} {suffix}"]
        return [left, right]

    # Short element name: "Fire" -> "Fire Spell Power" (in enhancement context)
    _ELEMENT_STATS = {
        "fire", "cold", "electric", "acid", "sonic", "light",
        "positive", "negative", "force", "repair",
    }
    if lower in _ELEMENT_STATS:
        return [f"{s.title()} Spell Power"]

    # Resistance: "Resistance to Fire" -> "Fire Resistance"
    resist_match = re.match(r"Resistance to (\w+)", s, re.IGNORECASE)
    if resist_match:
        return [f"{resist_match.group(1).title()} Resistance"]

    # No transformation needed
    return [s]


def parse_enchantment_string_multi(text: str) -> list[dict]:
    """Parse enchantment text into structured bonus dicts, splitting composites.

    Returns a list of dicts with keys: value, bonus_type, stat.
    Composite stats (Potency, Sheltering, named spell powers) are
    split into individual element rows.
    Returns empty list if unparseable.
    """
    result = parse_enchantment_string(text)
    if result is None:
        return []

    # Normalize and split the stat name
    stat_names = normalize_stat_name(result["stat"])
    return [
        {"value": result["value"], "bonus_type": result["bonus_type"], "stat": s}
        for s in stat_names
    ]


# ---------------------------------------------------------------------------
# Effect template parser (weapon/armor effects → item_effects table)
# ---------------------------------------------------------------------------

# Templates that are metadata, not effects — they have dedicated columns/tables.
_METADATA_TEMPLATES: frozenset[str] = frozenset({
    "augment", "named item sets", "mat", "craftingeffects",
    "enhancement bonus", "enhancement_bonus",
    "moonsunaugment", "lamordia slot", "dino slot",
    "vaultsoftheartificersupgrade", "bind",
})


# Generic regex: {{Name}}, {{Name|p1}}, {{Name|p1|p2}}, etc.
_GENERIC_TEMPLATE_RE = re.compile(
    r"\{\{([^|}]+?)(?:\|([^}]*))?\}\}",
)


def parse_effect_template(text: str) -> dict | None:
    """Parse a wiki enchantment template as a weapon/armor effect.

    Returns a dict with keys: effect (str), modifier (str|None), value (int|None).
    Returns None if the template is metadata, a stat bonus, plain text, or
    not a recognized template.

    This function is the complement of ``parse_enchantment_string`` — it handles
    everything that isn't a numeric stat bonus or metadata.
    """
    text = text.strip()
    match = _GENERIC_TEMPLATE_RE.search(text)
    if not match:
        return None

    name = match.group(1).strip()
    params_raw = match.group(2) or ""

    # Skip metadata templates (already stored in dedicated columns/tables)
    name_lower = name.lower()
    if name_lower in _METADATA_TEMPLATES:
        return None

    # Parse parameters, filtering out wiki noise (nocat=TRUE, prefix=..., etc.)
    params = []
    for p in params_raw.split("|"):
        p = p.strip()
        if not p or "=" in p:
            continue
        params.append(p)

    # Determine modifier and value from params
    modifier: str | None = None
    value: int | None = None

    if len(params) == 0:
        # Simple flag: {{Vorpal}}, {{Keen}}, {{Ghostly}}
        pass
    elif len(params) == 1:
        # One param: could be a modifier or a numeric value
        if params[0].isdigit():
            value = int(params[0])
        else:
            modifier = params[0]
    elif len(params) >= 2:
        # Two+ params: first is modifier, look for numeric value in rest
        modifier = params[0]
        for p in params[1:]:
            if p.isdigit():
                value = int(p)
                break

    return {
        "effect": name,
        "modifier": modifier,
        "value": value,
    }


def is_metadata_template(text: str) -> bool:
    """Check if a template string is item metadata (augment slots, sets, etc.)."""
    text = text.strip()
    match = _GENERIC_TEMPLATE_RE.search(text)
    if not match:
        # Plain text like "Tier 1:", "Adds ..."
        lower = text.lower()
        return lower.startswith(("tier", "adds", "upgradeable", "one of", "none"))
    name_lower = match.group(1).strip().lower()
    return name_lower in _METADATA_TEMPLATES


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
