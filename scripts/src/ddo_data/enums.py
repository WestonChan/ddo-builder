"""Canonical enum constants for DDO build planner.

All string constants used in the DB schema, parser mappings, and frontend
queries are defined here. Using enum members instead of raw strings catches
typos at import/lint time.

Each enum extends ``str`` so values work directly in SQL queries, dict
lookups, and JSON serialization without conversion.

Usage::

    from ddo_data.stat_names import S, ItemCategory, BonusType

    # In aliases:
    _STAT_ALIASES = {"ac": S.ARMOR_CLASS, ...}

    # In writer:
    if item_category == ItemCategory.WEAPON: ...
"""

from __future__ import annotations

from enum import Enum


class S(str, Enum):
    """DDO stat names. Value is the canonical string used in the DB seed."""

    def __str__(self) -> str:
        """Return the value string (not the member name) for DB compatibility."""
        return self.value

    # --- Ability Scores ---
    STRENGTH = "Strength"
    DEXTERITY = "Dexterity"
    CONSTITUTION = "Constitution"
    INTELLIGENCE = "Intelligence"
    WISDOM = "Wisdom"
    CHARISMA = "Charisma"

    # --- Martial ---
    MELEE_POWER = "Melee Power"
    RANGED_POWER = "Ranged Power"
    ATTACK_BONUS = "Attack Bonus"
    DAMAGE_BONUS = "Damage Bonus"
    DOUBLESTRIKE = "Doublestrike"
    DOUBLESHOT = "Doubleshot"
    SNEAK_ATTACK = "Sneak Attack"
    SNEAK_ATTACK_DICE = "Sneak Attack Dice"
    SNEAK_ATTACK_DAMAGE = "Sneak Attack Damage"
    SNEAK_ATTACK_HIT = "Sneak Attack Hit"
    CRITICAL_THREAT_RANGE = "Critical Threat Range"
    CRITICAL_CONFIRMATION = "Critical Confirmation"
    CRITICAL_DAMAGE = "Critical Damage"
    CRITICAL_MULTIPLIER_19_20 = "Critical Multiplier (19-20)"
    FORTIFICATION_BYPASS = "Fortification Bypass"
    HELPLESS_DAMAGE = "Helpless Damage"
    IMBUE_DICE = "Imbue Dice"
    TACTICS = "Tactics"
    ASSASSINATE_DC = "Assassinate DC"
    STRIKETHROUGH = "Strikethrough"
    OFFHAND_STRIKE_CHANCE = "Offhand Strike Chance"
    ATTACK_SPEED = "Attack Speed"

    # --- Defensive ---
    ARMOR_CLASS = "Armor Class"
    HIT_POINTS = "Hit Points"
    PHYSICAL_RESISTANCE_RATING = "Physical Resistance Rating"
    MAGICAL_RESISTANCE_RATING = "Magical Resistance Rating"
    PHYSICAL_AND_MAGICAL_RESISTANCE_RATING = "Physical and Magical Resistance Rating"
    MAGICAL_RESISTANCE_RATING_CAP = "Magical Resistance Rating Cap"
    PHYSICAL_SHELTERING = "Physical Sheltering"
    MAGICAL_SHELTERING = "Magical Sheltering"
    FORTITUDE_SAVE = "Fortitude Save"
    REFLEX_SAVE = "Reflex Save"
    WILL_SAVE = "Will Save"
    SAVING_THROWS = "Saving Throws"
    SPELL_RESISTANCE = "Spell Resistance"
    NATURAL_ARMOR = "Natural Armor"
    SHIELD_ARMOR_CLASS = "Shield Armor Class"
    DODGE_CAP = "Dodge Cap"
    UNCONSCIOUSNESS_RANGE = "Unconsciousness Range"
    MISSILE_DEFLECTION = "Missile Deflection"

    # --- Threat ---
    THREAT_GENERATION = "Threat Generation"
    MELEE_THREAT_GENERATION = "Melee Threat Generation"
    THREAT_REDUCTION = "Threat Reduction"
    MELEE_AND_RANGED_THREAT_REDUCTION = "Melee and Ranged Threat Reduction"

    # --- Spell Power (per-element) ---
    FIRE_SPELL_POWER = "Fire Spell Power"
    COLD_SPELL_POWER = "Cold Spell Power"
    ELECTRIC_SPELL_POWER = "Electric Spell Power"
    ACID_SPELL_POWER = "Acid Spell Power"
    SONIC_SPELL_POWER = "Sonic Spell Power"
    LIGHT_SPELL_POWER = "Light Spell Power"
    NEGATIVE_SPELL_POWER = "Negative Spell Power"
    POSITIVE_SPELL_POWER = "Positive Spell Power"
    FORCE_SPELL_POWER = "Force Spell Power"
    REPAIR_SPELL_POWER = "Repair Spell Power"
    POISON_SPELL_POWER = "Poison Spell Power"
    UNIVERSAL_SPELL_POWER = "Universal Spell Power"
    POTENCY = "Potency"

    # --- Spell Lore (per-element crit chance) ---
    FIRE_SPELL_LORE = "Fire Spell Lore"
    COLD_SPELL_LORE = "Cold Spell Lore"
    ELECTRIC_SPELL_LORE = "Electric Spell Lore"
    ACID_SPELL_LORE = "Acid Spell Lore"
    SONIC_SPELL_LORE = "Sonic Spell Lore"
    LIGHT_SPELL_LORE = "Light Spell Lore"
    NEGATIVE_SPELL_LORE = "Negative Spell Lore"
    POSITIVE_SPELL_LORE = "Positive Spell Lore"
    FORCE_SPELL_LORE = "Force Spell Lore"
    REPAIR_SPELL_LORE = "Repair Spell Lore"
    POISON_SPELL_LORE = "Poison Spell Lore"
    UNIVERSAL_SPELL_LORE = "Universal Spell Lore"
    SPELL_LORE = "Spell Lore"  # generic (splits to all schools)

    # --- Spell Critical Damage ---
    SPELL_CRITICAL_DAMAGE = "Spell Critical Damage"
    UNIVERSAL_SPELL_CRITICAL_DAMAGE = "Universal Spell Critical Damage"

    # --- Alignment Spell Power ---
    GOOD_SPELL_POWER = "Good Spell Power"
    EVIL_SPELL_POWER = "Evil Spell Power"
    LAW_SPELL_POWER = "Law Spell Power"
    CHAOS_SPELL_POWER = "Chaos Spell Power"

    # --- Alignment Spell Lore ---
    GOOD_SPELL_LORE = "Good Spell Lore"
    EVIL_SPELL_LORE = "Evil Spell Lore"
    LAW_SPELL_LORE = "Law Spell Lore"
    CHAOS_SPELL_LORE = "Chaos Spell Lore"

    # --- Spell Focus (per-school DCs) ---
    ABJURATION_SPELL_FOCUS = "Abjuration Spell Focus"
    CONJURATION_SPELL_FOCUS = "Conjuration Spell Focus"
    DIVINATION_SPELL_FOCUS = "Divination Spell Focus"
    ENCHANTMENT_SPELL_FOCUS = "Enchantment Spell Focus"
    EVOCATION_SPELL_FOCUS = "Evocation Spell Focus"
    ILLUSION_SPELL_FOCUS = "Illusion Spell Focus"
    NECROMANCY_SPELL_FOCUS = "Necromancy Spell Focus"
    TRANSMUTATION_SPELL_FOCUS = "Transmutation Spell Focus"

    # --- Other Magical ---
    SPELL_POINTS = "Spell Points"
    MAXIMUM_SPELL_POINTS = "Maximum Spell Points"
    SPELL_PENETRATION = "Spell Penetration"
    SPELL_DCS = "Spell DCs"
    RUNE_ARM_DC = "Rune Arm DC"
    HEALING_AMPLIFICATION = "Healing Amplification"
    POSITIVE_HEALING_AMPLIFICATION = "Positive Healing Amplification"
    NEGATIVE_HEALING_AMPLIFICATION = "Negative Healing Amplification"
    REPAIR_AMPLIFICATION = "Repair Amplification"
    MOVEMENT_SPEED = "Movement Speed"

    # --- Absorption (per-element) ---
    FIRE_ABSORPTION = "Fire Absorption"
    COLD_ABSORPTION = "Cold Absorption"
    ELECTRIC_ABSORPTION = "Electric Absorption"
    ACID_ABSORPTION = "Acid Absorption"
    SONIC_ABSORPTION = "Sonic Absorption"
    LIGHT_ABSORPTION = "Light Absorption"
    NEGATIVE_ABSORPTION = "Negative Absorption"
    POSITIVE_ABSORPTION = "Positive Absorption"
    FORCE_ABSORPTION = "Force Absorption"
    REPAIR_ABSORPTION = "Repair Absorption"
    POISON_ABSORPTION = "Poison Absorption"
    GOOD_ABSORPTION = "Good Absorption"
    EVIL_ABSORPTION = "Evil Absorption"
    LAW_ABSORPTION = "Law Absorption"
    CHAOS_ABSORPTION = "Chaos Absorption"

    # --- Resistance (per-element) ---
    FIRE_RESISTANCE = "Fire Resistance"
    COLD_RESISTANCE = "Cold Resistance"
    ELECTRIC_RESISTANCE = "Electric Resistance"
    ACID_RESISTANCE = "Acid Resistance"

    # --- Skills ---
    HIDE = "Hide"
    BLUFF = "Bluff"
    INTIMIDATE = "Intimidate"
    SEARCH = "Search"
    SPOT = "Spot"
    PERFORM = "Perform"
    COMMAND = "Command"
    PERSUASION = "Persuasion"

    # --- Saves (specific) ---
    POISON_SAVE = "Poison Save"
    SAVES_VS_EVIL = "Saves vs Evil"
    ATTACK_AND_DAMAGE_VS_EVIL = "Attack and Damage vs Evil"

    # --- Quality/Other ---
    QUALITY = "Quality"


class ItemCategory(str, Enum):
    """Item category (from binary enum or wiki)."""
    def __str__(self) -> str: return self.value
    # Equippable (kept in DB)
    ARMOR = "Armor"
    SHIELD = "Shield"
    WEAPON = "Weapon"
    JEWELRY = "Jewelry"
    CLOTHING = "Clothing"
    # Non-equippable (filtered out during import)
    WONDROUS = "Wondrous"
    POTION = "Potion"
    SCROLL = "Scroll"
    WAND = "Wand"
    COMPONENT = "Component"
    COLLECTIBLE = "Collectible"
    CONSUMABLE = "Consumable"


class Rarity(str, Enum):
    """Item rarity tier."""
    def __str__(self) -> str: return self.value
    COMMON = "Common"
    UNCOMMON = "Uncommon"
    RARE = "Rare"
    EPIC = "Epic"


class Handedness(str, Enum):
    """Weapon handedness."""
    def __str__(self) -> str: return self.value
    ONE_HANDED = "One-handed"
    TWO_HANDED = "Two-handed"
    OFF_HAND = "Off-hand"
    THROWN = "Thrown"


class TreeType(str, Enum):
    """Enhancement tree type."""
    def __str__(self) -> str: return self.value
    CLASS = "class"
    RACIAL = "racial"
    UNIVERSAL = "universal"
    REAPER = "reaper"
    DESTINY = "destiny"


class EnhancementTier(str, Enum):
    """Enhancement tier within a tree."""
    def __str__(self) -> str: return self.value
    CORE = "core"
    T1 = "1"
    T2 = "2"
    T3 = "3"
    T4 = "4"
    T5 = "5"
    UNKNOWN = "unknown"


class SpellSchool(str, Enum):
    """D&D spell school."""
    def __str__(self) -> str: return self.value
    ABJURATION = "Abjuration"
    CONJURATION = "Conjuration"
    DIVINATION = "Divination"
    ENCHANTMENT = "Enchantment"
    EVOCATION = "Evocation"
    ILLUSION = "Illusion"
    NECROMANCY = "Necromancy"
    TRANSMUTATION = "Transmutation"
    UNIVERSAL = "Universal"


class RaceType(str, Enum):
    """Race availability category."""
    def __str__(self) -> str: return self.value
    FREE = "free"
    PREMIUM = "premium"
    ICONIC = "iconic"


class FeatTier(str, Enum):
    """Feat level tier."""
    def __str__(self) -> str: return self.value
    HEROIC = "heroic"
    EPIC = "epic"
    LEGENDARY = "legendary"
    DESTINY = "destiny"
    DARK_GIFT = "dark_gift"


class DataSource(str, Enum):
    """Data provenance."""
    def __str__(self) -> str: return self.value
    BINARY = "binary"
    WIKI = "wiki"


class Alignment(str, Enum):
    """Class/race alignment restriction."""
    def __str__(self) -> str: return self.value
    ANY = "any"
    ANY_LAWFUL = "any lawful"
    ANY_NEUTRAL = "any neutral"
    ANY_NON_LAWFUL = "any non-lawful"
    LAWFUL_GOOD = "lawful good"


class BabProgression(str, Enum):
    """Base attack bonus progression rate."""
    def __str__(self) -> str: return self.value
    FULL = "full"
    THREE_QUARTER = "three_quarter"
    HALF = "half"


class SaveProgression(str, Enum):
    """Save bonus progression rate."""
    def __str__(self) -> str: return self.value
    GOOD = "good"
    POOR = "poor"


class CasterType(str, Enum):
    """Spellcasting progression type."""
    def __str__(self) -> str: return self.value
    FULL = "full"
    HALF = "half"
    NONE = "none"


class SpellTradition(str, Enum):
    """Spell tradition."""
    def __str__(self) -> str: return self.value
    ARCANE = "arcane"
    DIVINE = "divine"


class EquipmentSlot(str, Enum):
    """Equipment slot for gear items."""
    def __str__(self) -> str: return self.value
    MAIN_HAND = "Main Hand"
    OFF_HAND = "Off Hand"
    RANGED = "Ranged"
    QUIVER = "Quiver"
    HEAD = "Head"
    NECK = "Neck"
    TRINKET = "Trinket"
    BACK = "Back"
    WRISTS = "Wrists"
    ARMS = "Arms"
    BODY = "Body"
    WAIST = "Waist"
    FEET = "Feet"
    GOGGLES = "Goggles"
    RING = "Ring"
    RUNEARM = "Runearm"


class ResolutionMethod(str, Enum):
    """How a bonus stat was resolved."""
    def __str__(self) -> str: return self.value
    FID_LOOKUP = "fid_lookup"
    TYPE167_NAME = "type167_name"
    STAT_DEF_IDS = "stat_def_ids"
    WIKI_ENCHANTMENT = "wiki_enchantment"
    NAMED_ENCHANTMENT = "named_enchantment"
    WIKI_DESCRIPTION = "wiki_description"
    BINARY_NAME = "binary_name"
    LOCALIZATION_ORPHAN = "localization_orphan"
    FID_LOOKUP_AUGMENT = "fid_lookup"


class AugmentColor(str, Enum):
    """Augment slot color."""
    def __str__(self) -> str: return self.value
    COLORLESS = "colorless"
    BLUE = "blue"
    YELLOW = "yellow"
    RED = "red"
    GREEN = "green"
    ORANGE = "orange"
    PURPLE = "purple"
    SUN = "sun"
    MOON = "moon"


class DamageCategory(str, Enum):
    """Damage type category."""
    def __str__(self) -> str: return self.value
    PHYSICAL = "physical"
    ELEMENTAL = "elemental"
    ALIGNMENT = "alignment"
    ENERGY = "energy"
    UNTYPED = "untyped"


class SlotType(str, Enum):
    """Bonus feat slot type."""
    def __str__(self) -> str: return self.value
    CLASS_BONUS = "class_bonus"
    MARTIAL_ARTS = "martial_arts"
    CLASS_CHOICE = "class_choice"


class PastLifeType(str, Enum):
    """Past life feat category."""
    def __str__(self) -> str: return self.value
    HEROIC = "heroic"
    RACIAL = "racial"
    ICONIC = "iconic"
    EPIC = "epic"
    LEGENDARY = "legendary"
