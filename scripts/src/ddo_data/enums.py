"""Canonical enum constants for DDO build planner.

All string constants used in the DB schema, parser mappings, and frontend
queries are defined here. Using enum members instead of raw strings catches
typos at import/lint time.

Each enum extends ``str`` so values work directly in SQL queries, dict
lookups, and JSON serialization without conversion.

Rich enums (S, Skill, BonusType, DamageType, EquipmentSlot)
carry their DB seed attributes (id, category, etc.) directly on each member.
This means the enum IS the source of truth for the table — seed SQL is
generated from the enum, not maintained separately.

Usage::

    from ddo_data.enums import S, ItemCategory, BonusType

    # Stat with DB id and category:
    S.STRENGTH.id         # 1
    S.STRENGTH.category   # StatCategory.ABILITY
    str(S.STRENGTH)       # "Strength"

    # In writer:
    if item_category == ItemCategory.WEAPON: ...
"""

from __future__ import annotations

from enum import Enum


# ---------------------------------------------------------------------------
# Category enums (must be defined before the rich enums that reference them)
# ---------------------------------------------------------------------------

class StatCategory(str, Enum):
    """Stat seed category."""
    def __str__(self) -> str: return self.value
    ABILITY = "ability"
    DEFENSIVE = "defensive"
    MARTIAL = "martial"
    MAGICAL = "magical"
    SKILL = "skill"
    OTHER = "other"


class DamageCategory(str, Enum):
    """Damage type category."""
    def __str__(self) -> str: return self.value
    PHYSICAL = "physical"
    ELEMENTAL = "elemental"
    ALIGNMENT = "alignment"
    ENERGY = "energy"
    UNTYPED = "untyped"


class SlotCategory(str, Enum):
    """Equipment slot category."""
    def __str__(self) -> str: return self.value
    WEAPON = "weapon"
    ARMOR = "armor"
    ACCESSORY = "accessory"


# Compact aliases for member definitions below
_C = StatCategory
_DC = DamageCategory
_SC = SlotCategory


# ---------------------------------------------------------------------------
# Rich enums — carry DB seed attributes on each member
# ---------------------------------------------------------------------------

class S(str, Enum):
    """DDO stat names with DB seed attributes (id, category).

    Each member is ``(label, id, category)`` where label is the canonical
    string stored in the ``stats.name`` column.
    """

    def __new__(cls, value: str, id: int, category: StatCategory) -> S:
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.id = id
        obj.category = category
        return obj

    def __str__(self) -> str: return self.value

    # --- Ability Scores ---
    STRENGTH                                = ("Strength", 1, _C.ABILITY)
    DEXTERITY                               = ("Dexterity", 2, _C.ABILITY)
    CONSTITUTION                            = ("Constitution", 3, _C.ABILITY)
    INTELLIGENCE                            = ("Intelligence", 4, _C.ABILITY)
    WISDOM                                  = ("Wisdom", 5, _C.ABILITY)
    CHARISMA                                = ("Charisma", 6, _C.ABILITY)

    # --- Martial ---
    MELEE_POWER                             = ("Melee Power", 7, _C.MARTIAL)
    RANGED_POWER                            = ("Ranged Power", 8, _C.MARTIAL)
    ATTACK_BONUS                            = ("Attack Bonus", 9, _C.MARTIAL)
    DAMAGE_BONUS                            = ("Damage Bonus", 10, _C.MARTIAL)
    HIT_POINTS                              = ("Hit Points", 11, _C.MARTIAL)
    SNEAK_ATTACK_DICE                       = ("Sneak Attack Dice", 12, _C.MARTIAL)
    TRIP_DC                                 = ("Trip DC", 36, _C.MARTIAL)
    SUNDER_DC                               = ("Sunder DC", 37, _C.MARTIAL)
    STUN_DC                                 = ("Stun DC", 38, _C.MARTIAL)
    ASSASSINATE_DC                          = ("Assassinate DC", 39, _C.MARTIAL)
    HELPLESS_DAMAGE                         = ("Helpless Damage", 40, _C.MARTIAL)
    SEEKER                                  = ("Seeker", 63, _C.MARTIAL)
    DEADLY                                  = ("Deadly", 64, _C.MARTIAL)
    ACCURACY                                = ("Accuracy", 65, _C.MARTIAL)
    DECEPTION_STAT                          = ("Deception", 66, _C.MARTIAL)
    SPEED                                   = ("Speed", 67, _C.MARTIAL)
    DOUBLESTRIKE                            = ("Doublestrike", 68, _C.MARTIAL)
    DOUBLESHOT                              = ("Doubleshot", 69, _C.MARTIAL)
    COMBAT_MASTERY                          = ("Combat Mastery", 118, _C.MARTIAL)
    TENDON_SLICE                            = ("Tendon Slice", 119, _C.MARTIAL)
    NIMBLE                                  = ("Nimble", 124, _C.MARTIAL)
    ALLURING                                = ("Alluring", 125, _C.MARTIAL)
    CRITICAL_DAMAGE_MULTIPLIER              = ("Critical Damage Multiplier", 132, _C.MARTIAL)
    CRITICAL_THREAT_RANGE                   = ("Critical Threat Range", 133, _C.MARTIAL)
    MELEE_AND_RANGED_POWER                  = ("Melee and Ranged Power", 134, _C.MARTIAL)
    DOUBLESTRIKE_AND_DOUBLESHOT             = ("Doublestrike and Doubleshot", 138, _C.MARTIAL)
    SHATTER                                 = ("Shatter", 164, _C.MARTIAL)
    PRUDENT                                 = ("Prudent", 165, _C.MARTIAL)
    ASTUTE                                  = ("Astute", 166, _C.MARTIAL)
    IMBUE_DICE                              = ("Imbue Dice", 180, _C.MARTIAL)
    FORTIFICATION_BYPASS                    = ("Fortification Bypass", 181, _C.MARTIAL)
    ATTACK_SPEED                            = ("Attack Speed", 182, _C.MARTIAL)
    THREAT_GENERATION                       = ("Threat Generation", 188, _C.MARTIAL)
    MELEE_THREAT_GENERATION                 = ("Melee Threat Generation", 189, _C.MARTIAL)
    THREAT_REDUCTION                        = ("Threat Reduction", 190, _C.MARTIAL)
    OFFHAND_STRIKE_CHANCE                   = ("Offhand Strike Chance", 192, _C.MARTIAL)
    STRIKETHROUGH                           = ("Strikethrough", 193, _C.MARTIAL)
    CRITICAL_MULTIPLIER                     = ("Critical Multiplier", 194, _C.MARTIAL)
    TACTICS                                 = ("Tactics", 198, _C.MARTIAL)
    CRITICAL_CONFIRMATION                   = ("Critical Confirmation", 200, _C.MARTIAL)
    SNEAK_ATTACK_DAMAGE                     = ("Sneak Attack Damage", 204, _C.MARTIAL)
    CRITICAL_DAMAGE                         = ("Critical Damage", 205, _C.MARTIAL)
    SNEAK_ATTACK_HIT                        = ("Sneak Attack Hit", 207, _C.MARTIAL)
    SNEAK_ATTACK                            = ("Sneak Attack", 213, _C.MARTIAL)
    SNEAK_ATTACK_BONUS                      = ("Sneak Attack Bonus", 214, _C.MARTIAL)
    MELEE_AND_RANGED_THREAT_REDUCTION       = ("Melee and Ranged Threat Reduction", 226, _C.MARTIAL)
    RANGED_THREAT_REDUCTION                 = ("Ranged Threat Reduction", 227, _C.MARTIAL)
    ATTACK_AND_DAMAGE_VS_EVIL               = ("Attack and Damage vs Evil", 229, _C.MARTIAL)
    DAMAGE_VS_EVIL                          = ("Damage vs Evil", 230, _C.MARTIAL)
    CRITICAL_MULTIPLIER_19_20               = ("Critical Multiplier (19-20)", 231, _C.MARTIAL)

    # --- Defensive ---
    ARMOR_CLASS                             = ("Armor Class", 13, _C.DEFENSIVE)
    PHYSICAL_RESISTANCE_RATING              = ("Physical Resistance Rating", 14, _C.DEFENSIVE)
    MAGICAL_RESISTANCE_RATING               = ("Magical Resistance Rating", 15, _C.DEFENSIVE)
    FORTIFICATION                           = ("Fortification", 16, _C.DEFENSIVE)
    DODGE                                   = ("Dodge", 17, _C.DEFENSIVE)
    FORTITUDE_SAVE                          = ("Fortitude Save", 18, _C.DEFENSIVE)
    REFLEX_SAVE                             = ("Reflex Save", 19, _C.DEFENSIVE)
    WILL_SAVE                               = ("Will Save", 20, _C.DEFENSIVE)
    SPELL_RESISTANCE                        = ("Spell Resistance", 21, _C.DEFENSIVE)
    SAVING_THROWS_VS_TRAPS                  = ("Saving Throws vs Traps", 62, _C.DEFENSIVE)
    PHYSICAL_SHELTERING                     = ("Physical Sheltering", 70, _C.DEFENSIVE)
    MAGICAL_SHELTERING                      = ("Magical Sheltering", 71, _C.DEFENSIVE)
    CONCEALMENT                             = ("Concealment", 72, _C.DEFENSIVE)
    FIRE_RESISTANCE                         = ("Fire Resistance", 76, _C.DEFENSIVE)
    COLD_RESISTANCE                         = ("Cold Resistance", 77, _C.DEFENSIVE)
    ELECTRIC_RESISTANCE                     = ("Electric Resistance", 78, _C.DEFENSIVE)
    ACID_RESISTANCE                         = ("Acid Resistance", 79, _C.DEFENSIVE)
    SONIC_RESISTANCE                        = ("Sonic Resistance", 80, _C.DEFENSIVE)
    LIGHT_RESISTANCE                        = ("Light Resistance", 81, _C.DEFENSIVE)
    FORCE_RESISTANCE                        = ("Force Resistance", 82, _C.DEFENSIVE)
    NEGATIVE_RESISTANCE                     = ("Negative Resistance", 83, _C.DEFENSIVE)
    FIRE_ABSORPTION                         = ("Fire Absorption", 84, _C.DEFENSIVE)
    COLD_ABSORPTION                         = ("Cold Absorption", 85, _C.DEFENSIVE)
    ELECTRIC_ABSORPTION                     = ("Electric Absorption", 86, _C.DEFENSIVE)
    ACID_ABSORPTION                         = ("Acid Absorption", 87, _C.DEFENSIVE)
    SONIC_ABSORPTION                        = ("Sonic Absorption", 88, _C.DEFENSIVE)
    LIGHT_ABSORPTION                        = ("Light Absorption", 89, _C.DEFENSIVE)
    FORCE_ABSORPTION                        = ("Force Absorption", 90, _C.DEFENSIVE)
    NEGATIVE_ABSORPTION                     = ("Negative Absorption", 91, _C.DEFENSIVE)
    NATURAL_ARMOR                           = ("Natural Armor", 115, _C.DEFENSIVE)
    PROTECTION                              = ("Protection", 116, _C.DEFENSIVE)
    SHELTERING                              = ("Sheltering", 117, _C.DEFENSIVE)
    RESISTANCE                              = ("Resistance", 120, _C.DEFENSIVE)
    ENCHANTMENT_SAVE                        = ("Enchantment Save", 121, _C.DEFENSIVE)
    CURSE_SAVE                              = ("Curse Save", 122, _C.DEFENSIVE)
    POISON_RESISTANCE                       = ("Poison Resistance", 123, _C.DEFENSIVE)
    ELEMENTAL_RESISTANCE_STAT               = ("Elemental Resistance", 128, _C.DEFENSIVE)
    PHYSICAL_AND_MAGICAL_RESISTANCE_RATING  = ("Physical and Magical Resistance Rating", 135, _C.DEFENSIVE)
    TEMPORARY_HIT_POINTS                    = ("Temporary Hit Points", 142, _C.DEFENSIVE)
    MAXIMUM_HIT_POINTS                      = ("Maximum Hit Points", 145, _C.DEFENSIVE)
    NEGATIVE_ENERGY_ABSORPTION              = ("Negative Energy Absorption", 152, _C.DEFENSIVE)
    LAW_ABSORPTION                          = ("Law Absorption", 153, _C.DEFENSIVE)
    CHAOS_ABSORPTION                        = ("Chaos Absorption", 154, _C.DEFENSIVE)
    GOOD_ABSORPTION                         = ("Good Absorption", 155, _C.DEFENSIVE)
    EVIL_ABSORPTION                         = ("Evil Absorption", 156, _C.DEFENSIVE)
    ELEMENTAL_ABSORPTION_STAT               = ("Elemental Absorption", 157, _C.DEFENSIVE)
    ALIGNMENT_ABSORPTION                    = ("Alignment Absorption", 158, _C.DEFENSIVE)
    SPELL_ABSORPTION_STAT                   = ("Spell Absorption", 159, _C.DEFENSIVE)
    CURSE_ABSORPTION                        = ("Curse Absorption", 160, _C.DEFENSIVE)
    SAVING_THROWS                           = ("Saving Throws", 161, _C.DEFENSIVE)
    NEGATIVE_ENERGY_RESISTANCE              = ("Negative Energy Resistance", 167, _C.DEFENSIVE)
    ILLUSION_SAVE                           = ("Illusion Save", 170, _C.DEFENSIVE)
    FEAR_SAVE                               = ("Fear Save", 171, _C.DEFENSIVE)
    POISON_SAVE                             = ("Poison Save", 172, _C.DEFENSIVE)
    DISEASE_SAVE                            = ("Disease Save", 173, _C.DEFENSIVE)
    SLEEP_SAVE                              = ("Sleep Save", 175, _C.DEFENSIVE)
    TRAP_SAVE                               = ("Trap Save", 176, _C.DEFENSIVE)
    SPELL_SAVE                              = ("Spell Save", 177, _C.DEFENSIVE)
    MAGICAL_RESISTANCE_RATING_CAP           = ("Magical Resistance Rating Cap", 187, _C.DEFENSIVE)
    MISSILE_DEFLECTION                      = ("Missile Deflection", 191, _C.DEFENSIVE)
    SHIELD_ARMOR_CLASS                      = ("Shield Armor Class", 195, _C.DEFENSIVE)
    DODGE_CAP                               = ("Dodge Cap", 199, _C.DEFENSIVE)
    ARMOR_CLASS_PERCENTAGE                  = ("Armor Class Percentage", 203, _C.DEFENSIVE)
    POISON_ABSORPTION                       = ("Poison Absorption", 217, _C.DEFENSIVE)
    SAVES_VS_EVIL                           = ("Saves vs Evil", 228, _C.DEFENSIVE)
    UNCONSCIOUSNESS_RANGE                   = ("Unconsciousness Range", 232, _C.DEFENSIVE)
    POSITIVE_ABSORPTION                     = ("Positive Absorption", 234, _C.DEFENSIVE)
    REPAIR_ABSORPTION                       = ("Repair Absorption", 235, _C.DEFENSIVE)

    # --- Magical ---
    SPELL_POINTS                            = ("Spell Points", 22, _C.MAGICAL)
    SPELL_PENETRATION                       = ("Spell Penetration", 23, _C.MAGICAL)
    UNIVERSAL_SPELL_POWER                   = ("Universal Spell Power", 24, _C.MAGICAL)
    FIRE_SPELL_POWER                        = ("Fire Spell Power", 25, _C.MAGICAL)
    COLD_SPELL_POWER                        = ("Cold Spell Power", 26, _C.MAGICAL)
    ELECTRIC_SPELL_POWER                    = ("Electric Spell Power", 27, _C.MAGICAL)
    ACID_SPELL_POWER                        = ("Acid Spell Power", 28, _C.MAGICAL)
    SONIC_SPELL_POWER                       = ("Sonic Spell Power", 29, _C.MAGICAL)
    LIGHT_SPELL_POWER                       = ("Light Spell Power", 30, _C.MAGICAL)
    FORCE_SPELL_POWER                       = ("Force Spell Power", 31, _C.MAGICAL)
    NEGATIVE_SPELL_POWER                    = ("Negative Spell Power", 32, _C.MAGICAL)
    POSITIVE_SPELL_POWER                    = ("Positive Spell Power", 33, _C.MAGICAL)
    REPAIR_SPELL_POWER                      = ("Repair Spell Power", 34, _C.MAGICAL)
    ALIGNMENT_SPELL_POWER                   = ("Alignment Spell Power", 35, _C.MAGICAL)
    ABJURATION_SPELL_FOCUS                  = ("Abjuration Spell Focus", 92, _C.MAGICAL)
    CONJURATION_SPELL_FOCUS                 = ("Conjuration Spell Focus", 93, _C.MAGICAL)
    ENCHANTMENT_SPELL_FOCUS                 = ("Enchantment Spell Focus", 94, _C.MAGICAL)
    EVOCATION_SPELL_FOCUS                   = ("Evocation Spell Focus", 95, _C.MAGICAL)
    ILLUSION_SPELL_FOCUS                    = ("Illusion Spell Focus", 96, _C.MAGICAL)
    NECROMANCY_SPELL_FOCUS                  = ("Necromancy Spell Focus", 97, _C.MAGICAL)
    TRANSMUTATION_SPELL_FOCUS               = ("Transmutation Spell Focus", 98, _C.MAGICAL)
    WIZARDRY                                = ("Wizardry", 99, _C.MAGICAL)
    SPELL_FOCUS_MASTERY                     = ("Spell Focus Mastery", 100, _C.MAGICAL)
    FIRE_SPELL_LORE                         = ("Fire Spell Lore", 101, _C.MAGICAL)
    COLD_SPELL_LORE                         = ("Cold Spell Lore", 102, _C.MAGICAL)
    ELECTRIC_SPELL_LORE                     = ("Electric Spell Lore", 103, _C.MAGICAL)
    ACID_SPELL_LORE                         = ("Acid Spell Lore", 104, _C.MAGICAL)
    SONIC_SPELL_LORE                        = ("Sonic Spell Lore", 105, _C.MAGICAL)
    LIGHT_SPELL_LORE                        = ("Light Spell Lore", 106, _C.MAGICAL)
    FORCE_SPELL_LORE                        = ("Force Spell Lore", 107, _C.MAGICAL)
    NEGATIVE_SPELL_LORE                     = ("Negative Spell Lore", 108, _C.MAGICAL)
    POSITIVE_SPELL_LORE                     = ("Positive Spell Lore", 109, _C.MAGICAL)
    REPAIR_SPELL_LORE                       = ("Repair Spell Lore", 110, _C.MAGICAL)
    UNIVERSAL_SPELL_LORE                    = ("Universal Spell Lore", 111, _C.MAGICAL)
    SPELL_LORE                              = ("Spell Lore", 112, _C.MAGICAL)
    SACRED_GROUND_LORE                      = ("Sacred Ground Lore", 113, _C.MAGICAL)
    DARK_RESTORATION_LORE                   = ("Dark Restoration Lore", 114, _C.MAGICAL)
    RUNE_ARM_SPELL_FOCUS                    = ("Rune Arm Spell Focus", 126, _C.MAGICAL)
    MAXIMUM_SPELL_POINTS                    = ("Maximum Spell Points", 131, _C.MAGICAL)
    POSITIVE_AND_NEGATIVE_SPELL_POWER       = ("Positive and Negative Spell Power", 136, _C.MAGICAL)
    POISON_SPELL_POWER                      = ("Poison Spell Power", 140, _C.MAGICAL)
    UNIVERSAL_SPELL_FOCUS                   = ("Universal Spell Focus", 162, _C.MAGICAL)
    BREATH_WEAPON_SPELL_FOCUS               = ("Breath Weapon Spell Focus", 163, _C.MAGICAL)
    POTENCY                                 = ("Potency", 178, _C.MAGICAL)
    RUNE_ARM_DC                             = ("Rune Arm DC", 196, _C.MAGICAL)
    SPELL_CRITICAL_DAMAGE                   = ("Spell Critical Damage", 201, _C.MAGICAL)
    SPELL_POINT_COST_REDUCTION              = ("Spell Point Cost Reduction", 206, _C.MAGICAL)
    SPELL_DCS                               = ("Spell DCs", 209, _C.MAGICAL)
    UNIVERSAL_SPELL_CRITICAL_DAMAGE         = ("Universal Spell Critical Damage", 212, _C.MAGICAL)
    POISON_SPELL_LORE                       = ("Poison Spell Lore", 216, _C.MAGICAL)
    CHAOS_SPELL_POWER                       = ("Chaos Spell Power", 218, _C.MAGICAL)
    CHAOS_SPELL_LORE                        = ("Chaos Spell Lore", 219, _C.MAGICAL)
    GOOD_SPELL_POWER                        = ("Good Spell Power", 220, _C.MAGICAL)
    GOOD_SPELL_LORE                         = ("Good Spell Lore", 221, _C.MAGICAL)
    EVIL_SPELL_POWER                        = ("Evil Spell Power", 222, _C.MAGICAL)
    EVIL_SPELL_LORE                         = ("Evil Spell Lore", 223, _C.MAGICAL)
    LAW_SPELL_POWER                         = ("Law Spell Power", 224, _C.MAGICAL)
    LAW_SPELL_LORE                          = ("Law Spell Lore", 225, _C.MAGICAL)
    DIVINATION_SPELL_FOCUS                  = ("Divination Spell Focus", 233, _C.MAGICAL)

    # --- Skills (also appear as stat rows with category='skill') ---
    BALANCE                                 = ("Balance", 41, _C.SKILL)
    BLUFF                                   = ("Bluff", 42, _C.SKILL)
    CONCENTRATION                           = ("Concentration", 43, _C.SKILL)
    DIPLOMACY                               = ("Diplomacy", 44, _C.SKILL)
    DISABLE_DEVICE                          = ("Disable Device", 45, _C.SKILL)
    HAGGLE                                  = ("Haggle", 46, _C.SKILL)
    HEAL                                    = ("Heal", 47, _C.SKILL)
    HIDE                                    = ("Hide", 48, _C.SKILL)
    INTIMIDATE                              = ("Intimidate", 49, _C.SKILL)
    JUMP                                    = ("Jump", 50, _C.SKILL)
    LISTEN                                  = ("Listen", 51, _C.SKILL)
    MOVE_SILENTLY                           = ("Move Silently", 52, _C.SKILL)
    OPEN_LOCK                               = ("Open Lock", 53, _C.SKILL)
    PERFORM                                 = ("Perform", 54, _C.SKILL)
    REPAIR                                  = ("Repair", 55, _C.SKILL)
    SEARCH                                  = ("Search", 56, _C.SKILL)
    SPELLCRAFT                              = ("Spellcraft", 57, _C.SKILL)
    SPOT                                    = ("Spot", 58, _C.SKILL)
    SWIM                                    = ("Swim", 59, _C.SKILL)
    TUMBLE                                  = ("Tumble", 60, _C.SKILL)
    USE_MAGIC_DEVICE                        = ("Use Magic Device", 61, _C.SKILL)
    LINGUISTICS                             = ("Linguistics", 127, _C.SKILL)
    COMMAND                                 = ("Command", 210, _C.SKILL)
    PERSUASION                              = ("Persuasion", 211, _C.SKILL)

    # --- Other ---
    HEALING_AMPLIFICATION                   = ("Healing Amplification", 73, _C.OTHER)
    REPAIR_AMPLIFICATION                    = ("Repair Amplification", 74, _C.OTHER)
    WELL_ROUNDED                            = ("Well Rounded", 75, _C.OTHER)
    POSITIVE_HEALING_AMPLIFICATION          = ("Positive Healing Amplification", 129, _C.OTHER)
    NEGATIVE_HEALING_AMPLIFICATION          = ("Negative Healing Amplification", 130, _C.OTHER)
    POSITIVE_AND_NEGATIVE_HEALING_AMP       = ("Positive and Negative Healing Amplification", 137, _C.OTHER)
    BARD_SONGS                              = ("Bard Songs", 143, _C.OTHER)
    MOVEMENT_SPEED                          = ("Movement Speed", 144, _C.OTHER)
    QUALITY                                 = ("Quality", 236, _C.OTHER)


class Skill(str, Enum):
    """DDO skill names with DB seed attributes (id, key_ability_id)."""

    def __new__(cls, value: str, id: int, key_ability_id: int) -> Skill:
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.id = id
        obj.key_ability_id = key_ability_id
        return obj

    def __str__(self) -> str: return self.value

    BALANCE          = ("Balance", 1, 2)          # DEX
    BLUFF            = ("Bluff", 2, 6)             # CHA
    CONCENTRATION    = ("Concentration", 3, 3)     # CON
    DIPLOMACY        = ("Diplomacy", 4, 6)         # CHA
    DISABLE_DEVICE   = ("Disable Device", 5, 4)    # INT
    HAGGLE           = ("Haggle", 6, 6)            # CHA
    HEAL_SKILL       = ("Heal", 7, 5)              # WIS
    HIDE_SKILL       = ("Hide", 8, 2)              # DEX
    INTIMIDATE_SKILL = ("Intimidate", 9, 6)        # CHA
    JUMP             = ("Jump", 10, 1)             # STR
    LISTEN           = ("Listen", 11, 5)           # WIS
    MOVE_SILENTLY    = ("Move Silently", 12, 2)    # DEX
    OPEN_LOCK        = ("Open Lock", 13, 2)        # DEX
    PERFORM_SKILL    = ("Perform", 14, 6)          # CHA
    REPAIR_SKILL     = ("Repair", 15, 4)           # INT
    SEARCH_SKILL     = ("Search", 16, 4)           # INT
    SPELLCRAFT       = ("Spellcraft", 17, 4)       # INT
    SPOT_SKILL       = ("Spot", 18, 5)             # WIS
    SWIM             = ("Swim", 19, 1)             # STR
    TUMBLE           = ("Tumble", 20, 2)           # DEX
    USE_MAGIC_DEVICE = ("Use Magic Device", 21, 6) # CHA


class BonusType(str, Enum):
    """Bonus type names with DB seed attributes (id, stacks_with_self)."""

    def __new__(cls, value: str, id: int, stacks_with_self: bool) -> BonusType:
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.id = id
        obj.stacks_with_self = stacks_with_self
        return obj

    def __str__(self) -> str: return self.value

    ENHANCEMENT    = ("Enhancement", 1, False)
    COMPETENCE     = ("Competence", 2, False)
    INSIGHT        = ("Insight", 3, False)
    SACRED         = ("Sacred", 4, False)
    PROFANE        = ("Profane", 5, False)
    LUCK           = ("Luck", 6, False)
    MORALE         = ("Morale", 7, False)
    ALCHEMICAL     = ("Alchemical", 8, False)
    DODGE_BT       = ("Dodge", 9, True)      # dodge bonuses stack
    ARMOR_BT       = ("Armor", 10, False)
    NATURAL_ARMOR_BT = ("Natural Armor", 11, False)
    DEFLECTION     = ("Deflection", 12, False)
    SHIELD_BT      = ("Shield", 13, False)
    SIZE           = ("Size", 14, False)
    RACIAL_BT      = ("Racial", 15, False)
    RESISTANCE_BT  = ("Resistance", 16, False)
    FESTIVE        = ("Festive", 17, False)
    EXCEPTIONAL    = ("Exceptional", 18, False)
    QUALITY_BT     = ("Quality", 19, False)
    ARTIFACT       = ("Artifact", 20, False)
    INHERENT       = ("Inherent", 21, False)
    STACKING       = ("Stacking", 22, True)  # stacking bonuses stack
    RAGE           = ("Rage", 23, False)
    PRIMAL         = ("Primal", 24, False)
    DETERMINATION  = ("Determination", 25, False)
    IMPLEMENT      = ("Implement", 26, False)
    MUSIC          = ("Music", 27, False)
    EQUIPMENT      = ("Equipment", 28, False)


class DamageType(str, Enum):
    """Damage type names with DB seed attributes (id, category)."""

    def __new__(cls, value: str, id: int, category: DamageCategory) -> DamageType:
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.id = id
        obj.category = category
        return obj

    def __str__(self) -> str: return self.value

    SLASHING   = ("Slashing", 1, _DC.PHYSICAL)
    PIERCING   = ("Piercing", 2, _DC.PHYSICAL)
    BLUDGEONING = ("Bludgeoning", 3, _DC.PHYSICAL)
    FIRE       = ("Fire", 4, _DC.ELEMENTAL)
    COLD       = ("Cold", 5, _DC.ELEMENTAL)
    ELECTRIC   = ("Electric", 6, _DC.ELEMENTAL)
    ACID       = ("Acid", 7, _DC.ELEMENTAL)
    SONIC      = ("Sonic", 8, _DC.ELEMENTAL)
    GOOD       = ("Good", 9, _DC.ALIGNMENT)
    EVIL       = ("Evil", 10, _DC.ALIGNMENT)
    LAWFUL     = ("Lawful", 11, _DC.ALIGNMENT)
    CHAOTIC    = ("Chaotic", 12, _DC.ALIGNMENT)
    NEGATIVE   = ("Negative", 13, _DC.ENERGY)
    POSITIVE   = ("Positive", 14, _DC.ENERGY)
    FORCE      = ("Force", 15, _DC.ENERGY)
    LIGHT      = ("Light", 16, _DC.ENERGY)
    POISON     = ("Poison", 17, _DC.ENERGY)
    UNTYPED    = ("Untyped", 18, _DC.UNTYPED)


class EquipmentSlot(str, Enum):
    """Equipment slot with DB seed attributes (id, sort_order, category)."""

    def __new__(cls, value: str, id: int, sort_order: int, category: SlotCategory) -> EquipmentSlot:
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.id = id
        obj.sort_order = sort_order
        obj.category = category
        return obj

    def __str__(self) -> str: return self.value

    MAIN_HAND = ("Main Hand", 1, 1, _SC.WEAPON)
    OFF_HAND  = ("Off Hand", 2, 2, _SC.WEAPON)
    RANGED    = ("Ranged", 3, 3, _SC.WEAPON)
    QUIVER    = ("Quiver", 4, 4, _SC.WEAPON)
    HEAD      = ("Head", 5, 5, _SC.ARMOR)
    NECK      = ("Neck", 6, 6, _SC.ACCESSORY)
    TRINKET   = ("Trinket", 7, 7, _SC.ACCESSORY)
    BACK      = ("Back", 8, 8, _SC.ARMOR)
    WRISTS    = ("Wrists", 9, 9, _SC.ARMOR)
    ARMS      = ("Arms", 10, 10, _SC.ARMOR)
    BODY      = ("Body", 11, 11, _SC.ARMOR)
    WAIST     = ("Waist", 12, 12, _SC.ARMOR)
    FEET      = ("Feet", 13, 13, _SC.ARMOR)
    GOGGLES   = ("Goggles", 14, 14, _SC.ACCESSORY)
    RING      = ("Ring", 15, 15, _SC.ACCESSORY)
    RUNEARM   = ("Runearm", 16, 16, _SC.WEAPON)


# ---------------------------------------------------------------------------
# ID-bearing enums — carry just the DB primary key
# ---------------------------------------------------------------------------

class Class(str, Enum):
    """DDO base class names with DB id."""

    def __new__(cls, value: str, id: int) -> Class:
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.id = id
        return obj

    def __str__(self) -> str: return self.value

    BARBARIAN    = ("Barbarian", 1)
    BARD         = ("Bard", 2)
    CLERIC       = ("Cleric", 3)
    FIGHTER      = ("Fighter", 4)
    PALADIN      = ("Paladin", 5)
    RANGER       = ("Ranger", 6)
    ROGUE        = ("Rogue", 7)
    SORCERER     = ("Sorcerer", 8)
    WIZARD       = ("Wizard", 9)
    MONK         = ("Monk", 10)
    FAVORED_SOUL = ("Favored Soul", 11)
    ARTIFICER    = ("Artificer", 12)
    DRUID        = ("Druid", 13)
    WARLOCK      = ("Warlock", 14)
    ALCHEMIST    = ("Alchemist", 15)


class Archetype(str, Enum):
    """DDO archetype names with DB id."""

    def __new__(cls, value: str, id: int) -> Archetype:
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.id = id
        return obj

    def __str__(self) -> str: return self.value

    DRAGON_LORD          = ("Dragon Lord", 16)
    DRAGON_DISCIPLE      = ("Dragon Disciple", 17)
    ARCANE_TRICKSTER     = ("Arcane Trickster", 18)
    WILD_MAGE            = ("Wild Mage", 19)
    STORMSINGER          = ("Stormsinger", 20)
    DARK_APOSTATE        = ("Dark Apostate", 21)
    BLIGHTCASTER         = ("Blightcaster", 22)
    SACRED_FIST          = ("Sacred Fist", 23)
    DARK_HUNTER          = ("Dark Hunter", 24)
    ACOLYTE_OF_THE_SKIN  = ("Acolyte of the Skin", 25)


class Race(str, Enum):
    """DDO race names with DB id."""

    def __new__(cls, value: str, id: int) -> Race:
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.id = id
        return obj

    def __str__(self) -> str: return self.value

    # Free races
    HUMAN              = ("Human", 1)
    ELF                = ("Elf", 2)
    DWARF              = ("Dwarf", 3)
    HALFLING           = ("Halfling", 4)
    WARFORGED          = ("Warforged", 5)
    DROW_ELF           = ("Drow Elf", 6)
    HALF_ELF           = ("Half-Elf", 7)
    HALF_ORC           = ("Half-Orc", 8)
    GNOME              = ("Gnome", 9)
    DRAGONBORN         = ("Dragonborn", 10)
    TIEFLING           = ("Tiefling", 11)
    WOOD_ELF           = ("Wood Elf", 12)
    # Premium races
    AASIMAR            = ("Aasimar", 13)
    TABAXI             = ("Tabaxi", 14)
    SHIFTER            = ("Shifter", 15)
    ELADRIN            = ("Eladrin", 16)
    DHAMPIR            = ("Dhampir", 17)
    # Iconic races
    BLADEFORGED            = ("Bladeforged", 18)
    PURPLE_DRAGON_KNIGHT   = ("Purple Dragon Knight", 19)
    MORNINGLORD            = ("Morninglord", 20)
    SHADAR_KAI             = ("Shadar-kai", 21)
    DEEP_GNOME             = ("Deep Gnome", 22)
    AASIMAR_SCOURGE        = ("Aasimar Scourge", 23)
    RAZORCLAW_SHIFTER      = ("Razorclaw Shifter", 24)
    TIEFLING_SCOUNDREL     = ("Tiefling Scoundrel", 25)
    TABAXI_TRAILBLAZER     = ("Tabaxi Trailblazer", 26)
    ELADRIN_CHAOSMANCER    = ("Eladrin Chaosmancer", 27)
    DHAMPIR_DARK_BARGAINER = ("Dhampir Dark Bargainer", 28)


# ---------------------------------------------------------------------------
# Simple enums (no DB seed attributes)
# ---------------------------------------------------------------------------

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


class ProficiencyCategory(str, Enum):
    """Weapon proficiency category."""
    def __str__(self) -> str: return self.value
    SIMPLE = "simple"
    MARTIAL = "martial"
    EXOTIC = "exotic"


class AbilityModSource(str, Enum):
    """Race ability modifier source."""
    def __str__(self) -> str: return self.value
    INNATE = "innate"
    ENHANCEMENT = "enhancement"


class SlotTier(str, Enum):
    """Feat/bonus slot tier."""
    def __str__(self) -> str: return self.value
    HEROIC = "heroic"
    EPIC = "epic"
    LEGENDARY = "legendary"
    DESTINY = "destiny"


class ApPool(str, Enum):
    """Action point pool type."""
    def __str__(self) -> str: return self.value
    HEROIC = "heroic"
    RACIAL = "racial"
    REAPER = "reaper"
    LEGENDARY = "legendary"


class LinkType(str, Enum):
    """Enhancement/spell link type."""
    def __str__(self) -> str: return self.value
    REQUIRES = "requires"
    GRANTS = "grants"
    EXCLUDES = "excludes"
    MODIFIES = "modifies"


class SaveType(str, Enum):
    """Saving throw type."""
    def __str__(self) -> str: return self.value
    FORTITUDE = "Fortitude"
    REFLEX = "Reflex"
    WILL = "Will"


class SaveEffect(str, Enum):
    """Saving throw effect on success."""
    def __str__(self) -> str: return self.value
    NEGATES = "negates"
    HALF = "half"
    PARTIAL = "partial"
    SPECIAL = "special"


class AffixType(str, Enum):
    """Crafting enchantment slot position."""
    def __str__(self) -> str: return self.value
    PREFIX = "prefix"
    SUFFIX = "suffix"
    EXTRA = "extra"


class CraftingSystem(str, Enum):
    """Named crafting systems with DB id."""

    def __new__(cls, value: str, id: int) -> CraftingSystem:
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.id = id
        return obj

    def __str__(self) -> str: return self.value

    # Level 1+
    CANNITH = ("Cannith Crafting", 1)
    AUGMENT_SLOT = ("Augment Slot", 2)
    DECK_OF_MANY_CURSES = ("Deck of Many Curses", 3)
    REAPER_FORGE = ("Reaper Forge", 4)
    STONE_OF_CHANGE = ("Stone of Change", 5)
    # Level 4+
    CHALLENGES = ("Challenges", 6)
    TRAPMAKING = ("Trapmaking", 7)
    CAULDRON_OF_CADENCE = ("Cauldron of Cadence", 8)
    # Level 8+
    DAMPENED = ("Dampened", 9)
    SLAVE_LORDS = ("Slave Lords", 10)
    VIKTRANIUM = ("Viktranium Experiment", 11)
    # Level 11+
    GREEN_STEEL = ("Green Steel", 12)
    ALCHEMICAL = ("Alchemical", 13)
    CAULDRON_OF_SORA_KATRA = ("Cauldron of Sora Katra", 14)
    # Level 14+
    DRAGONSCALE = ("Dragonscale Armor", 15)
    STORMREAVER = ("Stormreaver Monument", 16)
    TRACE_OF_MADNESS = ("Trace of Madness", 17)
    # Level 15+
    FOUNTAIN_OF_NECROTIC_MIGHT = ("Fountain of Necrotic Might", 18)
    NEARLY_FINISHED = ("Nearly Finished", 19)
    # Level 16+
    DRAGONTOUCHED = ("Dragontouched Armor", 20)
    # Level 18+
    INCREDIBLE_POTENTIAL = ("Incredible Potential", 21)
    SUPPRESSED_POWER = ("Suppressed Power", 22)
    LOST_PURPOSE = ("Lost Purpose", 23)
    UNHOLY_DEFILER = ("Unholy Defiler of the Hidden Hand", 24)
    # Level 20+
    EPIC_CRAFTING = ("Epic Crafting", 25)
    SENTIENT_WEAPON = ("Sentient Weapon", 26)
    # Level 22+
    MIKROM_SUM = ("Mikrom Sum", 27)
    THUNDER_FORGED = ("Thunder-Forged", 28)
    # Level 26+
    LEGENDARY_GREEN_STEEL = ("Legendary Green Steel", 29)
    ZHENTARIM = ("Zhentarim Attuned", 30)
    # Level 28+
    SCHISM_SHARD = ("Schism Shard", 31)
    # Level 30+
    LEGENDARY_CRAFTING = ("Legendary Crafting", 32)
    NEBULA_FRAGMENT = ("Nebula Fragment", 33)
    SOULFORGE = ("Soulforge", 34)
    DINOSAUR_BONE = ("Dinosaur Bone", 35)
    ESOTERIC_TABLE = ("Esoteric Table", 36)
    RITUAL_TABLE = ("Ritual Table", 37)
    AUGMENTATION_ALTAR = ("Augmentation Altar", 38)


class CraftingParam(str, Enum):
    """Parameterized crafting enchantment type."""
    def __str__(self) -> str: return self.value
    ABILITY = "ability"          # choose which ability score
    SKILL = "skill"              # choose which skill
    ELEMENT = "element"          # choose which damage element
    SCHOOL = "school"            # choose which spell school
    CREATURE = "creature"        # choose which creature type (bane)
    SAVE = "save"                # choose which save (Fort/Ref/Will)
    ALIGNMENT = "alignment"      # choose which alignment (Good/Evil/Law/Chaos)
