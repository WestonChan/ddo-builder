"""Scrape DDO Wiki for supplementary game data."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

from .client import WikiClient
from .parsers import parse_feat_wikitext, parse_item_wikitext

logger = logging.getLogger(__name__)


def scrape_items(
    client: WikiClient,
    output: Path,
    *,
    limit: int = 0,
    category: str = "",
    on_progress: Callable[[str], None] | None = None,
) -> int:
    """Scrape Item: namespace pages, parse templates, write items.json.

    Enumerates pages from the Item namespace (ns=500), fetches wikitext
    for each, parses the ``{{Named item|...}}`` template, and writes the
    collected items to ``output/items.json``.

    Args:
        category: If set, scrape only items in this wiki category
            (e.g. "Named_items"). Otherwise enumerates the full namespace.

    Returns count of successfully parsed items.
    """
    items: list[dict] = []
    skipped = 0

    if category:
        page_iter = client.iter_category_members(category, namespace=500, limit=limit)
    else:
        page_iter = client.iter_namespace_pages(500, limit=limit)

    for i, title in enumerate(page_iter):
        wikitext = client.get_wikitext(title)
        if wikitext is None:
            skipped += 1
            continue

        if "#REDIRECT" in wikitext.upper():
            skipped += 1
            continue

        parsed = parse_item_wikitext(wikitext)
        if parsed is None:
            skipped += 1
            continue

        # Use page title as fallback name (strip "Item:" prefix)
        if not parsed.get("name"):
            parsed["name"] = title.removeprefix("Item:").replace("_", " ")

        items.append(parsed)

        if on_progress and (i + 1) % 100 == 0:
            on_progress(f"  ... {i + 1} pages processed, {len(items)} items parsed")

    output.mkdir(parents=True, exist_ok=True)
    output_path = output / "items.json"
    with open(output_path, "w") as f:
        json.dump(items, f, indent=2)

    logger.info(
        "Scraped %d items (%d skipped), written to %s",
        len(items), skipped, output_path,
    )
    return len(items)


# Page titles that are index/overview pages, not individual feats
_FEAT_SKIP_TITLES = {"Feat", "Feats", "Feat tree"}


def scrape_feats(
    client: WikiClient,
    output: Path,
    *,
    limit: int = 0,
    category: str = "Feats",
    on_progress: Callable[[str], None] | None = None,
) -> int:
    """Scrape feat pages from DDO Wiki, parse templates, write feats.json.

    Enumerates pages from the Feats category (namespace 0), fetches
    wikitext for each, parses the ``{{Feat|...}}`` template, and writes
    the collected feats to ``output/feats.json``.

    Returns count of successfully parsed feats.
    """
    feats: list[dict] = []
    skipped = 0

    page_iter = client.iter_category_members(category, namespace=0, limit=limit)

    for i, title in enumerate(page_iter):
        if title in _FEAT_SKIP_TITLES:
            skipped += 1
            continue

        # Skip subcategory-style titles (e.g. "Feats/Active")
        if "/" in title:
            skipped += 1
            continue

        wikitext = client.get_wikitext(title)
        if wikitext is None:
            skipped += 1
            continue

        if "#REDIRECT" in wikitext.upper():
            skipped += 1
            continue

        parsed = parse_feat_wikitext(wikitext)
        if parsed is None:
            skipped += 1
            continue

        # Use page title as fallback name
        if not parsed.get("name"):
            parsed["name"] = title.replace("_", " ")

        feats.append(parsed)

        if on_progress and (i + 1) % 100 == 0:
            on_progress(f"  ... {i + 1} pages processed, {len(feats)} feats parsed")

    output.mkdir(parents=True, exist_ok=True)
    output_path = output / "feats.json"
    with open(output_path, "w") as f:
        json.dump(feats, f, indent=2)

    logger.info(
        "Scraped %d feats (%d skipped), written to %s",
        len(feats), skipped, output_path,
    )
    return len(feats)


def scrape_enhancements(
    client: WikiClient,
    output: Path,
    *,
    limit: int = 0,
    on_progress: Callable[[str], None] | None = None,
) -> int:
    """Scrape enhancement tree data from DDO Wiki. Not yet implemented."""
    return 0
