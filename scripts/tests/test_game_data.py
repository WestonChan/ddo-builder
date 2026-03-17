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
from ddo_data.game_data.feats import parse_feats
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


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


def test_resolve_enum_known() -> None:
    """Known enum value returns the label."""
    assert resolve_enum(RARITY_TIERS, 4) == "Rare"
    assert resolve_enum(EQUIPMENT_SLOTS, 6) == "Weapon"
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
    assert item["equipment_slot"] == "Weapon"
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
    assert item["id"] is None
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
        patch("ddo_data.game_data.items.read_entry_data",
              return_value=item_content),
    ):
        items = parse_items(tmp_path)

    assert len(items) == 1
    assert items[0]["name"] == "Test Sword"
    assert items[0]["rarity"] == "Rare"
    assert items[0]["equipment_slot"] == "Weapon"


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
# Existing stub tests (backward compat)
# ---------------------------------------------------------------------------


def test_parse_feats_empty(tmp_path: Path) -> None:
    """Parse feats returns empty list when no data available."""
    assert parse_feats(tmp_path) == []
