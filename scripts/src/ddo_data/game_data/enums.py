"""DDO enum constants for game data parsing.

Mappings from integer codes found in binary game entries to human-readable
labels.  These are inferred from statistical distribution analysis across
76,000+ entries and may need refinement as more data is examined.
"""

from __future__ import annotations

# Equipment slot codes (from property key 0x10001BA1)
# Values 2-17, with 6 (Weapon) and 16 (Offhand) most common.
EQUIPMENT_SLOTS: dict[int, str] = {
    2: "Helmet",
    3: "Necklace",
    4: "Trinket",
    5: "Cloak",
    6: "Weapon",
    7: "Ring",
    8: "Belt",
    9: "Boots",
    10: "Gloves",
    11: "Bracers",
    12: "Armor",
    13: "Shield",
    14: "Goggles",
    15: "Quiver",
    16: "Offhand",
    17: "Runearm",
}

# Rarity tiers (from property key 0x10000E29)
# Values 2-5 across 6401 entries.
RARITY_TIERS: dict[int, str] = {
    2: "Common",
    3: "Uncommon",
    4: "Rare",
    5: "Epic",
}

# Item category codes (from property key 0x10001C59)
# Values 1-12, dominated by 12 and 3.
ITEM_CATEGORIES: dict[int, str] = {
    1: "Armor",
    2: "Shield",
    3: "Weapon",
    4: "Jewelry",
    5: "Clothing",
    6: "Wondrous",
    7: "Potion",
    8: "Scroll",
    9: "Wand",
    10: "Component",
    11: "Collectible",
    12: "Consumable",
}


def resolve_enum(mapping: dict[int, str], value: int) -> str | None:
    """Look up an enum value, returning None if unknown."""
    return mapping.get(value)
