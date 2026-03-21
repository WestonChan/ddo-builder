"""Tests for game data extraction modules."""

import json
import struct
from pathlib import Path

from ddo_data.game_data.enums import (
    EQUIPMENT_SLOTS,
    ITEM_CATEGORIES,
    RARITY_TIERS,
    resolve_enum,
)
from ddo_data.game_data.feats import (
    _decode_damage_dice,
    _decode_feat_entry,
    _merge_wiki_feats,
    export_feats_json,
    parse_feats,
)
from ddo_data.game_data.items import (
    _decode_item_entry,
    _merge_wiki_data,
    _wiki_url,
    export_items_json,
    parse_items,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_dup_triple_bytes(
    properties: list[tuple[int, int]],
    schema_id: int = 0x08551000,
) -> bytes:
    """Build raw bytes for a 0x79 dup-triple entry."""
    buf = struct.pack("<I", schema_id)
    for key, val in properties:
        buf += struct.pack("<III", key, key, val)
    return buf


# Property key constants (from DISCOVERED_KEYS)
_KEY_LEVEL = 0x1000361A
_KEY_RARITY = 0x10000E29
_KEY_DURABILITY = 0x10003D24
_KEY_EQUIPMENT_SLOT = 0x10001BA1
_KEY_ITEM_CATEGORY = 0x10001C59
_KEY_EFFECT_VALUE = 0x100012A2
_KEY_EFFECT_REF = 0x10000919
_KEY_EFFECT_REF_2 = 0x10001390
_KEY_MINIMUM_LEVEL = 0x10001C5D
_KEY_COOLDOWN = 0x10000B7A
_KEY_DURATION = 0x10000907


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


def test_resolve_enum_known() -> None:
    """Known enum value returns the label."""
    assert resolve_enum(RARITY_TIERS, 4) == "Rare"
    assert resolve_enum(EQUIPMENT_SLOTS, 6) == "Main Hand"
    assert resolve_enum(EQUIPMENT_SLOTS, 13) == "Off Hand"
    assert resolve_enum(EQUIPMENT_SLOTS, 16) == "Off Hand"
    assert resolve_enum(ITEM_CATEGORIES, 3) == "Weapon"


def test_resolve_enum_unknown() -> None:
    """Unknown enum value returns None."""
    assert resolve_enum(RARITY_TIERS, 99) is None
    assert resolve_enum(EQUIPMENT_SLOTS, 0) is None


# ---------------------------------------------------------------------------
# _decode_item_entry tests
# ---------------------------------------------------------------------------


def test_decode_item_entry_basic() -> None:
    """Entry with known property keys decodes to correct item dict."""
    data = _build_dup_triple_bytes([
        (_KEY_RARITY, 4),           # Rare
        (_KEY_EQUIPMENT_SLOT, 6),   # Weapon
        (_KEY_ITEM_CATEGORY, 3),    # Weapon
        (_KEY_DURABILITY, 150),
        (_KEY_LEVEL, 15),
    ])

    item = _decode_item_entry(data, 0x79001234, "Celestia")

    assert item is not None
    assert item["id"] == "0x79001234"
    assert item["name"] == "Celestia"
    assert item["rarity"] == "Rare"
    assert item["equipment_slot"] == "Main Hand"
    assert item["item_category"] == "Weapon"
    assert item["durability"] == 150
    assert item["level"] == 15


def test_decode_item_entry_effect_refs() -> None:
    """Effect refs (0x70XXXXXX) appear in _effect_refs list."""
    data = _build_dup_triple_bytes([
        (_KEY_RARITY, 3),
        (_KEY_EFFECT_REF, 0x70001234),
    ])

    item = _decode_item_entry(data, 0x79000001, "Test Item")

    assert item is not None
    assert item["_effect_refs"] == ["0x70001234"]


def test_decode_item_entry_minimum_level() -> None:
    """minimum_level is extracted from dat key 0x10001C5D."""
    data = _build_dup_triple_bytes([
        (_KEY_RARITY, 4),
        (_KEY_EQUIPMENT_SLOT, 6),
        (_KEY_MINIMUM_LEVEL, 20),
    ])

    item = _decode_item_entry(data, 0x79000001, "Ring of Feathers")

    assert item is not None
    assert item["minimum_level"] == 20


def test_decode_item_entry_minimum_level_absent() -> None:
    """minimum_level is None when key is not present in the entry."""
    data = _build_dup_triple_bytes([
        (_KEY_RARITY, 4),
        (_KEY_EQUIPMENT_SLOT, 6),
    ])

    item = _decode_item_entry(data, 0x79000001, "Ring of Feathers")

    assert item is not None
    assert item["minimum_level"] is None


def test_decode_item_entry_multiple_effect_ref_slots() -> None:
    """Effect refs from different effect_ref_N slots are all collected."""
    data = _build_dup_triple_bytes([
        (_KEY_RARITY, 4),
        (_KEY_EFFECT_REF, 0x70001111),
        (_KEY_EFFECT_REF_2, 0x70002222),
    ])

    item = _decode_item_entry(data, 0x79000001, "Test Ring")

    assert item is not None
    assert set(item["_effect_refs"]) == {"0x70001111", "0x70002222"}


def test_decode_item_entry_no_item_keys() -> None:
    """Entry without item indicator keys returns None (filtered out)."""
    # Only has level and effect_value -- no slot, rarity, or category
    data = _build_dup_triple_bytes([
        (_KEY_LEVEL, 10),
        (_KEY_EFFECT_VALUE, 50),
    ])

    item = _decode_item_entry(data, 0x79000099, "Quest Object")
    assert item is None


def test_decode_item_entry_empty() -> None:
    """Entry with no decodable properties returns None."""
    data = struct.pack("<III", 0x08551000, 0x00000000, 0xDEADBEEF)
    item = _decode_item_entry(data, 0x79000001, "Empty")
    assert item is None


def test_decode_item_entry_unknown_enum() -> None:
    """Unknown enum values resolve to None instead of crashing."""
    data = _build_dup_triple_bytes([
        (_KEY_RARITY, 99),          # Unknown rarity
        (_KEY_EQUIPMENT_SLOT, 99),  # Unknown slot
    ])

    item = _decode_item_entry(data, 0x79000001, "Weird Item")

    assert item is not None
    assert item["rarity"] is None
    assert item["equipment_slot"] is None


# ---------------------------------------------------------------------------
# _merge_wiki_data tests
# ---------------------------------------------------------------------------


def test_merge_matched() -> None:
    """Matched items merge wiki fields onto binary, binary wins, has wiki_url."""
    binary = [{"id": "0x79000001", "name": "Celestia", "durability": 150, "rarity": "Rare"}]
    wiki = [{"name": "Celestia", "durability": 200, "enchantments": ["+5 Holy"], "minimum_level": 28}]

    merged = _merge_wiki_data(binary, wiki)

    assert len(merged) == 1
    item = merged[0]
    # Binary wins for durability
    assert item["durability"] == 150
    # Wiki fills in missing fields
    assert item["enchantments"] == ["+5 Holy"]
    assert item["minimum_level"] == 28
    # Wiki URL present
    assert item["wiki_url"] == "https://ddowiki.com/page/Item:Celestia"


def test_merge_binary_only() -> None:
    """Binary-only item has no wiki_url."""
    binary = [{"id": "0x79000001", "name": "Unknown Sword", "rarity": "Common"}]
    wiki = [{"name": "Different Item", "enchantments": []}]

    merged = _merge_wiki_data(binary, wiki)

    # Binary item + unmatched wiki item
    assert len(merged) == 2
    sword = next(i for i in merged if i["name"] == "Unknown Sword")
    assert "wiki_url" not in sword


def test_merge_wiki_only() -> None:
    """Wiki-only item gets id=None and wiki_url."""
    binary: list[dict] = []
    wiki = [{"name": "Wiki Only Item", "minimum_level": 5}]

    merged = _merge_wiki_data(binary, wiki)

    assert len(merged) == 1
    item = merged[0]
    assert item["dat_id"] is None
    assert item["data_source"] == "wiki"
    assert item["wiki_url"] == "https://ddowiki.com/page/Item:Wiki_Only_Item"


def test_merge_name_normalization() -> None:
    """Case/whitespace differences still merge."""
    binary = [{"id": "0x79000001", "name": "Vorpal Sword", "rarity": "Rare"}]
    wiki = [{"name": "vorpal_sword", "enchantments": ["Vorpal"]}]

    merged = _merge_wiki_data(binary, wiki)

    assert len(merged) == 1
    assert merged[0]["enchantments"] == ["Vorpal"]
    assert "wiki_url" in merged[0]


def test_wiki_url_special_characters() -> None:
    """Wiki URL handles special characters correctly."""
    assert _wiki_url("Dusk, the Light Descending") == (
        "https://ddowiki.com/page/Item:Dusk,_the_Light_Descending"
    )


# ---------------------------------------------------------------------------
# parse_items tests
# ---------------------------------------------------------------------------


def test_parse_items_empty(tmp_path: Path) -> None:
    """Parse items returns empty list when no .dat files exist."""
    assert parse_items(tmp_path) == []


def test_parse_items_single(tmp_path: Path) -> None:
    """Parses one 0x79 entry with a matching string table entry."""
    from unittest.mock import patch

    from ddo_data.dat_parser.archive import FileEntry

    item_content = _build_dup_triple_bytes([
        (_KEY_RARITY, 4),
        (_KEY_EQUIPMENT_SLOT, 6),
    ])

    mock_entry = FileEntry(
        file_id=0x79000001, data_offset=0, size=len(item_content),
        disk_size=len(item_content) + 8, flags=1,
    )

    # Create dummy .dat files so parse_items doesn't bail on exists() checks
    (tmp_path / "client_gamelogic.dat").write_bytes(b"\x00" * 256)
    (tmp_path / "client_local_English.dat").write_bytes(b"\x00" * 256)

    with (
        patch("ddo_data.game_data.items.DatArchive"),
        patch("ddo_data.game_data.items.traverse_btree",
              return_value={0x79000001: mock_entry}),
        patch("ddo_data.game_data.items.load_string_table",
              return_value={0x25000001: "Test Sword"}),
        patch("ddo_data.game_data.items.load_tooltip_table",
              return_value={0x25000001: "A sharp test sword."}),
        patch("ddo_data.game_data.items.load_localization_tables",
              return_value={"enchant_name": {0x25000001: "Holy +6"},
                            "enchant_suffix": {0x25000001: "of Greater Good"},
                            "description": {}}),
        patch("ddo_data.game_data.items.read_entry_data",
              return_value=item_content),
    ):
        items = parse_items(tmp_path)

    assert len(items) == 1
    assert items[0]["name"] == "Test Sword"
    assert items[0]["rarity"] == "Rare"
    assert items[0]["equipment_slot"] == "Main Hand"
    assert items[0]["tooltip"] == "A sharp test sword."
    assert items[0]["enchant_name"] == "Holy +6"
    assert items[0]["enchant_suffix"] == "of Greater Good"


# ---------------------------------------------------------------------------
# _decode_damage_dice tests
# ---------------------------------------------------------------------------

# Damage dice key constant (matches DISCOVERED_KEYS entry 0x10001399)
_KEY_DAMAGE_DICE_NOTATION = 0x10001399


def test_decode_damage_dice_with_bonus() -> None:
    """Packed u32 decodes to dice+bonus string."""
    # 0x32643205: bonus=5, dice bytes=[0x32, 0x64, 0x32] = "2d2"
    assert _decode_damage_dice(0x32643205) == "2d2+5"


def test_decode_damage_dice_no_bonus() -> None:
    """Zero bonus produces bare dice string."""
    # 0x34643100: bonus=0, dice bytes=[0x31, 0x64, 0x34] = "1d4"
    assert _decode_damage_dice(0x34643100) == "1d4"


def test_decode_damage_dice_1d4_plus3() -> None:
    """1d4+3 example from DISCOVERED_KEYS docs."""
    # 0x34643103: bonus=3, dice bytes=[0x31, 0x64, 0x34] = "1d4"
    assert _decode_damage_dice(0x34643103) == "1d4+3"


def test_decode_damage_dice_invalid_bytes() -> None:
    """Non-ASCII bytes return None without crashing."""
    assert _decode_damage_dice(0xFF808080) is None


# ---------------------------------------------------------------------------
# _decode_feat_entry tests
# ---------------------------------------------------------------------------


def test_decode_feat_entry_returns_none_for_item() -> None:
    """Entry with item indicator key (rarity) returns None."""
    data = _build_dup_triple_bytes([
        (_KEY_RARITY, 4),           # Rare — item indicator
        (_KEY_LEVEL, 10),
    ])
    assert _decode_feat_entry(data, 0x79001000, "Precise Shot") is None


def test_decode_feat_entry_returns_none_for_equipment_slot() -> None:
    """Entry with equipment_slot indicator returns None."""
    data = _build_dup_triple_bytes([
        (_KEY_EQUIPMENT_SLOT, 6),   # Main Hand — item indicator
    ])
    assert _decode_feat_entry(data, 0x79001001, "Some Feat") is None


def test_decode_feat_entry_basic() -> None:
    """Entry with no item indicator keys returns feat dict with dat_id and name."""
    data = _build_dup_triple_bytes([
        (_KEY_LEVEL, 5),
        (_KEY_EFFECT_VALUE, 20),
    ])
    feat = _decode_feat_entry(data, 0x79002000, "Weapon Focus")

    assert feat is not None
    assert feat["dat_id"] == "0x79002000"
    assert feat["name"] == "Weapon Focus"
    assert "damage_dice_notation" not in feat


def test_decode_feat_entry_damage_dice() -> None:
    """damage_dice_notation key is decoded when present."""
    # 0x32643205 = "2d2+5"
    data = _build_dup_triple_bytes([
        (_KEY_DAMAGE_DICE_NOTATION, 0x32643205),
    ])
    feat = _decode_feat_entry(data, 0x79002001, "Sneak Attack")

    assert feat is not None
    assert feat["damage_dice_notation"] == "2d2+5"


def test_decode_feat_entry_scales_with_difficulty() -> None:
    """Presence of difficulty tier keys sets scales_with_difficulty."""
    _KEY_TIER_QUARTER = 0x10000867
    quarter_025 = struct.unpack("<I", struct.pack("<f", 0.25))[0]

    data = _build_dup_triple_bytes([
        (_KEY_LEVEL, 5),
        (_KEY_TIER_QUARTER, quarter_025),
    ])

    feat = _decode_feat_entry(data, 0x79000001, "Scaling Feat")
    assert feat is not None
    assert feat.get("scales_with_difficulty") is True


def test_decode_feat_entry_empty_properties() -> None:
    """Entry with no decodable properties returns None."""
    data = struct.pack("<III", 0x08551000, 0x00000000, 0xDEADBEEF)
    assert _decode_feat_entry(data, 0x79000001, "Empty Feat") is None


def test_decode_feat_entry_cooldown_duration() -> None:
    """Float keys for cooldown and duration are extracted as seconds."""
    # 15.0 as IEEE 754 float = 0x41700000
    cooldown_15 = struct.unpack("<I", struct.pack("<f", 15.0))[0]
    # -1.0 as IEEE 754 float = 0xBF800000 (permanent duration)
    duration_perm = struct.unpack("<I", struct.pack("<f", -1.0))[0]

    data = _build_dup_triple_bytes([
        (_KEY_LEVEL, 5),
        (_KEY_COOLDOWN, cooldown_15),
        (_KEY_DURATION, duration_perm),
    ])

    feat = _decode_feat_entry(data, 0x79000001, "Power Attack")
    assert feat is not None
    assert feat["cooldown_seconds"] == 15.0
    assert feat["duration_seconds"] == -1.0


def test_decode_item_entry_cooldown() -> None:
    """Float cooldown key is extracted from item entries."""
    cooldown_6 = struct.unpack("<I", struct.pack("<f", 6.0))[0]

    data = _build_dup_triple_bytes([
        (_KEY_RARITY, 4),
        (_KEY_EQUIPMENT_SLOT, 6),
        (_KEY_COOLDOWN, cooldown_6),
    ])

    item = _decode_item_entry(data, 0x79000001, "Test Clickie")
    assert item is not None
    assert item["cooldown_seconds"] == 6.0


def test_decode_item_entry_effect_value() -> None:
    """Effect value magnitude is extracted as integer."""
    _KEY_EFFECT_VALUE = 0x100012A2

    data = _build_dup_triple_bytes([
        (_KEY_RARITY, 4),
        (_KEY_EQUIPMENT_SLOT, 6),
        (_KEY_EFFECT_VALUE, 33),
    ])

    item = _decode_item_entry(data, 0x79000001, "Strength +33 Ring")
    assert item is not None
    assert item["effect_value"] == 33


def test_decode_item_entry_level_and_tier() -> None:
    """Internal level and tier multiplier float keys are extracted."""
    _KEY_INTERNAL_LEVEL = 0x10000742
    _KEY_TIER_MULTIPLIER = 0x10000B60
    level_20 = struct.unpack("<I", struct.pack("<f", 20.0))[0]
    tier_3 = struct.unpack("<I", struct.pack("<f", 3.0))[0]

    data = _build_dup_triple_bytes([
        (_KEY_RARITY, 4),
        (_KEY_EQUIPMENT_SLOT, 6),
        (_KEY_INTERNAL_LEVEL, level_20),
        (_KEY_TIER_MULTIPLIER, tier_3),
    ])

    item = _decode_item_entry(data, 0x79000001, "Epic Sword")
    assert item is not None
    assert item["internal_level"] == 20
    assert item["tier_multiplier"] == 3.0


# ---------------------------------------------------------------------------
# _merge_wiki_feats tests
# ---------------------------------------------------------------------------


def test_merge_wiki_feats_matched() -> None:
    """Matched feat gets wiki fields overlaid; dat_id preserved from binary."""
    binary = [{"dat_id": "0x79001000", "name": "Precise Shot"}]
    wiki = [{"name": "Precise Shot", "description": "Fires precisely.", "passive": True}]

    merged = _merge_wiki_feats(binary, wiki)

    assert len(merged) == 1
    feat = merged[0]
    assert feat["dat_id"] == "0x79001000"
    assert feat["name"] == "Precise Shot"
    assert feat["description"] == "Fires precisely."
    assert feat["passive"] is True


def test_merge_wiki_feats_unmatched_binary_discarded() -> None:
    """Binary entries not in wiki (NPCs, abilities) are dropped."""
    binary = [
        {"dat_id": "0x79001000", "name": "Precise Shot"},
        {"dat_id": "0x79001001", "name": "Some NPC Name"},   # no wiki match
    ]
    wiki = [{"name": "Precise Shot", "description": "Fires precisely."}]

    merged = _merge_wiki_feats(binary, wiki)

    assert len(merged) == 1
    assert merged[0]["name"] == "Precise Shot"


def test_merge_wiki_feats_wiki_only() -> None:
    """Wiki-only feat (no binary match) is kept with dat_id=None."""
    binary: list[dict] = []
    wiki = [{"name": "Toughness", "description": "Increases HP."}]

    merged = _merge_wiki_feats(binary, wiki)

    assert len(merged) == 1
    assert merged[0]["dat_id"] is None
    assert merged[0]["name"] == "Toughness"


def test_merge_wiki_feats_name_normalization() -> None:
    """Case/underscore differences still match."""
    binary = [{"dat_id": "0x79003000", "name": "Weapon_Focus"}]
    wiki = [{"name": "weapon focus", "description": "Improves accuracy."}]

    merged = _merge_wiki_feats(binary, wiki)

    assert len(merged) == 1
    assert merged[0]["dat_id"] == "0x79003000"
    assert merged[0]["description"] == "Improves accuracy."


# ---------------------------------------------------------------------------
# parse_feats tests
# ---------------------------------------------------------------------------


def test_parse_feats_missing_dat(tmp_path: Path) -> None:
    """parse_feats returns empty list when .dat files are absent."""
    assert parse_feats(tmp_path) == []


def test_parse_feats_single(tmp_path: Path) -> None:
    """Parses one feat entry (no item indicator keys) and skips item entries."""
    from unittest.mock import patch

    from ddo_data.dat_parser.archive import FileEntry

    # Feat entry: no item indicator keys
    feat_content = _build_dup_triple_bytes([
        (_KEY_LEVEL, 5),
    ])
    # Item entry: has rarity — should be skipped by feat parser
    item_content = _build_dup_triple_bytes([
        (_KEY_RARITY, 4),
        (_KEY_EQUIPMENT_SLOT, 6),
    ])

    feat_entry = FileEntry(
        file_id=0x79000001, data_offset=0, size=len(feat_content),
        disk_size=len(feat_content) + 8, flags=1,
    )
    item_entry = FileEntry(
        file_id=0x79000002, data_offset=0, size=len(item_content),
        disk_size=len(item_content) + 8, flags=1,
    )

    (tmp_path / "client_gamelogic.dat").write_bytes(b"\x00" * 256)
    (tmp_path / "client_local_English.dat").write_bytes(b"\x00" * 256)

    def mock_read_entry(archive, entry):
        if entry.file_id == 0x79000001:
            return feat_content
        return item_content

    with (
        patch("ddo_data.game_data.feats.DatArchive"),
        patch("ddo_data.game_data.feats.traverse_btree",
              return_value={0x79000001: feat_entry, 0x79000002: item_entry}),
        patch("ddo_data.game_data.feats.load_string_table",
              return_value={0x25000001: "Precise Shot", 0x25000002: "Iron Defender"}),
        patch("ddo_data.game_data.feats.load_tooltip_table",
              return_value={0x25000001: "Improves ranged accuracy."}),
        patch("ddo_data.game_data.feats.read_entry_data", side_effect=mock_read_entry),
    ):
        feats = parse_feats(tmp_path)

    assert len(feats) == 1
    assert feats[0]["name"] == "Precise Shot"
    assert feats[0]["dat_id"] == "0x79000001"
    assert feats[0]["tooltip"] == "Improves ranged accuracy."


# ---------------------------------------------------------------------------
# export_feats_json tests
# ---------------------------------------------------------------------------


def test_export_feats_json(tmp_path: Path) -> None:
    """Feats list is written as valid JSON."""
    feats = [{"dat_id": "0x79001000", "name": "Toughness", "description": "HP bonus."}]
    out = tmp_path / "feats.json"

    export_feats_json(feats, out)

    assert out.exists()
    loaded = json.loads(out.read_text())
    assert loaded == feats


# ---------------------------------------------------------------------------
# export_items_json tests
# ---------------------------------------------------------------------------


def test_export_items_json_roundtrip(tmp_path: Path) -> None:
    """Write and re-read JSON to verify round-trip."""
    items = [
        {"id": "0x79000001", "name": "Celestia", "rarity": "Rare"},
        {"id": None, "name": "Wiki Item", "wiki_url": "https://ddowiki.com/page/Item:Wiki_Item"},
    ]

    output = tmp_path / "items.json"
    export_items_json(items, output)

    with open(output) as f:
        loaded = json.load(f)

    assert len(loaded) == 2
    assert loaded[0]["name"] == "Celestia"
    assert loaded[1]["id"] is None


# ---------------------------------------------------------------------------
# decode_effect_entry tests
# ---------------------------------------------------------------------------


def _build_effect53_bytes(
    stat_def_id: int,
    magnitude: int,
    bonus_type: int = 0x0100,
) -> bytes:
    """Build a minimal valid entry_type=53 effect entry (84 bytes)."""
    buf = bytearray(84)
    struct.pack_into("<I", buf, 0, 0x00000002)   # DID
    buf[4] = 0x00                                 # ref_count
    struct.pack_into("<I", buf, 5, 0x35)          # entry_type = 53
    struct.pack_into("<I", buf, 9, 0x00000001)    # flag
    struct.pack_into("<H", buf, 13, bonus_type)   # bonus_type_code
    struct.pack_into("<H", buf, 16, stat_def_id)  # stat_def_id
    struct.pack_into("<I", buf, 68, magnitude)    # magnitude
    return bytes(buf)


def test_decode_effect_entry_type53_known_stat() -> None:
    """entry_type=53 with known stat_def_id decodes to stat name, magnitude, bonus type."""
    from ddo_data.dat_parser.probe import decode_effect_entry

    data = _build_effect53_bytes(stat_def_id=376, magnitude=11)
    result = decode_effect_entry(data)

    assert result is not None
    assert result["stat"] == "Haggle"
    assert result["magnitude"] == 11
    assert result["bonus_type"] == "Enhancement"
    assert result["entry_type"] == 0x35
    assert result["stat_def_id"] == 376


def test_decode_effect_entry_unknown_stat() -> None:
    """Unknown stat_def_id yields stat=None but entry still decodes."""
    from ddo_data.dat_parser.probe import decode_effect_entry

    data = _build_effect53_bytes(stat_def_id=9999, magnitude=5)
    result = decode_effect_entry(data)

    assert result is not None
    assert result["stat"] is None
    assert result["magnitude"] == 5
    assert result["stat_def_id"] == 9999


def test_decode_effect_entry_type26_skipped() -> None:
    """entry_type=26 (secondary augment marker) returns None."""
    from ddo_data.dat_parser.probe import decode_effect_entry

    buf = bytearray(37)
    struct.pack_into("<I", buf, 5, 0x1A)  # entry_type = 26
    result = decode_effect_entry(bytes(buf))

    assert result is None


def test_decode_effect_entry_too_short() -> None:
    """Entry shorter than 20 bytes returns None without crashing."""
    from ddo_data.dat_parser.probe import decode_effect_entry

    assert decode_effect_entry(b"\x00" * 10) is None


def _build_effect17_bytes(stat_def_id: int, bonus_type: int = 0x0100) -> bytes:
    """Build a minimal valid entry_type=17 effect entry (28 bytes, no magnitude field)."""
    buf = bytearray(28)
    struct.pack_into("<I", buf, 0, 0x00000002)   # DID
    buf[4] = 0x00                                 # ref_count
    struct.pack_into("<I", buf, 5, 0x11)          # entry_type = 17
    struct.pack_into("<H", buf, 13, bonus_type)   # bonus_type_code
    struct.pack_into("<H", buf, 16, stat_def_id)  # stat_def_id
    return bytes(buf)


def test_decode_effect_entry_type17() -> None:
    """entry_type=17 yields magnitude=1 (implicit) and decodes stat."""
    from ddo_data.dat_parser.probe import decode_effect_entry

    data = _build_effect17_bytes(stat_def_id=376)
    result = decode_effect_entry(data)

    assert result is not None
    assert result["entry_type"] == 0x11
    assert result["magnitude"] == 1
    assert result["stat"] == "Haggle"
    assert result["bonus_type"] == "Enhancement"


def test_decode_effect_entry_type17_too_short() -> None:
    """entry_type=17 entry shorter than 28 bytes returns None.

    27 bytes: passes the initial 20-byte guard but fails the type-17 minimum (28).
    """
    from ddo_data.dat_parser.probe import decode_effect_entry

    buf = bytearray(27)  # one byte under the type-17 minimum of 28
    struct.pack_into("<I", buf, 5, 0x11)  # entry_type = 17
    assert decode_effect_entry(bytes(buf)) is None


def test_decode_effect_entry_zero_magnitude() -> None:
    """entry_type=53 with magnitude=0 decodes without filtering (value=0 is valid)."""
    from ddo_data.dat_parser.probe import decode_effect_entry

    data = _build_effect53_bytes(stat_def_id=376, magnitude=0)
    result = decode_effect_entry(data)

    assert result is not None
    assert result["magnitude"] == 0
    assert result["stat"] == "Haggle"


# ---------------------------------------------------------------------------
# Existing stub tests (backward compat)
# ---------------------------------------------------------------------------


def test_parse_feats_empty(tmp_path: Path) -> None:
    """Parse feats returns empty list when no data available."""
    assert parse_feats(tmp_path) == []
