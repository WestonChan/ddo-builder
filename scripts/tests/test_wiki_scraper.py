"""Tests for the DDO Wiki scraper orchestration."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from ddo_data.wiki.scraper import scrape_feats, scrape_items


ITEM_WIKITEXT = """
{{Named item|Weapon
|name = Test Sword
|minlevel = 10
|damage = 1[1d8]+5
}}
"""

REDIRECT_WIKITEXT = "#REDIRECT [[Item:Other Page]]"

FEAT_WIKITEXT = """
{{Feat
|name=Cleave
|icon=Icon_Feat_Cleave.png
|cooldown=5 seconds
|prerequisite=[[Power Attack]]
|description=Attack enemies in an arc.
|free=no
|active=yes
|fighter bonus feat=yes
}}
"""


def test_scrape_items_writes_json(tmp_path: Path) -> None:
    """scrape_items writes parsed items to items.json."""
    client = MagicMock()
    client.iter_namespace_pages.return_value = iter(["Item:Test_Sword"])
    client.get_wikitext.return_value = ITEM_WIKITEXT

    count = scrape_items(client, tmp_path, limit=1)

    assert count == 1
    output_file = tmp_path / "items.json"
    assert output_file.exists()
    items = json.loads(output_file.read_text())
    assert len(items) == 1
    assert items[0]["name"] == "Test Sword"
    assert items[0]["minimum_level"] == 10


def test_scrape_items_skips_redirects(tmp_path: Path) -> None:
    """Redirect pages are skipped."""
    client = MagicMock()
    client.iter_namespace_pages.return_value = iter([
        "Item:Redirect_Page",
        "Item:Real_Item",
    ])
    client.get_wikitext.side_effect = [REDIRECT_WIKITEXT, ITEM_WIKITEXT]

    count = scrape_items(client, tmp_path)

    assert count == 1


def test_scrape_items_skips_missing_pages(tmp_path: Path) -> None:
    """Pages that return None wikitext are skipped."""
    client = MagicMock()
    client.iter_namespace_pages.return_value = iter(["Item:Missing"])
    client.get_wikitext.return_value = None

    count = scrape_items(client, tmp_path)

    assert count == 0
    items = json.loads((tmp_path / "items.json").read_text())
    assert items == []


def test_scrape_items_fallback_name(tmp_path: Path) -> None:
    """Page title used as fallback when parser returns no name."""
    # Template with no name= field and no positional arg → parser returns name=None
    wikitext = "{{Named item|minlevel=5}}"
    client = MagicMock()
    client.iter_namespace_pages.return_value = iter(["Item:Cool_Blade"])
    client.get_wikitext.return_value = wikitext

    count = scrape_items(client, tmp_path)

    assert count == 1
    items = json.loads((tmp_path / "items.json").read_text())
    assert items[0]["name"] == "Cool Blade"


def test_scrape_items_progress_callback(tmp_path: Path) -> None:
    """Progress callback fires at 100-page intervals."""
    # Generate 150 pages — callback should fire once (at page 100)
    titles = [f"Item:Item_{i}" for i in range(150)]
    client = MagicMock()
    client.iter_namespace_pages.return_value = iter(titles)
    client.get_wikitext.return_value = ITEM_WIKITEXT

    progress_messages: list[str] = []
    scrape_items(client, tmp_path, on_progress=progress_messages.append)

    assert len(progress_messages) == 1
    assert "100 pages processed" in progress_messages[0]


# ---------------------------------------------------------------------------
# scrape_feats tests
# ---------------------------------------------------------------------------


def test_scrape_feats_writes_json(tmp_path: Path) -> None:
    """scrape_feats writes parsed feats to feats.json."""
    client = MagicMock()
    client.iter_category_members.return_value = iter(["Cleave"])
    client.get_wikitext.return_value = FEAT_WIKITEXT

    count = scrape_feats(client, tmp_path, limit=1)

    assert count == 1
    output_file = tmp_path / "feats.json"
    assert output_file.exists()
    feats = json.loads(output_file.read_text())
    assert len(feats) == 1
    assert feats[0]["name"] == "Cleave"
    assert feats[0]["active"] is True


def test_scrape_feats_skips_redirects(tmp_path: Path) -> None:
    """Redirect pages are skipped."""
    client = MagicMock()
    client.iter_category_members.return_value = iter([
        "Old_Feat_Name",
        "Cleave",
    ])
    client.get_wikitext.side_effect = [REDIRECT_WIKITEXT, FEAT_WIKITEXT]

    count = scrape_feats(client, tmp_path)

    assert count == 1


def test_scrape_feats_skips_overview_pages(tmp_path: Path) -> None:
    """Overview pages like 'Feat' and 'Feats' are skipped."""
    client = MagicMock()
    client.iter_category_members.return_value = iter([
        "Feat",
        "Feats",
        "Feat tree",
        "Feats/Active",
        "Cleave",
    ])
    client.get_wikitext.return_value = FEAT_WIKITEXT

    count = scrape_feats(client, tmp_path)

    assert count == 1
    # Only "Cleave" should have been fetched
    assert client.get_wikitext.call_count == 1


def test_scrape_feats_fallback_name(tmp_path: Path) -> None:
    """Page title used as fallback when parser returns no name."""
    wikitext = "{{Feat|active=yes}}"
    client = MagicMock()
    client.iter_category_members.return_value = iter(["Power_Attack"])
    client.get_wikitext.return_value = wikitext

    count = scrape_feats(client, tmp_path)

    assert count == 1
    feats = json.loads((tmp_path / "feats.json").read_text())
    assert feats[0]["name"] == "Power Attack"


def test_scrape_feats_missing_page(tmp_path: Path) -> None:
    """Pages returning None wikitext are skipped."""
    client = MagicMock()
    client.iter_category_members.return_value = iter(["Missing_Feat"])
    client.get_wikitext.return_value = None

    count = scrape_feats(client, tmp_path)

    assert count == 0
    feats = json.loads((tmp_path / "feats.json").read_text())
    assert feats == []
