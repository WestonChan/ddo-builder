"""Scrape DDO Wiki for supplementary game data."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

from .client import WikiClient
from .parsers import (
    parse_augment_wikitext,
    parse_enhancement_tree_wikitext,
    parse_feat_wikitext,
    parse_item_wikitext,
    parse_spell_wikitext,
    parse_tree_index_wikitext,
    parse_universal_tree_index,
)

logger = logging.getLogger(__name__)


def collect_items(
    client: WikiClient,
    *,
    limit: int = 0,
    category: str = "",
    on_progress: Callable[[str], None] | None = None,
) -> list[dict]:
    """Collect item dicts from DDO Wiki without writing to disk.

    Enumerates pages from the Item namespace (ns=500), fetches wikitext
    for each, and parses the ``{{Named item|...}}`` template.

    Args:
        category: If set, scrape only items in this wiki category
            (e.g. "Named_items"). Otherwise enumerates the full namespace.

    Returns list of parsed item dicts.
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

        from urllib.parse import quote
        parsed["wiki_url"] = f"https://ddowiki.com/page/{quote(title.replace(' ', '_'), safe='_/:()-,')}"
        items.append(parsed)

        if on_progress and (i + 1) % 100 == 0:
            on_progress(f"  ... {i + 1} pages processed, {len(items)} items parsed")

    logger.info("Collected %d items (%d skipped)", len(items), skipped)
    return items


def collect_augments(
    client: WikiClient,
    *,
    limit: int = 0,
    on_progress: Callable[[str], None] | None = None,
) -> list[dict]:
    """Collect augment dicts from DDO Wiki.

    Enumerates pages from the Item namespace (ns=500), fetches wikitext
    for each, and parses the ``{{Item Augment|...}}`` template.
    Pages without this template are skipped (they're regular items).

    Uses the wiki cache, so if collect_items ran first, this is fast.
    """
    augments: list[dict] = []
    skipped = 0

    page_iter = client.iter_namespace_pages(500, limit=limit)

    for i, title in enumerate(page_iter):
        wikitext = client.get_wikitext(title)
        if wikitext is None:
            skipped += 1
            continue

        if "#REDIRECT" in wikitext.upper():
            skipped += 1
            continue

        parsed = parse_augment_wikitext(wikitext)
        if parsed is None:
            skipped += 1
            continue

        if not parsed.get("name"):
            parsed["name"] = title.removeprefix("Item:").replace("_", " ")

        from urllib.parse import quote
        parsed["wiki_url"] = f"https://ddowiki.com/page/{quote(title.replace(' ', '_'), safe='_/:()-,')}"
        augments.append(parsed)

        if on_progress and (i + 1) % 100 == 0:
            on_progress(f"  ... {i + 1} pages processed, {len(augments)} augments parsed")

    logger.info("Collected %d augments (%d skipped)", len(augments), skipped)
    return augments


# Page titles that are index/overview pages, not individual feats
_SPELL_SKIP_TITLES = {"All spells", "Spell", "Spells"}


def collect_spells(
    client: WikiClient,
    *,
    limit: int = 0,
    on_progress: Callable[[str], None] | None = None,
) -> list[dict]:
    """Collect spell dicts from DDO Wiki Spells category.

    Enumerates pages from the Spells category (namespace 0), fetches
    wikitext for each, and parses the ``{{Infobox-spell|...}}`` template.
    """
    spells: list[dict] = []
    skipped = 0

    page_iter = client.iter_category_members("Spells", namespace=0, limit=limit)

    for i, title in enumerate(page_iter):
        if title in _SPELL_SKIP_TITLES or "/" in title:
            skipped += 1
            continue

        wikitext = client.get_wikitext(title)
        if wikitext is None:
            skipped += 1
            continue

        if "#REDIRECT" in wikitext.upper():
            skipped += 1
            continue

        parsed = parse_spell_wikitext(wikitext)
        if parsed is None:
            skipped += 1
            continue

        if not parsed.get("name"):
            parsed["name"] = title.replace("_", " ")

        from urllib.parse import quote
        parsed["wiki_url"] = f"https://ddowiki.com/page/{quote(title.replace(' ', '_'), safe='_/:()-,')}"
        spells.append(parsed)

        if on_progress and (i + 1) % 100 == 0:
            on_progress(f"  ... {i + 1} pages processed, {len(spells)} spells parsed")

    logger.info("Collected %d spells (%d skipped)", len(spells), skipped)
    return spells


_FEAT_SKIP_TITLES = {"Feat", "Feats", "Feat tree"}


def collect_feats(
    client: WikiClient,
    *,
    limit: int = 0,
    category: str = "Feats",
    on_progress: Callable[[str], None] | None = None,
) -> list[dict]:
    """Collect feat dicts from DDO Wiki without writing to disk.

    Enumerates pages from the Feats category (namespace 0), fetches
    wikitext for each, and parses the ``{{Feat|...}}`` template.

    Returns list of parsed feat dicts.
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

        from urllib.parse import quote
        parsed["wiki_url"] = f"https://ddowiki.com/page/{quote(title.replace(' ', '_'), safe='_/:()-,')}"

        # Detect past life feats and annotate with type/class
        _annotate_past_life(parsed)

        feats.append(parsed)

        if on_progress and (i + 1) % 100 == 0:
            on_progress(f"  ... {i + 1} pages processed, {len(feats)} feats parsed")

    logger.info("Collected %d feats (%d skipped)", len(feats), skipped)
    return feats


def _annotate_past_life(feat: dict) -> None:
    """Detect past life feats and annotate with past_life_type and class."""
    name = feat.get("name", "")
    if name.startswith("Past Life: "):
        suffix = name[len("Past Life: "):]
        feat["past_life_type"] = "heroic"
        feat["past_life_class"] = suffix  # May not match a class (e.g., "Arcane Trickster")
        feat["past_life_max_stacks"] = 3
    elif "(Epic Past Life Feat)" in name or "(epic past life feat)" in name:
        feat["past_life_type"] = "epic"
        feat["past_life_max_stacks"] = 3
    elif "(Racial Past Life Feat)" in name or "(racial past life feat)" in name:
        feat["past_life_type"] = "racial"
        feat["past_life_max_stacks"] = 3
    elif "(Iconic Past Life Feat)" in name or "(iconic past life feat)" in name:
        feat["past_life_type"] = "iconic"
        feat["past_life_max_stacks"] = 3


# Index pages that list all enhancement trees, with their tree type.
_ENHANCEMENT_INDEX_PAGES: list[tuple[str, str]] = [
    ("Class enhancements", "class"),
    ("Racial enhancements", "racial"),
    ("Universal enhancements", "universal"),
]

# Regex to extract redirect target from "#REDIRECT [[Target]]"
_REDIRECT_RE = re.compile(r"#REDIRECT\s*\[\[([^\]]+)\]\]", re.IGNORECASE)


def _resolve_redirect(wikitext: str) -> str | None:
    """Extract the redirect target page title, or None if not a redirect."""
    match = _REDIRECT_RE.search(wikitext)
    return match.group(1).strip() if match else None


def collect_enhancements(
    client: WikiClient,
    *,
    limit: int = 0,
    on_progress: Callable[[str], None] | None = None,
) -> list[dict]:
    """Collect enhancement tree dicts from DDO Wiki without writing to disk.

    Discovers trees from three index pages (Class, Racial, Universal
    enhancements), fetches each tree page, and parses all enhancement
    templates.

    Returns list of parsed enhancement tree dicts.
    """
    trees: list[dict] = []
    skipped = 0
    visited: set[str] = set()  # deduplicate shared trees (e.g. Vanguard)

    # Gather tree refs from all index pages
    tree_refs: list[dict] = []
    for index_title, tree_type in _ENHANCEMENT_INDEX_PAGES:
        index_wikitext = client.get_wikitext(index_title)
        if index_wikitext is None:
            logger.warning("Could not fetch index page: %s", index_title)
            continue

        if tree_type == "universal":
            refs = parse_universal_tree_index(index_wikitext)
        else:
            refs = parse_tree_index_wikitext(index_wikitext)

        for ref in refs:
            ref["tree_type"] = tree_type
        tree_refs.extend(refs)

    if on_progress:
        on_progress(f"  Found {len(tree_refs)} tree references from index pages")

    tree_count = 0
    for ref in tree_refs:
        page_title = ref["page_title"]

        # Deduplicate shared trees
        if page_title in visited:
            continue
        visited.add(page_title)

        # Check limit
        if 0 < limit <= tree_count:
            break

        wikitext = client.get_wikitext(page_title)
        if wikitext is None:
            skipped += 1
            continue

        # Resolve redirects (universal trees link to redirects)
        if "#REDIRECT" in wikitext.upper():
            redirect_target = _resolve_redirect(wikitext)
            if redirect_target is None:
                skipped += 1
                continue
            visited.add(redirect_target)
            wikitext = client.get_wikitext(redirect_target)
            if wikitext is None:
                skipped += 1
                continue
            page_title = redirect_target

        parsed = parse_enhancement_tree_wikitext(wikitext, page_title)
        if parsed is None:
            skipped += 1
            continue

        # Add metadata from index page
        parsed["type"] = ref["tree_type"]
        parsed["class_or_race"] = ref.get("parent", "") or None

        trees.append(parsed)
        tree_count += 1

        if on_progress and tree_count % 10 == 0:
            on_progress(f"  ... {tree_count} trees processed")

    # Direct tree pages (single trees not discovered from index pages)
    _DIRECT_TREES = [
        ("Reaper enhancements", "reaper", None),
    ]
    for page_title, tree_type, parent in _DIRECT_TREES:
        if page_title in visited:
            continue
        if 0 < limit <= tree_count:
            break
        wikitext = client.get_wikitext(page_title)
        if wikitext is None:
            continue
        parsed = parse_enhancement_tree_wikitext(wikitext, page_title)
        if parsed is None:
            continue
        parsed["type"] = tree_type
        parsed["class_or_race"] = parent
        trees.append(parsed)
        tree_count += 1
        visited.add(page_title)

    logger.info("Collected %d enhancement trees (%d skipped)", len(trees), skipped)
    return trees


def collect_filigrees(
    client: WikiClient,
    *,
    on_progress: Callable[[str], None] | None = None,
) -> list[dict]:
    """Scrape filigree data from the Sentient Weapon/Filigrees wiki page.

    Returns a list of dicts: {"name", "set_name", "rare_bonus", "bonus"}.
    """
    from .parsers import clean_wikitext

    wikitext = client.get_wikitext("Sentient Weapon/Filigrees")
    if not wikitext:
        logger.warning("Sentient Weapon/Filigrees page not found")
        return []

    filigrees: list[dict] = []
    for match in re.finditer(r'\|-\s*\n\|\s*(.+)', wikitext):
        row = match.group(1).strip()
        cells = [c.strip() for c in row.split("||")]
        if len(cells) < 2:
            continue

        name = clean_wikitext(cells[0])
        if not name or name == "Name" or name.startswith("Set"):
            continue

        set_name = name.split(": ", 1)[0].strip() if ": " in name else None
        rare_bonus = clean_wikitext(cells[1]) if len(cells) > 1 and cells[1].strip() else None
        bonus = clean_wikitext(cells[2]) if len(cells) > 2 and cells[2].strip() else None

        filigrees.append({
            "name": name,
            "set_name": set_name,
            "rare_bonus": rare_bonus,
            "bonus": bonus,
        })

    if on_progress:
        on_progress(f"  {len(filigrees)} filigrees parsed from wiki")

    return filigrees


_PIECE_RE = re.compile(
    r"(\d+)\s*(?:Pieces?\s*Equipped|pieces?)\s*:?\s*\n((?:\*[^\n]+\n)*)",
    re.IGNORECASE,
)


def collect_set_bonuses(
    client: WikiClient,
    *,
    on_progress: Callable[[str], None] | None = None,
) -> list[dict]:
    """Scrape set bonus effects from the Named_item_sets wiki page.

    Returns a list of dicts:
        {"name": "Seasons of the Feywild",
         "bonuses": [{"min_pieces": 2, "text": "+10 Artifact bonus to HP"}, ...]}
    """
    wikitext = client.get_wikitext("Named_item_sets")
    if not wikitext:
        logger.warning("Named_item_sets page not found")
        return []

    anchors = list(re.finditer(r"\{\{Anchor\|([^}]+)\}\}", wikitext))
    if on_progress:
        on_progress(f"Found {len(anchors)} set anchors on Named_item_sets page")

    results: list[dict] = []

    for i, anchor_match in enumerate(anchors):
        set_name = anchor_match.group(1).strip()
        start = anchor_match.end()
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(wikitext)
        section = wikitext[start:end]

        piece_matches = list(_PIECE_RE.finditer(section))
        if not piece_matches:
            continue

        bonuses: list[dict] = []
        for pm in piece_matches:
            pieces = int(pm.group(1))
            bonus_text = pm.group(2).strip()
            for line in bonus_text.split("\n"):
                line = line.strip().lstrip("*").strip()
                if line:
                    bonuses.append({"min_pieces": pieces, "text": line})

        if bonuses:
            results.append({"name": set_name, "bonuses": bonuses})

    if on_progress:
        on_progress(f"  {len(results)} sets with bonus effects parsed")

    return results


# Races whose feats are listed in wiki Category:<Race> feats pages.
_RACE_FEAT_CATEGORIES: dict[str, str] = {
    "Human": "Human feats",
    "Elf": "Elf feats",
    "Dwarf": "Dwarf feats",
    "Halfling": "Halfling feats",
    "Half-Elf": "Half-Elf feats",
    "Half-Orc": "Half-Orc feats",
    "Warforged": "Warforged feats",
    "Drow Elf": "Drow Elf feats",
    "Gnome": "Gnome feats",
    "Aasimar": "Aasimar feats",
    "Dragonborn": "Dragonborn feats",
    "Tiefling": "Tiefling feats",
    "Shifter": "Shifter feats",
    "Tabaxi": "Tabaxi feats",
    "Eladrin": "Eladrin feats",
    "Deep Gnome": "Deep Gnome feats",
}


def collect_race_feats(
    client: WikiClient,
    *,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, list[str]]:
    """Scrape racial feat lists from wiki category pages.

    Returns a dict mapping race name -> list of feat page titles.
    Feat titles may include "(feat)" suffixes that need stripping
    before matching against the feats table.
    """
    results: dict[str, list[str]] = {}
    for race_name, category in _RACE_FEAT_CATEGORIES.items():
        feat_titles = []
        for title in client.iter_category_members(category):
            # Skip sub-pages and category redirects
            if "/" in title or title.startswith("Category:"):
                continue
            # Strip "(feat)" suffix if present
            clean = re.sub(r"\s*\(feat\)$", "", title).strip()
            if clean:
                feat_titles.append(clean)
        results[race_name] = feat_titles
    total = sum(len(v) for v in results.values())
    if on_progress:
        on_progress(f"  {total} racial feats across {len(results)} races")
    return results


