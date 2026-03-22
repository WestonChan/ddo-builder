"""Effect FID lookup tables for resolving stat names and bonus types.

Built via discriminant analysis: while effect template CONTENT is shared
across many items, the template FID is context-specific. Different stats
and bonus types reference different FIDs.

Each FID maps to a (stat_name, bonus_type) tuple. Built from wiki
cross-reference with 0 conflicts per FID.

Usage:
    result = EFFECT_FID_LOOKUP.get(effect_ref_fid)
    if result:
        stat, bonus_type = result
        # stat = "Strength", bonus_type = "Enhancement"
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Canonical name normalization
# ---------------------------------------------------------------------------

_STAT_NORMALIZE: dict[str, str] = {
    "str": "Strength", "STR": "Strength", "Strength": "Strength",
    "dex": "Dexterity", "DEX": "Dexterity", "Dexterity": "Dexterity",
    "con": "Constitution", "CON": "Constitution", "Constitution": "Constitution",
    "int": "Intelligence", "INT": "Intelligence", "Intelligence": "Intelligence",
    "wis": "Wisdom", "WIS": "Wisdom", "Wisdom": "Wisdom",
    "cha": "Charisma", "CHA": "Charisma", "Charisma": "Charisma",
}

_BT_NORMALIZE: dict[str, str] = {
    "Enhancement": "Enhancement",
    "Insightful": "Insight", "Insight": "Insight",
    "Quality": "Quality",
    "Profane": "Profane", "Sacred": "Sacred",
    "Exceptional": "Exceptional",
    "Competence": "Competence",
    "Luck": "Luck", "Artifact": "Artifact",
    "Festive": "Festive", "Morale": "Morale",
    "Alchemical": "Alchemical", "Resistance": "Resistance",
}


def _n(stat: str, bt: str) -> tuple[str, str]:
    """Normalize a (stat, bonus_type) pair to canonical names."""
    return (_STAT_NORMALIZE.get(stat, stat), _BT_NORMALIZE.get(bt, bt))


# ---------------------------------------------------------------------------
# Collapsed FID -> (stat, bonus_type) lookup
# 97 stat entries + 106 bonus_type entries -> merged into one map.
# Built from 1,088 wiki-matched items via primary effect_ref slot.
# Each entry has 0 conflicts for both stat and bonus_type.
# ---------------------------------------------------------------------------

EFFECT_FID_LOOKUP: dict[int, tuple[str, str]] = {
    # Enhancement ability scores
    0x70000A12: _n("CHA", "Enhancement"),
    0x70000A1A: _n("Con", "Enhancement"),
    0x70000A23: _n("Intelligence", "Enhancement"),
    0x70000EA5: _n("CON", "Enhancement"),
    0x70002024: _n("INT", "Enhancement"),
    0x700021CB: _n("Charisma", "Enhancement"),
    0x700025B5: _n("DEX", "Enhancement"),
    0x700025CD: _n("DEX", "Enhancement"),
    0x7000265D: _n("CON", "Enhancement"),
    0x700026B8: _n("CON", "Enhancement"),
    0x70002A03: _n("CON", "Enhancement"),
    0x7000407C: _n("WIS", "Enhancement"),
    0x70004250: _n("Intelligence", "Enhancement"),
    0x700048C5: _n("INT", "Enhancement"),
    0x70005275: _n("CON", "Enhancement"),
    0x7000541B: _n("Wisdom", "Enhancement"),
    0x70005622: _n("STR", "Enhancement"),
    0x70005F35: _n("CON", "Enhancement"),
    0x70005F90: _n("DEX", "Enhancement"),
    0x70006050: _n("CHA", "Enhancement"),
    0x700060DF: _n("CON", "Enhancement"),
    0x70006499: _n("STR", "Enhancement"),
    0x700064F4: _n("INT", "Enhancement"),
    0x70006EE5: _n("CON", "Enhancement"),
    0x7000719F: _n("INT", "Enhancement"),
    0x700091A8: _n("wis", "Enhancement"),
    0x7000EA38: _n("DEX", "Enhancement"),
    0x7000EF5F: _n("INT", "Enhancement"),
    0x7001A370: _n("STR", "Enhancement"),
    0x7001B236: _n("CON", "Enhancement"),
    0x7001BF43: _n("STR", "Enhancement"),
    0x70023DBD: _n("Strength", "Enhancement"),
    0x70023E29: _n("dex", "Enhancement"),
    0x70023E35: _n("Wisdom", "Enhancement"),
    0x70023E3E: _n("STR", "Enhancement"),
    0x70023E3F: _n("CON", "Enhancement"),
    0x70023E44: _n("INT", "Enhancement"),
    0x70023E46: _n("INT", "Enhancement"),
    0x70023E47: _n("STR", "Enhancement"),
    0x70023E4A: _n("Charisma", "Enhancement"),
    0x70023E4D: _n("dex", "Enhancement"),
    0x70023E4F: _n("Wisdom", "Enhancement"),
    0x70023E51: _n("CHA", "Enhancement"),
    0x70023E54: _n("STR", "Enhancement"),
    0x70023E57: _n("WIS", "Enhancement"),
    0x70023E5A: _n("CON", "Enhancement"),
    0x70025280: _n("Strength", "Enhancement"),
    0x70025283: _n("str", "Enhancement"),
    0x7002528D: _n("Cha", "Enhancement"),
    0x7002528E: _n("WIS", "Enhancement"),
    0x70025290: _n("str", "Enhancement"),
    0x700252D2: _n("Strength", "Enhancement"),
    0x700252D5: _n("Constitution", "Enhancement"),
    0x700252D7: _n("Intelligence", "Enhancement"),
    0x700252DB: _n("Wisdom", "Enhancement"),
    0x700252DF: _n("Charisma", "Enhancement"),
    # Insightful ability scores
    0x7001AE2C: _n("INT", "Insightful"),
    0x7001AE39: _n("CON", "Insightful"),
    0x7001AE3B: _n("WIS", "Insightful"),
    0x7001AE3F: _n("STR", "Insightful"),
    0x7001AE47: _n("DEX", "Insightful"),
    0x7001AE49: _n("STR", "Insightful"),
    0x7001AE55: _n("DEX", "Insightful"),
    0x7001AE5F: _n("WIS", "Insightful"),
    0x7001AE60: _n("WIS", "Insightful"),
    0x7001AE65: _n("CHA", "Insightful"),
    0x7001AE67: _n("CHA", "Insightful"),
    0x7001AE6A: _n("INT", "Insightful"),
    0x7001AE6B: _n("CHA", "Insightful"),
    0x7001AE71: _n("DEX", "Insightful"),
    0x7001AE7C: _n("CHA", "Insightful"),
    0x70025286: _n("CON", "Insightful"),
    0x70025289: _n("INT", "Insightful"),
    # Quality ability scores
    0x7001C83F: _n("dex", "Quality"),
    0x7001C8D2: _n("WIS", "Quality"),
    0x7001C8D5: _n("CON", "Quality"),
    0x7001D0FA: _n("INT", "Quality"),
    0x7001D0FB: _n("CON", "Quality"),
    0x70025287: _n("CON", "Quality"),
    0x7002528A: _n("INT", "Quality"),
    0x7002869C: _n("Dexterity", "Quality"),
    0x700286A0: _n("Dexterity", "Quality"),
    0x700286A2: _n("Dexterity", "Quality"),
    # Insightful ability scores (alternate FID range)
    0x70027C8F: _n("Strength", "Insightful"),
    0x70027C94: _n("Constitution", "Insightful"),
    0x70027C96: _n("Intelligence", "Insightful"),
    0x70027C9A: _n("Wisdom", "Insightful"),
    0x70027C9E: _n("Charisma", "Insightful"),
    # Exceptional ability scores
    0x70029352: _n("Strength", "Exceptional"),
    0x70029355: _n("Strength", "Exceptional"),
    0x7002935B: _n("Constitution", "Exceptional"),
    0x7002935E: _n("Constitution", "Exceptional"),
    0x70029362: _n("Intelligence", "Exceptional"),
    0x70029365: _n("Intelligence", "Exceptional"),
    0x70029367: _n("Constitution", "Exceptional"),
    0x7002936A: _n("Constitution", "Exceptional"),
    0x7002936C: _n("Wisdom", "Exceptional"),
    0x7002936E: _n("Constitution", "Exceptional"),
    0x7002936F: _n("Wisdom", "Exceptional"),
    0x70029373: _n("Charisma", "Exceptional"),
    0x70029376: _n("Charisma", "Exceptional"),
}
"""Maps effect_ref FID -> (canonical_stat_name, canonical_bonus_type).

Example: EFFECT_FID_LOOKUP[0x70002A03] == ("Constitution", "Enhancement")
"""
