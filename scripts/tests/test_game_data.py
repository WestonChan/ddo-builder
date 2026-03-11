"""Tests for game data extraction modules."""

from ddo_data.game_data.items import parse_items
from ddo_data.game_data.feats import parse_feats
from pathlib import Path


def test_parse_items_empty(tmp_path: Path) -> None:
    """Parse items returns empty list when no data available."""
    assert parse_items(tmp_path) == []


def test_parse_feats_empty(tmp_path: Path) -> None:
    """Parse feats returns empty list when no data available."""
    assert parse_feats(tmp_path) == []
