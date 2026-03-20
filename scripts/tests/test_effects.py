"""Tests for the effect entry census and wiki-correlation mapper."""

import struct

from ddo_data.dat_parser.effects import (
    EffectMapResult,
    build_effect_census,
    build_effect_map,
    format_effect_census,
    format_effect_map,
    parse_enchantment_string,
    _record_bonus_type_mapping,
    _record_stat_mapping,
    _correlate_item_effects,
)


# ---------------------------------------------------------------------------
# parse_enchantment_string tests
# ---------------------------------------------------------------------------


def test_parse_enchantment_string_standard():
    result = parse_enchantment_string("+7 Enhancement bonus to Strength")
    assert result == {"value": 7, "bonus_type": "Enhancement", "stat": "Strength"}


def test_parse_enchantment_string_insightful():
    """'Insightful' in wiki text maps to 'Insight' bonus type in DB."""
    result = parse_enchantment_string("+6 Insightful bonus to Constitution")
    assert result == {"value": 6, "bonus_type": "Insight", "stat": "Constitution"}


def test_parse_enchantment_string_multi_word_stat():
    result = parse_enchantment_string("+5 Enhancement bonus to Magical Resistance Rating")
    assert result == {"value": 5, "bonus_type": "Enhancement", "stat": "Magical Resistance Rating"}


def test_parse_enchantment_string_spell_power():
    result = parse_enchantment_string("+4 Quality bonus to Fire Spell Power")
    assert result == {"value": 4, "bonus_type": "Quality", "stat": "Fire Spell Power"}


def test_parse_enchantment_string_unparseable():
    assert parse_enchantment_string("Ghostly") is None


def test_parse_enchantment_string_deathblock():
    assert parse_enchantment_string("Deathblock") is None


def test_parse_enchantment_string_speed():
    assert parse_enchantment_string("Speed XV") is None


def test_parse_enchantment_string_competence():
    result = parse_enchantment_string("+11 Competence bonus to Haggle")
    assert result == {"value": 11, "bonus_type": "Competence", "stat": "Haggle"}


def test_parse_enchantment_string_whitespace():
    """Leading/trailing whitespace is trimmed."""
    result = parse_enchantment_string("  +3 Luck bonus to Spot  ")
    assert result == {"value": 3, "bonus_type": "Luck", "stat": "Spot"}


def test_parse_enchantment_string_saving_throws():
    result = parse_enchantment_string("+2 Resistance bonus to Saving Throws vs Traps")
    assert result == {"value": 2, "bonus_type": "Resistance", "stat": "Saving Throws vs Traps"}


# Wiki template format tests

def test_parse_stat_template_basic():
    """{{Stat|CON|13}} → +13 Enhancement bonus to Constitution."""
    result = parse_enchantment_string("{{Stat|CON|13}}")
    assert result == {"value": 13, "bonus_type": "Enhancement", "stat": "Constitution"}


def test_parse_stat_template_with_bonus_type():
    """{{Stat|INT|6|Insightful}} → +6 Insight bonus to Intelligence."""
    result = parse_enchantment_string("{{Stat|INT|6|Insightful}}")
    assert result == {"value": 6, "bonus_type": "Insight", "stat": "Intelligence"}


def test_parse_stat_template_quality():
    """{{Stat|STR|3|Quality}} → +3 Quality bonus to Strength."""
    result = parse_enchantment_string("{{Stat|STR|3|Quality}}")
    assert result == {"value": 3, "bonus_type": "Quality", "stat": "Strength"}


def test_parse_stat_template_well_rounded():
    """{{Stat|Well Rounded|2|Profane}} → +2 Profane bonus to Well Rounded."""
    result = parse_enchantment_string("{{Stat|Well Rounded|2|Profane}}")
    assert result == {"value": 2, "bonus_type": "Profane", "stat": "Well Rounded"}


def test_parse_sheltering_template():
    """{{Sheltering|33|Enhancement|Physical}} → Physical Sheltering."""
    result = parse_enchantment_string("{{Sheltering|33|Enhancement|Physical}}")
    assert result == {"value": 33, "bonus_type": "Enhancement", "stat": "Physical Sheltering"}


def test_parse_spellpower_template():
    """{{SpellPower|Devotion|30}} → +30 Positive Spell Power."""
    result = parse_enchantment_string("{{SpellPower|Devotion|30}}")
    assert result == {"value": 30, "bonus_type": "Enhancement", "stat": "Positive Spell Power"}


def test_parse_spellpower_combustion():
    """{{SpellPower|Combustion|30}} → +30 Fire Spell Power."""
    result = parse_enchantment_string("{{SpellPower|Combustion|30}}")
    assert result == {"value": 30, "bonus_type": "Enhancement", "stat": "Fire Spell Power"}


def test_parse_seeker_template():
    """{{Seeker|3}} → +3 Enhancement Seeker."""
    result = parse_enchantment_string("{{Seeker|3}}")
    assert result == {"value": 3, "bonus_type": "Enhancement", "stat": "Seeker"}


def test_parse_seeker_insightful():
    """{{Seeker|4|Insightful}} → +4 Insight Seeker."""
    result = parse_enchantment_string("{{Seeker|4|Insightful}}")
    assert result == {"value": 4, "bonus_type": "Insight", "stat": "Seeker"}


def test_parse_deadly_template():
    """{{Deadly|4|Insightful}} → +4 Insight Deadly."""
    result = parse_enchantment_string("{{Deadly|4|Insightful}}")
    assert result == {"value": 4, "bonus_type": "Insight", "stat": "Deadly"}


def test_parse_fortification_template():
    """{{Fortification|100}} → +100 Enhancement Fortification."""
    result = parse_enchantment_string("{{Fortification|100}}")
    assert result == {"value": 100, "bonus_type": "Enhancement", "stat": "Fortification"}


def test_parse_save_template():
    """{{Save|r|11}} → +11 Resistance Reflex Save."""
    result = parse_enchantment_string("{{Save|r|11}}")
    assert result == {"value": 11, "bonus_type": "Resistance", "stat": "Reflex Save"}


def test_parse_save_will():
    """{{Save|w|5}} → +5 Resistance Will Save."""
    result = parse_enchantment_string("{{Save|w|5}}")
    assert result == {"value": 5, "bonus_type": "Resistance", "stat": "Will Save"}


def test_parse_skills_template():
    """{{Skills|intim|3}} → +3 Enhancement Intimidate."""
    result = parse_enchantment_string("{{Skills|intim|3}}")
    assert result == {"value": 3, "bonus_type": "Enhancement", "stat": "Intimidate"}


def test_parse_skills_with_bonus_type():
    """{{Skills|Command|5|Insight}} → +5 Insight Intimidate."""
    result = parse_enchantment_string("{{Skills|Command|5|Insight}}")
    assert result == {"value": 5, "bonus_type": "Insight", "stat": "Intimidate"}


def test_parse_accuracy_template():
    """{{Accuracy|7}} → +7 Enhancement Accuracy."""
    result = parse_enchantment_string("{{Accuracy|7}}")
    assert result == {"value": 7, "bonus_type": "Enhancement", "stat": "Accuracy"}


def test_parse_deception_numeric():
    """{{Deception|3}} → +3 Enhancement Deception."""
    result = parse_enchantment_string("{{Deception|3}}")
    assert result == {"value": 3, "bonus_type": "Enhancement", "stat": "Deception"}


def test_parse_elemental_resistance_template():
    """{{Elemental Resistance|Acid|30}} → +30 Acid Resistance."""
    result = parse_enchantment_string("{{Elemental Resistance|Acid|30}}")
    assert result == {"value": 30, "bonus_type": "Enhancement", "stat": "Acid Resistance"}


def test_parse_absorption_template():
    """{{Absorption|Fire|26}} → +26 Fire Absorption."""
    result = parse_enchantment_string("{{Absorption|Fire|26}}")
    assert result == {"value": 26, "bonus_type": "Enhancement", "stat": "Fire Absorption"}


def test_parse_spell_focus_template():
    """{{Spell Focus|Abjuration|3}} → +3 Abjuration Spell Focus."""
    result = parse_enchantment_string("{{Spell Focus|Abjuration|3}}")
    assert result == {"value": 3, "bonus_type": "Enhancement", "stat": "Abjuration Spell Focus"}


def test_parse_hp_template():
    """{{Hp|Vitality|25}} → +25 Hit Points."""
    result = parse_enchantment_string("{{Hp|Vitality|25}}")
    assert result == {"value": 25, "bonus_type": "Enhancement", "stat": "Hit Points"}


def test_parse_healingamp_template():
    """{{HealingAmp|53|R}} → +53 Repair Amplification."""
    result = parse_enchantment_string("{{HealingAmp|53|R}}")
    assert result == {"value": 53, "bonus_type": "Enhancement", "stat": "Repair Amplification"}


def test_parse_healingamp_with_bonus_type():
    """{{HealingAmp|17|h|Competence}} → +17 Competence Healing Amplification."""
    result = parse_enchantment_string("{{HealingAmp|17|h|Competence}}")
    assert result == {"value": 17, "bonus_type": "Competence", "stat": "Healing Amplification"}


def test_parse_dodge_template():
    """{{Dodge|8}} → +8 Enhancement Dodge."""
    result = parse_enchantment_string("{{Dodge|8}}")
    assert result == {"value": 8, "bonus_type": "Enhancement", "stat": "Dodge"}


def test_parse_template_unrecognized():
    """Unrecognized templates return None."""
    assert parse_enchantment_string("{{Ghostly}}") is None
    assert parse_enchantment_string("{{Deathblock}}") is None
    assert parse_enchantment_string("{{Enhancement bonus|w|1}}") is None


# ---------------------------------------------------------------------------
# parse_effect_template tests
# ---------------------------------------------------------------------------

from ddo_data.dat_parser.effects import is_metadata_template, parse_effect_template


def test_parse_effect_simple_flag():
    """{{Vorpal}} → effect only, no modifier or value."""
    result = parse_effect_template("{{Vorpal}}")
    assert result == {"effect": "Vorpal", "modifier": None, "value": None}


def test_parse_effect_ranked_word():
    """{{Destruction|Improved}} → effect + word modifier."""
    result = parse_effect_template("{{Destruction|Improved}}")
    assert result == {"effect": "Destruction", "modifier": "Improved", "value": None}


def test_parse_effect_ranked_numeric():
    """{{Maiming|4}} → effect + numeric value."""
    result = parse_effect_template("{{Maiming|4}}")
    assert result == {"effect": "Maiming", "modifier": None, "value": 4}


def test_parse_effect_typed_with_value():
    """{{Bane|Evil Outsider|4}} → effect + modifier + value."""
    result = parse_effect_template("{{Bane|Evil Outsider|4}}")
    assert result == {"effect": "Bane", "modifier": "Evil Outsider", "value": 4}


def test_parse_effect_typed_element():
    """{{Blast|Acid|7}} → effect + element modifier + value."""
    result = parse_effect_template("{{Blast|Acid|7}}")
    assert result == {"effect": "Blast", "modifier": "Acid", "value": 7}


def test_parse_effect_sovereign_vorpal():
    """{{Vorpal|Sovereign}} → effect + word modifier."""
    result = parse_effect_template("{{Vorpal|Sovereign}}")
    assert result == {"effect": "Vorpal", "modifier": "Sovereign", "value": None}


def test_parse_effect_skips_nocat():
    """nocat=TRUE parameters are filtered out."""
    result = parse_effect_template("{{Vulnerability|Electric|nocat=TRUE}}")
    assert result == {"effect": "Vulnerability", "modifier": "Electric", "value": None}


def test_parse_effect_skips_metadata():
    """Metadata templates return None."""
    assert parse_effect_template("{{Augment|Red}}") is None
    assert parse_effect_template("{{Named item sets|Slave Lords}}") is None
    assert parse_effect_template("{{Mat|Adamantine}}") is None
    assert parse_effect_template("{{Enhancement bonus|w|5}}") is None


def test_parse_effect_catches_non_numeric_bonus_templates():
    """Non-numeric bonus template variants are caught as effects.

    In Pass B, parse_enchantment_string tries first (catches numeric ones);
    parse_effect_template catches the rest as weapon/armor effects.
    """
    # Numeric: parse_effect_template also parses these, but Pass B calls
    # parse_enchantment_string first, so no double-counting in practice.
    result = parse_effect_template("{{Concealment|Lesser Displacement}}")
    assert result == {"effect": "Concealment", "modifier": "Lesser Displacement", "value": None}
    result = parse_effect_template("{{Fortification|heavy}}")
    assert result == {"effect": "Fortification", "modifier": "heavy", "value": None}


def test_parse_effect_plain_text_returns_none():
    """Plain text without templates returns None."""
    assert parse_effect_template("Tier 1:") is None
    assert parse_effect_template("+15 Enhancement Bonus") is None


def test_is_metadata_template():
    """is_metadata_template identifies metadata templates."""
    assert is_metadata_template("{{Augment|Red}}") is True
    assert is_metadata_template("{{Named item sets|Foo}}") is True
    assert is_metadata_template("Tier 1:") is True
    assert is_metadata_template("Adds {{Augment|Purple|nocat=TRUE}}") is True
    assert is_metadata_template("{{Vorpal}}") is False
    assert is_metadata_template("{{Stat|STR|7}}") is False


# ---------------------------------------------------------------------------
# Effect Census tests
# ---------------------------------------------------------------------------


def _build_effect_entry(entry_type: int, stat_def_id: int, bonus_type_code: int, magnitude: int = 0) -> bytes:
    """Build a synthetic 0x70XXXXXX effect entry for testing.

    Layout matches decode_effect_entry expectations:
      bytes[5..8]  = entry_type (u32 LE)
      bytes[13..14] = bonus_type_code (u16 LE)
      bytes[16..17] = stat_def_id (u16 LE)
      bytes[68..71] = magnitude (u32 LE, only for entry_type=53)
    """
    # Build at least 72 bytes for type-53 entries
    buf = bytearray(80)
    struct.pack_into("<I", buf, 5, entry_type)
    struct.pack_into("<H", buf, 13, bonus_type_code)
    struct.pack_into("<H", buf, 16, stat_def_id)
    if entry_type == 0x35:
        struct.pack_into("<I", buf, 68, magnitude)
    return bytes(buf)


def test_effect_census_counts_entry_types(build_dat):
    """Census correctly histograms entry_type values."""
    from ddo_data.dat_parser.archive import DatArchive
    from ddo_data.dat_parser.extract import scan_file_table

    effect1 = _build_effect_entry(entry_type=0x35, stat_def_id=100, bonus_type_code=0x0100, magnitude=7)
    effect2 = _build_effect_entry(entry_type=0x35, stat_def_id=200, bonus_type_code=0x0200, magnitude=5)
    effect3 = _build_effect_entry(entry_type=0x11, stat_def_id=300, bonus_type_code=0x0000)

    dat_path = build_dat([
        (0x70000001, effect1),
        (0x70000002, effect2),
        (0x70000003, effect3),
    ])

    archive = DatArchive(dat_path)
    archive.read_header()
    entries = scan_file_table(archive)

    result = build_effect_census(archive, entries)

    assert result.total_effects == 3
    assert result.by_entry_type[0x35] == 2
    assert result.by_entry_type[0x11] == 1


def test_effect_census_stat_histogram(build_dat):
    """Census builds per-stat_def_id histogram for type-53 entries."""
    from ddo_data.dat_parser.archive import DatArchive
    from ddo_data.dat_parser.extract import scan_file_table

    effect1 = _build_effect_entry(entry_type=0x35, stat_def_id=100, bonus_type_code=0x0100, magnitude=7)
    effect2 = _build_effect_entry(entry_type=0x35, stat_def_id=100, bonus_type_code=0x0100, magnitude=3)
    effect3 = _build_effect_entry(entry_type=0x35, stat_def_id=200, bonus_type_code=0x0200, magnitude=5)

    dat_path = build_dat([
        (0x70000001, effect1),
        (0x70000002, effect2),
        (0x70000003, effect3),
    ])

    archive = DatArchive(dat_path)
    archive.read_header()
    entries = scan_file_table(archive)

    result = build_effect_census(archive, entries)

    assert result.type53_stat_histogram[100] == 2
    assert result.type53_stat_histogram[200] == 1
    assert result.type53_magnitude_range[100] == (3, 7)
    assert result.type53_magnitude_range[200] == (5, 5)


def test_effect_census_bonus_type_histogram(build_dat):
    """Census builds per-bonus_type_code histogram for type-53 entries."""
    from ddo_data.dat_parser.archive import DatArchive
    from ddo_data.dat_parser.extract import scan_file_table

    effect1 = _build_effect_entry(entry_type=0x35, stat_def_id=100, bonus_type_code=0x0100, magnitude=7)
    effect2 = _build_effect_entry(entry_type=0x35, stat_def_id=200, bonus_type_code=0x0200, magnitude=5)

    dat_path = build_dat([
        (0x70000001, effect1),
        (0x70000002, effect2),
    ])

    archive = DatArchive(dat_path)
    archive.read_header()
    entries = scan_file_table(archive)

    result = build_effect_census(archive, entries)

    assert result.type53_bonus_type_histogram[0x0100] == 1
    assert result.type53_bonus_type_histogram[0x0200] == 1


def test_effect_census_ignores_non_0x70(build_dat):
    """Census skips entries that aren't in the 0x70 namespace."""
    from ddo_data.dat_parser.archive import DatArchive
    from ddo_data.dat_parser.extract import scan_file_table

    effect = _build_effect_entry(entry_type=0x35, stat_def_id=100, bonus_type_code=0x0100, magnitude=7)
    non_effect = b"\x00" * 80

    dat_path = build_dat([
        (0x70000001, effect),
        (0x79000002, non_effect),  # gamelogic entry, not effect
    ])

    archive = DatArchive(dat_path)
    archive.read_header()
    entries = scan_file_table(archive)

    result = build_effect_census(archive, entries)

    assert result.total_effects == 1


def test_effect_census_format_output(build_dat):
    """format_effect_census produces readable output."""
    from ddo_data.dat_parser.archive import DatArchive
    from ddo_data.dat_parser.extract import scan_file_table

    effect = _build_effect_entry(entry_type=0x35, stat_def_id=100, bonus_type_code=0x0100, magnitude=7)

    dat_path = build_dat([(0x70000001, effect)])
    archive = DatArchive(dat_path)
    archive.read_header()
    entries = scan_file_table(archive)

    result = build_effect_census(archive, entries)
    text = format_effect_census(result)

    assert "Effect Entry Census" in text
    assert "entry_type=53" in text


# ---------------------------------------------------------------------------
# Correlation logic tests
# ---------------------------------------------------------------------------


def test_record_stat_mapping_new():
    """Recording a new stat mapping creates a fresh entry."""
    result = EffectMapResult()
    _record_stat_mapping(result, 100, "Strength")
    assert 100 in result.stat_mappings
    assert result.stat_mappings[100].stat_name == "Strength"
    assert result.stat_mappings[100].confirmations == 1
    assert result.stat_mappings[100].conflicts == 0


def test_record_stat_mapping_confirm():
    """Repeated same mapping increments confirmations."""
    result = EffectMapResult()
    _record_stat_mapping(result, 100, "Strength")
    _record_stat_mapping(result, 100, "Strength")
    _record_stat_mapping(result, 100, "Strength")
    assert result.stat_mappings[100].confirmations == 3
    assert result.stat_mappings[100].conflicts == 0


def test_record_stat_mapping_conflict():
    """Different stat name for same stat_def_id increments conflicts."""
    result = EffectMapResult()
    _record_stat_mapping(result, 100, "Strength")
    _record_stat_mapping(result, 100, "Dexterity")
    assert result.stat_mappings[100].confirmations == 1
    assert result.stat_mappings[100].conflicts == 1
    assert "Dexterity" in result.stat_mappings[100].conflict_names


def test_correlate_single_item():
    """Single item with 2 enchantments and 2 effects produces correct mappings."""
    result = EffectMapResult()

    parsed_enchantments = [
        {"value": 7, "bonus_type": "Enhancement", "stat": "Strength"},
        {"value": 5, "bonus_type": "Insight", "stat": "Constitution"},
    ]
    decoded_effects = [
        {"entry_type": 0x35, "stat_def_id": 100, "bonus_type_code": 0x0100, "magnitude": 7, "stat": None, "bonus_type": None},
        {"entry_type": 0x35, "stat_def_id": 200, "bonus_type_code": 0x0300, "magnitude": 5, "stat": None, "bonus_type": None},
    ]

    _correlate_item_effects(result, parsed_enchantments, decoded_effects)

    assert result.correlations_matched == 2
    assert result.stat_mappings[100].stat_name == "Strength"
    assert result.stat_mappings[200].stat_name == "Constitution"
    assert result.bonus_type_mappings[0x0100].bonus_type_name == "Enhancement"
    assert result.bonus_type_mappings[0x0300].bonus_type_name == "Insight"


def test_correlate_no_magnitude_match():
    """Enchantments with no matching magnitude produce no mappings."""
    result = EffectMapResult()

    parsed_enchantments = [
        {"value": 7, "bonus_type": "Enhancement", "stat": "Strength"},
    ]
    decoded_effects = [
        {"entry_type": 0x35, "stat_def_id": 100, "bonus_type_code": 0x0100, "magnitude": 5, "stat": None, "bonus_type": None},
    ]

    _correlate_item_effects(result, parsed_enchantments, decoded_effects)

    assert result.correlations_matched == 0
    assert len(result.stat_mappings) == 0


def test_effect_map_format_output():
    """format_effect_map produces readable output with suggested code."""
    result = EffectMapResult(
        items_processed=10,
        items_with_both=5,
        correlations_attempted=8,
        correlations_matched=6,
    )
    _record_stat_mapping(result, 100, "Strength")
    _record_stat_mapping(result, 100, "Strength")
    _record_stat_mapping(result, 100, "Strength")

    text = format_effect_map(result)
    assert "Effect Stat/Bonus Mapping Report" in text
    assert "Strength" in text
    assert "STAT_DEF_IDS" in text


def test_effect_map_rediscovers_known():
    """Correlation produces mappings matching the 4 known STAT_DEF_IDS.

    This test verifies the core correlation logic by simulating items
    whose enchantments and effects match the existing known mappings.
    """
    result = EffectMapResult()

    # Simulate 3 items each confirming Haggle (stat_def_id=376)
    for _ in range(3):
        _correlate_item_effects(
            result,
            [{"value": 11, "bonus_type": "Competence", "stat": "Haggle"}],
            [{"entry_type": 0x35, "stat_def_id": 376, "bonus_type_code": 0x0200, "magnitude": 11, "stat": None, "bonus_type": None}],
        )

    assert result.stat_mappings[376].stat_name == "Haggle"
    assert result.stat_mappings[376].confirmations == 3
    assert result.stat_mappings[376].conflicts == 0
