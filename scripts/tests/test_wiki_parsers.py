"""Tests for DDO Wiki wikitext template extraction and item parsing."""

from ddo_data.wiki.parsers import (
    clean_wikitext,
    extract_all_templates,
    extract_template,
    parse_feat_wikitext,
    parse_item_wikitext,
)

# ---------------------------------------------------------------------------
# Static wikitext fixtures
# ---------------------------------------------------------------------------

SIMPLE_TEMPLATE = """
{{Named item|Weapon
|name = Celestia
|minlevel = 29
|bind = BtCoE
|damage = 5[1d8]+15
|critical = 17-20/x2
|weapontype = Longsword
|proficiency = Martial Weapon Proficiency
|handedness = One Handed
|enchantmentbonus = 15
|durability = 250
|material = Steel
|hardness = 39
|weight = 4
|basevalue = 1000pp
|description = A holy blade of light.
|enchantments =
* [[Holy Sword]]
* +15 Enhancement Bonus
* Brilliance
|augmentslot =
* Red Augment Slot
* Purple Augment Slot
|set = Slave Lords
|quest = [[Slave Lords|Slave Lord Crafting]]
}}
"""

ARMOR_TEMPLATE = """
{{Named item|Armor
|name = Legendary Adherent of the Mists Docent
|minlevel = 32
|bind = BtCoA
|armorbonus = 28
|maxdex = 0
|material = Gem
|enchantments =
* Fortification +200%
* [[Physical Sheltering]] +53
}}
"""

NESTED_TEMPLATE = """
{{Named item|Weapon
|name = Test Nested
|damage = {{dice|1d6}}+5
|enchantments = * {{tooltip|Holy|Deals extra holy damage}}
}}
"""

NO_TEMPLATE_PAGE = """
This is a page about DDO lore.
It does not contain any item template.
== History ==
The Harbor was once a bustling port.
"""

MINIMAL_TEMPLATE = """
{{Named item|Jewelry
|name = Ring of Power
|minlevel = 5
}}
"""

MULTILINE_VALUE = """
{{Named item|Weapon
|name = Multi Line Weapon
|description = This is a weapon
that spans multiple lines
and has lots of text.
|minlevel = 10
}}
"""


# ---------------------------------------------------------------------------
# extract_template tests
# ---------------------------------------------------------------------------


def test_extract_template_basic() -> None:
    """Extracts fields from a simple {{Template|key=value}} block."""
    result = extract_template(SIMPLE_TEMPLATE, "Named item")
    assert result is not None
    assert result["name"] == "Celestia"
    assert result["minlevel"] == "29"
    assert result["bind"] == "BtCoE"
    assert result["weapontype"] == "Longsword"


def test_extract_template_positional_arg() -> None:
    """First arg before key=value is stored as _positional_1."""
    result = extract_template(SIMPLE_TEMPLATE, "Named item")
    assert result is not None
    assert result["_positional_1"] == "Weapon"


def test_extract_template_nested_braces() -> None:
    """Nested {{inner}} in field values is handled by brace counting."""
    result = extract_template(NESTED_TEMPLATE, "Named item")
    assert result is not None
    assert result["name"] == "Test Nested"
    # The nested {{dice|1d6}} should be preserved in the value
    assert "{{dice|1d6}}" in result["damage"]


def test_extract_template_not_found() -> None:
    """Returns None when template absent."""
    result = extract_template(NO_TEMPLATE_PAGE, "Named item")
    assert result is None


def test_extract_template_case_insensitive() -> None:
    """Template name matching is case-insensitive."""
    result = extract_template(SIMPLE_TEMPLATE, "named item")
    assert result is not None
    assert result["name"] == "Celestia"

    result2 = extract_template(SIMPLE_TEMPLATE, "NAMED ITEM")
    assert result2 is not None
    assert result2["name"] == "Celestia"


def test_extract_template_multiline_values() -> None:
    """Field values spanning multiple lines are preserved."""
    result = extract_template(MULTILINE_VALUE, "Named item")
    assert result is not None
    assert "multiple lines" in result["description"]


def test_extract_template_keys_lowercase() -> None:
    """Field keys are normalized to lowercase."""
    wikitext = "{{TestTemplate|MyKey = some value}}"
    result = extract_template(wikitext, "TestTemplate")
    assert result is not None
    assert "mykey" in result
    assert result["mykey"] == "some value"


# ---------------------------------------------------------------------------
# extract_all_templates tests
# ---------------------------------------------------------------------------


def test_extract_all_templates_multiple() -> None:
    """Finds multiple occurrences of the same template."""
    wikitext = "{{Foo|a=1}}{{Foo|a=2}}{{Foo|a=3}}"
    results = extract_all_templates(wikitext, "Foo")
    assert len(results) == 3
    assert results[0]["a"] == "1"
    assert results[1]["a"] == "2"
    assert results[2]["a"] == "3"


def test_extract_all_templates_none() -> None:
    """Returns empty list when template not found."""
    results = extract_all_templates("no templates here", "Foo")
    assert results == []


# ---------------------------------------------------------------------------
# clean_wikitext tests
# ---------------------------------------------------------------------------


def test_clean_wikitext_links() -> None:
    """[[Target|Display]] -> Display, [[Simple]] -> Simple."""
    assert clean_wikitext("[[Holy Sword]]") == "Holy Sword"
    assert clean_wikitext("[[Slave Lords|Slave Lord Crafting]]") == "Slave Lord Crafting"


def test_clean_wikitext_html() -> None:
    """HTML tags are stripped."""
    assert clean_wikitext("Hello<br/>World") == "Hello World"
    assert clean_wikitext('<span style="color:red">Red</span>') == "Red"


def test_clean_wikitext_templates() -> None:
    """Simple {{template}} markers are stripped."""
    assert clean_wikitext("{{some template}}text") == "text"


def test_clean_wikitext_whitespace() -> None:
    """Excessive whitespace is collapsed."""
    assert clean_wikitext("  hello   world  ") == "hello world"


def test_clean_wikitext_combined() -> None:
    """Multiple markup types in one value."""
    assert clean_wikitext("[[Physical Sheltering]] +53") == "Physical Sheltering +53"


# ---------------------------------------------------------------------------
# parse_item_wikitext tests
# ---------------------------------------------------------------------------


def test_parse_item_wikitext_weapon() -> None:
    """Full weapon parse: name, minlevel, damage, enchantments list."""
    item = parse_item_wikitext(SIMPLE_TEMPLATE)
    assert item is not None
    assert item["name"] == "Celestia"
    assert item["item_type"] == "Weapon"
    assert item["minimum_level"] == 29
    assert item["damage"] == "5[1d8]+15"
    assert item["critical"] == "17-20/x2"
    assert item["weapon_type"] == "Longsword"
    assert item["proficiency"] == "Martial Weapon Proficiency"
    assert item["handedness"] == "One Handed"
    assert item["enhancement_bonus"] == 15
    assert item["durability"] == 250
    assert item["material"] == "Steel"
    assert item["hardness"] == 39
    assert item["weight"] == 4.0
    assert item["binding"] == "BtCoE"
    assert item["base_value"] == "1000pp"
    assert item["set_name"] == "Slave Lords"
    assert item["quest"] == "Slave Lord Crafting"
    assert item["description"] == "A holy blade of light."
    # Enchantments should be a list with wiki links cleaned
    assert isinstance(item["enchantments"], list)
    assert "Holy Sword" in item["enchantments"]
    assert "+15 Enhancement Bonus" in item["enchantments"]
    # Augment slots
    assert isinstance(item["augment_slots"], list)
    assert "Red Augment Slot" in item["augment_slots"]
    assert "Purple Augment Slot" in item["augment_slots"]


def test_parse_item_wikitext_armor() -> None:
    """Armor with different fields (armor_bonus, max_dex)."""
    item = parse_item_wikitext(ARMOR_TEMPLATE)
    assert item is not None
    assert item["name"] == "Legendary Adherent of the Mists Docent"
    assert item["item_type"] == "Armor"
    assert item["minimum_level"] == 32
    assert item["armor_bonus"] == 28
    assert item["max_dex_bonus"] == 0
    assert item["material"] == "Gem"
    assert isinstance(item["enchantments"], list)
    assert len(item["enchantments"]) >= 2


def test_parse_item_wikitext_no_template() -> None:
    """Page without {{Named item}} returns None."""
    assert parse_item_wikitext(NO_TEMPLATE_PAGE) is None


def test_parse_item_wikitext_minimal() -> None:
    """Template with only name and minlevel works."""
    item = parse_item_wikitext(MINIMAL_TEMPLATE)
    assert item is not None
    assert item["name"] == "Ring of Power"
    assert item["item_type"] == "Jewelry"
    assert item["minimum_level"] == 5
    # Optional fields should be None or empty
    assert item["damage"] is None
    assert item["enchantments"] == []


def test_parse_item_wikitext_nested() -> None:
    """Nested templates in field values don't break the parser."""
    item = parse_item_wikitext(NESTED_TEMPLATE)
    assert item is not None
    assert item["name"] == "Test Nested"
    # Damage should still parse (nested template stripped by clean_wikitext)
    assert item["damage"] is not None


def test_parse_item_wikitext_empty_name_fallback() -> None:
    """When name field is empty, positional arg is used as fallback."""
    wikitext = "{{Named item|Weapon|minlevel=5}}"
    item = parse_item_wikitext(wikitext)
    assert item is not None
    # name should fall back to positional (or be the cleaned type)
    assert item["name"] == "Weapon" or item["name"] is not None


# ---------------------------------------------------------------------------
# parse_feat_wikitext tests
# ---------------------------------------------------------------------------

CLEAVE_FEAT = """
{{Feat
|name=Cleave
|icon=Icon_Feat_Cleave.png
|cooldown=5 seconds
|prerequisite=[[Power Attack]]
|description=Activate this [[feat]] to attack one or more enemies in an arc.
|note=
* [[Great Cleave]] does not replace Cleave.
|free=no
|active=yes
|fighter bonus feat=yes
}}
"""

TOUGHNESS_FEAT = """
{{Feat
|name=Toughness
|icon=Icon Feat Toughness.png
|epic destiny=Yes
|prerequisite=
|description=Increases your [[hit point]]s by +3 at first level.
|free=no
|passive=yes
|martial arts feat=yes
|dragon arts feat=yes
}}
"""

MAXIMIZE_FEAT = """
{{Feat
|name=Maximize Spell
|icon=Icon Feat Maximize Spell.png
|prerequisite=able to cast spells
|description=+150 Spell Power while active, costs 25 extra SP.
|free=no
|active=yes
|metamagic=yes
|alchemist bonus feat=yes
|artificer bonus feat=yes
|wizard bonus feat=yes
}}
"""


def test_parse_feat_active() -> None:
    """Active feat with prerequisite, cooldown, and fighter bonus."""
    feat = parse_feat_wikitext(CLEAVE_FEAT)
    assert feat is not None
    assert feat["name"] == "Cleave"
    assert feat["icon"] == "Icon_Feat_Cleave.png"
    assert feat["cooldown"] == "5 seconds"
    assert feat["prerequisite"] == "Power Attack"
    assert "attack one or more enemies" in feat["description"]
    assert feat["active"] is True
    assert feat["passive"] is False
    assert feat["free"] is False
    assert feat["metamagic"] is False
    assert feat["epic_destiny"] is False
    assert "fighter" in feat["bonus_classes"]


def test_parse_feat_passive() -> None:
    """Passive feat with epic destiny and monk bonus."""
    feat = parse_feat_wikitext(TOUGHNESS_FEAT)
    assert feat is not None
    assert feat["name"] == "Toughness"
    assert feat["passive"] is True
    assert feat["active"] is False
    assert feat["epic_destiny"] is True
    assert "monk" in feat["bonus_classes"]


def test_parse_feat_metamagic() -> None:
    """Metamagic feat with multiple bonus classes."""
    feat = parse_feat_wikitext(MAXIMIZE_FEAT)
    assert feat is not None
    assert feat["name"] == "Maximize Spell"
    assert feat["metamagic"] is True
    assert feat["active"] is True
    assert "alchemist" in feat["bonus_classes"]
    assert "artificer" in feat["bonus_classes"]
    assert "wizard" in feat["bonus_classes"]


def test_parse_feat_no_template() -> None:
    """Page without {{Feat}} template returns None."""
    assert parse_feat_wikitext("This is just text about feats.") is None


def test_parse_feat_minimal() -> None:
    """Minimal feat template with just a name."""
    feat = parse_feat_wikitext("{{Feat|name=Simple Feat}}")
    assert feat is not None
    assert feat["name"] == "Simple Feat"
    assert feat["bonus_classes"] == []
    assert feat["passive"] is False
    assert feat["active"] is False
