"""Static crafting data for systems whose wiki pages are guide-format.

These systems have complex tier trees that don't parse well from wikitext.
Data sourced from ddowiki.com pages (March 2026).
"""

from __future__ import annotations

from ddo_data.enums import CraftingSystem

_GS = CraftingSystem.GREEN_STEEL.id
_LGS = CraftingSystem.LEGENDARY_GREEN_STEEL.id
_TF = CraftingSystem.THUNDER_FORGED.id
_DINO = CraftingSystem.DINOSAUR_BONE.id

# ---------------------------------------------------------------------------
# Green Steel (Heroic) — 6 elements x 3 tiers, weapons + accessories
# Source: ddowiki.com/page/Green_Steel_items
# ---------------------------------------------------------------------------

GREEN_STEEL_OPTIONS: list[dict] = [
    # --- Tier 1: Altar of Invasion ---
    # Weapons
    {"system_id": _GS, "tier": "Tier 1 Weapon", "name": "Air",
     "description": "Shocking Burst; Lightning Strike on critical hit"},
    {"system_id": _GS, "tier": "Tier 1 Weapon", "name": "Earth",
     "description": "Acid Burst; Earthgrab on critical hit"},
    {"system_id": _GS, "tier": "Tier 1 Weapon", "name": "Fire",
     "description": "Flaming Burst; Incineration on critical hit"},
    {"system_id": _GS, "tier": "Tier 1 Weapon", "name": "Water",
     "description": "Icy Burst; Crushing Wave on critical hit"},
    {"system_id": _GS, "tier": "Tier 1 Weapon", "name": "Positive",
     "description": "Holy; Good Burst damage"},
    {"system_id": _GS, "tier": "Tier 1 Weapon", "name": "Negative",
     "description": "Unholy; Evil Burst damage; Enervation on critical hit"},
    # Accessories
    {"system_id": _GS, "tier": "Tier 1 Accessory", "name": "Air - Concordant Opposition",
     "description": "+45 Spell Points; Haste clickie 3/rest"},
    {"system_id": _GS, "tier": "Tier 1 Accessory", "name": "Earth - HP",
     "description": "Greater Elemental Energy (+20 HP); Stoneskin Guard"},
    {"system_id": _GS, "tier": "Tier 1 Accessory", "name": "Fire - Spell Power",
     "description": "Combustion +72; Fire Shield (Warm) clickie"},
    {"system_id": _GS, "tier": "Tier 1 Accessory", "name": "Water - Spell Power",
     "description": "Glaciation +72; Fire Shield (Cold) clickie"},
    {"system_id": _GS, "tier": "Tier 1 Accessory", "name": "Positive - HP/Mana",
     "description": "Greater Elemental Energy (+20 HP); Raise Dead clickie"},
    {"system_id": _GS, "tier": "Tier 1 Accessory", "name": "Negative - Mana",
     "description": "Wizardry VI (+150 SP); Enervation Guard"},

    # --- Tier 2: Altar of Subjugation ---
    {"system_id": _GS, "tier": "Tier 2 Weapon", "name": "Air",
     "description": "Shocking Blast; +10 Stunning DC; Heightened Awareness IV"},
    {"system_id": _GS, "tier": "Tier 2 Weapon", "name": "Earth",
     "description": "Acid Blast; Greater Stone Prison; +2 Exceptional Strength"},
    {"system_id": _GS, "tier": "Tier 2 Weapon", "name": "Fire",
     "description": "Flaming Blast; Seeker +10; Blinding Embers on critical hit"},
    {"system_id": _GS, "tier": "Tier 2 Weapon", "name": "Water",
     "description": "Icy Blast; Freezing Ice on critical hit; +2 Exceptional Constitution"},
    {"system_id": _GS, "tier": "Tier 2 Weapon", "name": "Positive",
     "description": "Good Blast; +6 Enhancement to Wisdom; +10 Diplomacy"},
    {"system_id": _GS, "tier": "Tier 2 Weapon", "name": "Negative",
     "description": "Evil Blast; +6 Enhancement to Intelligence; +10 Haggle"},
    {"system_id": _GS, "tier": "Tier 2 Accessory", "name": "Air",
     "description": "+3 Resistance bonus to saves; +11 Balance; Haste Guard"},
    {"system_id": _GS, "tier": "Tier 2 Accessory", "name": "Earth",
     "description": "Heavy Fortification; Protection +5; Stoneskin Guard"},
    {"system_id": _GS, "tier": "Tier 2 Accessory", "name": "Fire",
     "description": "+30 Fire Resistance; +10 Intimidate; Fire Shield Guard"},
    {"system_id": _GS, "tier": "Tier 2 Accessory", "name": "Water",
     "description": "+30 Cold Resistance; +10 Concentration; Crushing Wave Guard"},
    {"system_id": _GS, "tier": "Tier 2 Accessory", "name": "Positive",
     "description": "+30 Healing Amplification; +4 Insight AC; +2 Exceptional stat"},
    {"system_id": _GS, "tier": "Tier 2 Accessory", "name": "Negative",
     "description": "+6 Enhancement Charisma; Deathblock; Enervation Guard"},

    # --- Tier 3: Altar of Devastation ---
    # Weapons (double-shard combinations)
    {"system_id": _GS, "tier": "Tier 3 Weapon", "name": "Lightning II (Air+Air)",
     "description": "Lightning Strike: massive electric damage on critical hit; Shocking Burst + Blast"},
    {"system_id": _GS, "tier": "Tier 3 Weapon", "name": "Fire II (Fire+Fire)",
     "description": "Incineration: fire damage over time on hit; 2x proc rate; Flaming Burst + Blast"},
    {"system_id": _GS, "tier": "Tier 3 Weapon", "name": "Mineral II (Earth+Positive)",
     "description": "Metalline + Good: bypasses all material and alignment DR"},
    {"system_id": _GS, "tier": "Tier 3 Weapon", "name": "Ice II (Water+Water)",
     "description": "Crushing Wave: cold + bludgeoning damage over time; Icy Burst + Blast"},
    {"system_id": _GS, "tier": "Tier 3 Weapon", "name": "Pos+Pos",
     "description": "Holy Burst; Greater Disruption; +2d6 Good damage"},
    {"system_id": _GS, "tier": "Tier 3 Weapon", "name": "Neg+Neg",
     "description": "Unholy Burst; Greater Vampirism; +2d6 Evil damage"},
    # Accessories
    {"system_id": _GS, "tier": "Tier 3 Accessory", "name": "HP Build (Earth+Earth)",
     "description": "20% Blur permanent; Displacement clickie 2/rest; Heavy Fortification"},
    {"system_id": _GS, "tier": "Tier 3 Accessory", "name": "Mana Build (Air+Air)",
     "description": "Wizardry VI (+150 SP); Haste clickie; Concordant Opposition"},
    {"system_id": _GS, "tier": "Tier 3 Accessory", "name": "Immunity (Pos+Neg)",
     "description": "Deathblock; Blindness Immunity; Fear Immunity; Disease/Poison Immunity"},
    {"system_id": _GS, "tier": "Tier 3 Accessory", "name": "Healing (Pos+Pos)",
     "description": "+30% Healing Amplification; Raise Dead clickie; Regeneration"},
]


# ---------------------------------------------------------------------------
# Legendary Green Steel — augment-based system
# Source: ddowiki.com/page/Legendary_Green_Steel_items
# ---------------------------------------------------------------------------

LGS_OPTIONS: list[dict] = [
    # Tier 1 — stat bonuses (Profane for HP/SP, Enhancement for others)
    {"system_id": _LGS, "tier": "Tier 1", "name": "Air - Dominion",
     "description": "+15 Enhancement Dexterity; +22 Competence Hide"},
    {"system_id": _LGS, "tier": "Tier 1", "name": "Air - Escalation",
     "description": "+15 Enhancement Dexterity; +22 Competence Move Silently"},
    {"system_id": _LGS, "tier": "Tier 1", "name": "Earth - Dominion",
     "description": "+15 Enhancement Constitution; +22 Competence Balance"},
    {"system_id": _LGS, "tier": "Tier 1", "name": "Fire - Dominion",
     "description": "+15 Enhancement Strength; +22 Competence Intimidate"},
    {"system_id": _LGS, "tier": "Tier 1", "name": "Water - Dominion",
     "description": "+15 Enhancement Wisdom; +22 Competence Concentration"},
    {"system_id": _LGS, "tier": "Tier 1", "name": "Positive - Dominion",
     "description": "+300 Profane Hit Points; +22 Competence Heal"},
    {"system_id": _LGS, "tier": "Tier 1", "name": "Negative - Dominion",
     "description": "+300 Profane Spell Points; +22 Competence Spellcraft"},

    # Tier 2 — secondary bonuses (Insight)
    {"system_id": _LGS, "tier": "Tier 2", "name": "Air",
     "description": "+7 Insight Dexterity; +11 Insight skill"},
    {"system_id": _LGS, "tier": "Tier 2", "name": "Earth",
     "description": "+7 Insight Constitution; +11 Insight skill"},
    {"system_id": _LGS, "tier": "Tier 2", "name": "Fire",
     "description": "+7 Insight Strength; +11 Insight skill"},
    {"system_id": _LGS, "tier": "Tier 2", "name": "Water",
     "description": "+7 Insight Wisdom; +11 Insight skill"},
    {"system_id": _LGS, "tier": "Tier 2", "name": "Positive",
     "description": "+150 Insight Hit Points; +11 Insight skill"},
    {"system_id": _LGS, "tier": "Tier 2", "name": "Negative",
     "description": "+150 Insight Spell Points; +11 Insight skill"},

    # Tier 3 — tertiary bonuses (Quality)
    {"system_id": _LGS, "tier": "Tier 3", "name": "Air",
     "description": "+2 Quality Dexterity; +6 Quality skill"},
    {"system_id": _LGS, "tier": "Tier 3", "name": "Earth",
     "description": "+2 Quality Constitution; +6 Quality skill"},
    {"system_id": _LGS, "tier": "Tier 3", "name": "Fire",
     "description": "+2 Quality Strength; +6 Quality skill"},
    {"system_id": _LGS, "tier": "Tier 3", "name": "Water",
     "description": "+2 Quality Wisdom; +6 Quality skill"},
    {"system_id": _LGS, "tier": "Tier 3", "name": "Positive",
     "description": "+50 Quality Hit Points; +6 Quality skill"},
    {"system_id": _LGS, "tier": "Tier 3", "name": "Negative",
     "description": "+50 Quality Spell Points; +6 Quality skill"},

    # Set bonuses
    {"system_id": _LGS, "tier": "Set Bonus", "name": "Dominion (2pc)",
     "description": "+200 Spell Points"},
    {"system_id": _LGS, "tier": "Set Bonus", "name": "Escalation (2pc)",
     "description": "+5% Dodge Cap"},
    {"system_id": _LGS, "tier": "Set Bonus", "name": "Opposition (2pc)",
     "description": "+200 Hit Points"},
    {"system_id": _LGS, "tier": "Set Bonus", "name": "Ethereal (4pc)",
     "description": "10% Incorporeal miss chance"},
    {"system_id": _LGS, "tier": "Set Bonus", "name": "Material (4pc)",
     "description": "+1 Critical Damage multiplier on 19-20"},
    {"system_id": _LGS, "tier": "Set Bonus", "name": "Controller's Grip (5pc)",
     "description": "5% chance on hit to Paralyze target for 6 seconds"},
    {"system_id": _LGS, "tier": "Set Bonus", "name": "Whispers of Life (5pc)",
     "description": "Healing aura: 1d4+10 positive energy every 6 seconds"},
]


# ---------------------------------------------------------------------------
# Thunder-Forged — 4 tiers with weapon/armor options
# Source: ddowiki.com/page/Thunder-Forged
# ---------------------------------------------------------------------------

THUNDER_FORGED_OPTIONS: list[dict] = [
    # Base (Tier 0)
    {"system_id": _TF, "tier": "Base", "name": "Base Weapon",
     "description": "+9 Enhancement bonus; Metalline; Orange augment slot; ML 22"},
    {"system_id": _TF, "tier": "Base", "name": "Base Armor (Shadowscale)",
     "description": "+11 Enhancement bonus; Fortification 125%; ML 26"},

    # Tier 1
    {"system_id": _TF, "tier": "Tier 1", "name": "Blinding Fear",
     "description": "On Hit: Blinds and Shakens foe for 6 seconds; +10 Enhancement"},
    {"system_id": _TF, "tier": "Tier 1", "name": "Dragon Bane",
     "description": "Epic Bane of Dragons: +8 to hit, +5d6 damage vs dragons; +10 Enhancement"},
    {"system_id": _TF, "tier": "Tier 1", "name": "Burn (Fire)",
     "description": "Fire damage proc; +90 Combustion spell power; +10 Enhancement"},
    {"system_id": _TF, "tier": "Tier 1", "name": "Shadow (Negative)",
     "description": "Negative energy damage proc; +90 Nullification spell power; +10 Enhancement"},

    # Tier 2
    {"system_id": _TF, "tier": "Tier 2", "name": "Dragon's Blessing",
     "description": "On spell cast: heal ally for spell points spent; +11 Enhancement"},
    {"system_id": _TF, "tier": "Tier 2", "name": "Dragon's Edge",
     "description": "Armor-Piercing 35%; Bleed on critical hit; +11 Enhancement"},
    {"system_id": _TF, "tier": "Tier 2", "name": "Burn AoE",
     "description": "Fire AoE damage proc on hit; Red augment slot; +11 Enhancement"},
    {"system_id": _TF, "tier": "Tier 2", "name": "Shadow AoE",
     "description": "Negative AoE damage proc on hit; Green augment slot; +11 Enhancement"},
    {"system_id": _TF, "tier": "Tier 2", "name": "Spell Focus (Fire)",
     "description": "+3 Equipment bonus to Evocation/Conjuration DCs; Red augment slot; +11 Enhancement"},
    {"system_id": _TF, "tier": "Tier 2", "name": "Spell Focus (Shadow)",
     "description": "+3 Equipment bonus to Necromancy/Enchantment DCs; Purple augment slot; +11 Enhancement"},

    # Tier 3
    {"system_id": _TF, "tier": "Tier 3", "name": "Dragon Breath (Fire)",
     "description": "Fire Storm breath attack 3/rest; 1d15+15 fire damage per caster level; +12 Enhancement"},
    {"system_id": _TF, "tier": "Tier 3", "name": "Dragon Breath (Ice)",
     "description": "Ice Storm breath attack 3/rest; 1d15+15 cold damage per caster level; +12 Enhancement"},
    {"system_id": _TF, "tier": "Tier 3", "name": "Dragon Breath (Lightning)",
     "description": "Lightning Storm breath attack 3/rest; 1d15+15 electric damage per caster level; +12 Enhancement"},
    {"system_id": _TF, "tier": "Tier 3", "name": "Dragon Breath (Acid)",
     "description": "Acid Storm breath attack 3/rest; 1d15+15 acid damage per caster level; +12 Enhancement"},
    {"system_id": _TF, "tier": "Tier 3", "name": "Spell Lore (Evocation)",
     "description": "+22% Evocation Spell Critical Chance; +12 Enhancement"},
    {"system_id": _TF, "tier": "Tier 3", "name": "Spell Lore (Conjuration)",
     "description": "+22% Conjuration Spell Critical Chance; +12 Enhancement"},
    {"system_id": _TF, "tier": "Tier 3", "name": "Spell Lore (Necromancy)",
     "description": "+22% Necromancy Spell Critical Chance; +12 Enhancement"},
    {"system_id": _TF, "tier": "Tier 3", "name": "Spell Lore (Enchantment)",
     "description": "+22% Enchantment Spell Critical Chance; +12 Enhancement"},
    {"system_id": _TF, "tier": "Tier 3", "name": "Vorpal (Fire)",
     "description": "Vorpal on natural 20; fire damage proc; +12 Enhancement"},
    {"system_id": _TF, "tier": "Tier 3", "name": "Draconic Reinvigoration",
     "description": "Action boost generation on hit; +12 Enhancement"},
]


# ---------------------------------------------------------------------------
# Dinosaur Bone — augment-based system (weapons, accessories, armor)
# Source: ddowiki.com/page/Dinosaur_Bone_crafting
# ---------------------------------------------------------------------------

DINOSAUR_BONE_OPTIONS: list[dict] = [
    # --- Weapon Scales ---
    {"system_id": _DINO, "tier": "Weapon Scale", "name": "Flamescale",
     "description": "Adamantine material; On hit: 15d6 Fire Damage"},
    {"system_id": _DINO, "tier": "Weapon Scale", "name": "Icescale",
     "description": "Cold Iron material; On hit: 15d6 Cold Damage"},
    {"system_id": _DINO, "tier": "Weapon Scale", "name": "Sparkscale",
     "description": "Silver material; On hit: 15d6 Electric Damage"},
    {"system_id": _DINO, "tier": "Weapon Scale", "name": "Meltscale",
     "description": "Crystal/Byeshk material; On hit: 15d6 Acid Damage"},
    {"system_id": _DINO, "tier": "Weapon Scale", "name": "Brightscale",
     "description": "+9 Enhancement bonus to Spell Penetration"},
    {"system_id": _DINO, "tier": "Weapon Scale", "name": "Shadowscale",
     "description": "+10% Enhancement bonus to Spell Cost Reduction"},
    {"system_id": _DINO, "tier": "Weapon Scale", "name": "Iridescent Scale",
     "description": "+102 Equipment bonus to all Spell Powers"},

    # --- Weapon Fangs ---
    {"system_id": _DINO, "tier": "Weapon Fang", "name": "Flamefang",
     "description": "Good alignment bypass; fire damage procs"},
    {"system_id": _DINO, "tier": "Weapon Fang", "name": "Icefang",
     "description": "Chaotic alignment bypass; cold DoT stacks"},
    {"system_id": _DINO, "tier": "Weapon Fang", "name": "Sparkfang",
     "description": "Lawful alignment bypass; electric damage procs"},
    {"system_id": _DINO, "tier": "Weapon Fang", "name": "Meltfang",
     "description": "Evil alignment bypass; acid DoT stacking"},
    {"system_id": _DINO, "tier": "Weapon Fang", "name": "Brightfang",
     "description": "Untyped damage chance on attacks/spells"},
    {"system_id": _DINO, "tier": "Weapon Fang", "name": "Shadowfang",
     "description": "Curse application with untyped DoT damage"},
    {"system_id": _DINO, "tier": "Weapon Fang", "name": "Iridescent Fang",
     "description": "+5 Equipment bonus to all Spell DCs"},

    # --- Weapon Claws ---
    {"system_id": _DINO, "tier": "Weapon Claw", "name": "Flameclaw",
     "description": "+2 Exceptional bonus to Strength"},
    {"system_id": _DINO, "tier": "Weapon Claw", "name": "Iceclaw",
     "description": "+2 Exceptional bonus to Wisdom"},
    {"system_id": _DINO, "tier": "Weapon Claw", "name": "Sparkclaw",
     "description": "+2 Exceptional bonus to Charisma"},
    {"system_id": _DINO, "tier": "Weapon Claw", "name": "Meltclaw",
     "description": "+2 Exceptional bonus to Constitution"},
    {"system_id": _DINO, "tier": "Weapon Claw", "name": "Brightclaw",
     "description": "+2 Exceptional bonus to Intelligence"},
    {"system_id": _DINO, "tier": "Weapon Claw", "name": "Shadowclaw",
     "description": "+2 Exceptional bonus to Dexterity"},
    {"system_id": _DINO, "tier": "Weapon Claw", "name": "Iridescent Claws (element)",
     "description": "+149 Equipment bonus to specific Spell Power (10 element variants)"},

    # --- Weapon Horns ---
    {"system_id": _DINO, "tier": "Weapon Horn", "name": "Flamehorn",
     "description": "Reduces enemy MRR and Universal Spell Power"},
    {"system_id": _DINO, "tier": "Weapon Horn", "name": "Icehorn",
     "description": "Freeze effect on targets"},
    {"system_id": _DINO, "tier": "Weapon Horn", "name": "Sparkhorn",
     "description": "Vulnerability stacking application"},
    {"system_id": _DINO, "tier": "Weapon Horn", "name": "Melthorn",
     "description": "Reduces enemy PRR and healing amplification"},
    {"system_id": _DINO, "tier": "Weapon Horn", "name": "Brighthorn",
     "description": "Grants 1,000 Temporary HP chance on hit"},
    {"system_id": _DINO, "tier": "Weapon Horn", "name": "Shadowhorn",
     "description": "Reduces enemy PRR and MRR combined"},

    # --- Accessory Scales ---
    {"system_id": _DINO, "tier": "Accessory Scale", "name": "False Life",
     "description": "+53 Enhancement bonus to Maximum HP"},
    {"system_id": _DINO, "tier": "Accessory Scale", "name": "Strength",
     "description": "+14 Enhancement bonus to Strength"},
    {"system_id": _DINO, "tier": "Accessory Scale", "name": "Dexterity",
     "description": "+14 Enhancement bonus to Dexterity"},
    {"system_id": _DINO, "tier": "Accessory Scale", "name": "Constitution",
     "description": "+14 Enhancement bonus to Constitution"},
    {"system_id": _DINO, "tier": "Accessory Scale", "name": "Intelligence",
     "description": "+14 Enhancement bonus to Intelligence"},
    {"system_id": _DINO, "tier": "Accessory Scale", "name": "Wisdom",
     "description": "+14 Enhancement bonus to Wisdom"},
    {"system_id": _DINO, "tier": "Accessory Scale", "name": "Charisma",
     "description": "+14 Enhancement bonus to Charisma"},

    # --- Accessory Fangs ---
    {"system_id": _DINO, "tier": "Accessory Fang", "name": "Healing Amplification",
     "description": "+56 Competence bonus to Positive Healing Amplification"},
    {"system_id": _DINO, "tier": "Accessory Fang", "name": "Negative Amplification",
     "description": "+56 Profane bonus to Negative Healing Amplification"},
    {"system_id": _DINO, "tier": "Accessory Fang", "name": "Repair Amplification",
     "description": "+56 Enhancement bonus to Repair Amplification"},
    {"system_id": _DINO, "tier": "Accessory Fang", "name": "Accuracy",
     "description": "+21 Competence bonus to Attack"},
    {"system_id": _DINO, "tier": "Accessory Fang", "name": "Damage",
     "description": "+11 Competence bonus to Damage"},
    {"system_id": _DINO, "tier": "Accessory Fang", "name": "Seeker",
     "description": "+14 Enhancement bonus to Critical Confirmation and Damage"},
    {"system_id": _DINO, "tier": "Accessory Fang", "name": "Deception",
     "description": "+11 Enhancement bonus to Sneak Attacks; +17 to Sneak Attack Damage"},

    # --- Accessory Claws ---
    {"system_id": _DINO, "tier": "Accessory Claw", "name": "Physical Resistance Rating",
     "description": "+35 Enhancement bonus to Physical Resistance Rating"},
    {"system_id": _DINO, "tier": "Accessory Claw", "name": "Magical Resistance Rating",
     "description": "+35 Enhancement bonus to Magical Resistance Rating"},
    {"system_id": _DINO, "tier": "Accessory Claw", "name": "Stunning",
     "description": "+15 Enhancement bonus to Stunning DCs"},
    {"system_id": _DINO, "tier": "Accessory Claw", "name": "Trip",
     "description": "+15 Enhancement bonus to Trip DCs"},
    {"system_id": _DINO, "tier": "Accessory Claw", "name": "Sunder",
     "description": "+15 Enhancement bonus to Sunder DCs"},
    {"system_id": _DINO, "tier": "Accessory Claw", "name": "Assassinate",
     "description": "+15 Enhancement bonus to Assassinate DCs"},
    {"system_id": _DINO, "tier": "Accessory Claw", "name": "Spell Penetration",
     "description": "+9 Equipment bonus to Spell Penetration"},

    # --- Accessory Horns ---
    {"system_id": _DINO, "tier": "Accessory Horn", "name": "Resistance",
     "description": "+12 Resistance bonus to all Saving Throws"},
    {"system_id": _DINO, "tier": "Accessory Horn", "name": "Enhanced Ghostly",
     "description": "15% Incorporeal miss chance; +5 Enhancement Hide/Move Silently"},
    {"system_id": _DINO, "tier": "Accessory Horn", "name": "Relentless Fury",
     "description": "5% Enhancement damage bonus to melee/ranged for 30 seconds"},
    {"system_id": _DINO, "tier": "Accessory Horn", "name": "Armor Piercing",
     "description": "+21% Enhancement bonus to Fortification Bypass"},
    {"system_id": _DINO, "tier": "Accessory Horn", "name": "Wizardry",
     "description": "+286 Enhancement bonus to Maximum Spell Points"},
    {"system_id": _DINO, "tier": "Accessory Horn", "name": "Profane DCs",
     "description": "+2 Profane bonus to Spell DCs"},
    {"system_id": _DINO, "tier": "Accessory Horn", "name": "Sacred DCs",
     "description": "+2 Sacred bonus to Spell DCs"},

    # --- Armor Scales ---
    {"system_id": _DINO, "tier": "Armor Scale", "name": "Bronzescale",
     "description": "Deathblock; Ghostly (10% incorporeal)"},
    {"system_id": _DINO, "tier": "Armor Scale", "name": "Goldscale",
     "description": "+150% Enhancement bonus to Fortification"},
    {"system_id": _DINO, "tier": "Armor Scale", "name": "Silverscale",
     "description": "+56 bonus to Healing/Negative/Repair Amplification"},
    {"system_id": _DINO, "tier": "Armor Scale", "name": "Voidscale",
     "description": "+5% Exceptional bonus to Universal Spell Lore"},

    # --- Armor Fangs ---
    {"system_id": _DINO, "tier": "Armor Fang", "name": "Goldfang",
     "description": "+2d6 Profane bonus to Sneak Attack Dice"},
    {"system_id": _DINO, "tier": "Armor Fang", "name": "Silverfang",
     "description": "+2 Profane bonus to Spell DCs, Tactical DCs, Assassinate"},
    {"system_id": _DINO, "tier": "Armor Fang", "name": "Voidfang",
     "description": "+15 Exceptional bonus to Universal Spell Power"},
]


def _load_missing_json() -> list[dict]:
    """Load previously-zero-option systems from JSON (557 options across 10 systems)."""
    import json
    from pathlib import Path

    json_path = Path(__file__).parent / "crafting_missing.json"
    if not json_path.exists():
        return []
    return json.loads(json_path.read_text())


def get_all_static_options() -> list[dict]:
    """Return all static crafting options for systems with guide-format wiki pages."""
    return (
        GREEN_STEEL_OPTIONS
        + LGS_OPTIONS
        + THUNDER_FORGED_OPTIONS
        + DINOSAUR_BONE_OPTIONS
        + _load_missing_json()
    )
