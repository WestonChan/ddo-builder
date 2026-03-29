"""Named crafting system scrapers — Green Steel, Thunder-Forged, etc.

Each system has its own parser that returns a list of option dicts:
    {"system_id": int, "tier": str, "name": str, "description": str}
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

from ddo_data.enums import CraftingSystem

from .client import WikiClient

logger = logging.getLogger(__name__)


def _clean(text: str) -> str:
    """Strip wiki markup from text."""
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"'''?", "", text)
    text = re.sub(r"\{\{[^}]*\}\}", "", text)
    return text.strip()


def _extract_table_rows(wikitext: str) -> list[list[str]]:
    """Extract rows from a wikitable as lists of cell strings."""
    rows = []
    for row_text in re.split(r"\n\|-", wikitext):
        cells = []
        for cell in re.split(r"\|\|", row_text):
            cell = re.sub(r"^\s*[|!]\s*", "", cell)
            cleaned = _clean(cell)
            if cleaned:
                cells.append(cleaned)
        if cells:
            rows.append(cells)
    return rows


def _extract_sections(wikitext: str, level: int = 2) -> dict[str, str]:
    """Split wikitext into named sections by heading level."""
    marker = "=" * level
    pattern = rf"\n{marker}([^=]+){marker}\s*\n"
    parts = re.split(pattern, wikitext)
    sections = {}
    for i in range(1, len(parts), 2):
        name = parts[i].strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        sections[name] = body
    return sections


def _scrape_green_steel(client: WikiClient) -> list[dict]:
    """Scrape Green Steel options from the main items page."""
    options: list[dict] = []
    sys_id = CraftingSystem.GREEN_STEEL.id

    wikitext = client.get_wikitext("Green_Steel_items")
    if not wikitext:
        logger.warning("Could not fetch Green_Steel_items")
        return options

    sections = _extract_sections(wikitext, level=2)
    if not sections:
        sections = _extract_sections(wikitext, level=3)

    for section_name, body in sections.items():
        name = _clean(section_name)
        if not name or name.lower() in (
            "notes", "see also", "external links", "references",
            "gallery", "sources", "location", "recipes",
        ):
            continue

        # Check for subsections
        subsections = _extract_sections(body, level=3)
        if subsections:
            for sub_name, sub_body in subsections.items():
                sub_clean = _clean(sub_name)
                if not sub_clean:
                    continue
                effects = []
                for line in sub_body.split("\n"):
                    line = line.strip()
                    if line.startswith("*"):
                        effect = _clean(line.lstrip("*").strip())
                        if effect and len(effect) > 3:
                            effects.append(effect)
                desc = "; ".join(effects) if effects else _clean(sub_body[:500])
                if desc:
                    options.append({
                        "system_id": sys_id,
                        "tier": name,
                        "name": sub_clean,
                        "description": desc,
                    })
        else:
            # Extract bullet points as options
            effects = []
            for line in body.split("\n"):
                line = line.strip()
                if line.startswith("*") and not line.startswith("**"):
                    effect = _clean(line.lstrip("*").strip())
                    if effect and len(effect) > 3:
                        effects.append(effect)
            desc = "; ".join(effects) if effects else _clean(body[:500])
            if desc and len(desc) > 10:
                options.append({
                    "system_id": sys_id,
                    "tier": "General",
                    "name": name,
                    "description": desc,
                })

    return options


def _scrape_legendary_green_steel(client: WikiClient) -> list[dict]:
    """Scrape Legendary Green Steel tier options."""
    options: list[dict] = []
    sys_id = CraftingSystem.LEGENDARY_GREEN_STEEL.id

    for tier_num in range(1, 4):
        page = f"Legendary_Green_Steel_items/Tier_{tier_num}"
        wikitext = client.get_wikitext(page)
        if not wikitext:
            logger.warning("Could not fetch %s", page)
            continue

        tier = f"Tier {tier_num}"
        sections = _extract_sections(wikitext, level=3)
        if not sections:
            sections = _extract_sections(wikitext, level=2)

        for section_name, body in sections.items():
            name = _clean(section_name)
            if not name or name.lower() in ("notes", "see also", "ingredients", "overview"):
                continue

            effects = []
            for line in body.split("\n"):
                line = line.strip()
                if line.startswith("*") and not line.startswith("**"):
                    effect = _clean(line.lstrip("*").strip())
                    if effect:
                        effects.append(effect)

            desc = "; ".join(effects) if effects else _clean(body[:500])
            options.append({
                "system_id": sys_id,
                "tier": tier,
                "name": name,
                "description": desc,
            })

    # Also fetch Active slot
    wikitext = client.get_wikitext("Legendary_Green_Steel_items/Active")
    if wikitext:
        sections = _extract_sections(wikitext, level=3)
        if not sections:
            sections = _extract_sections(wikitext, level=2)
        for section_name, body in sections.items():
            name = _clean(section_name)
            if not name or name.lower() in ("notes", "see also", "ingredients", "overview"):
                continue
            effects = []
            for line in body.split("\n"):
                line = line.strip()
                if line.startswith("*") and not line.startswith("**"):
                    effect = _clean(line.lstrip("*").strip())
                    if effect:
                        effects.append(effect)
            desc = "; ".join(effects) if effects else _clean(body[:500])
            options.append({
                "system_id": sys_id,
                "tier": "Active",
                "name": name,
                "description": desc,
            })

    return options


def _scrape_thunder_forged(client: WikiClient) -> list[dict]:
    """Scrape Thunder-Forged tier options."""
    options: list[dict] = []
    sys_id = CraftingSystem.THUNDER_FORGED.id

    wikitext = client.get_wikitext("Thunder-Forged")
    if not wikitext:
        return options

    sections = _extract_sections(wikitext, level=2)

    for section_name, body in sections.items():
        name = _clean(section_name)
        # Identify tier from section name
        tier = None
        if "tier 1" in name.lower() or "first" in name.lower():
            tier = "Tier 1"
        elif "tier 2" in name.lower() or "second" in name.lower():
            tier = "Tier 2"
        elif "tier 3" in name.lower() or "third" in name.lower():
            tier = "Tier 3"
        elif "base" in name.lower():
            tier = "Base"

        if not tier:
            # Try matching subsections
            subsections = _extract_sections(body, level=3)
            for sub_name, sub_body in subsections.items():
                sub_clean = _clean(sub_name)
                effects = []
                for line in sub_body.split("\n"):
                    line = line.strip()
                    if line.startswith("*"):
                        effects.append(_clean(line.lstrip("*").strip()))
                desc = "; ".join(effects) if effects else _clean(sub_body[:500])
                if sub_clean and desc:
                    options.append({
                        "system_id": sys_id,
                        "tier": name,
                        "name": sub_clean,
                        "description": desc,
                    })
            continue

        # Extract options from bullet points
        for line in body.split("\n"):
            line = line.strip()
            if line.startswith("*") and not line.startswith("**"):
                opt_text = _clean(line.lstrip("*").strip())
                if opt_text and len(opt_text) > 5:
                    # Split name from description on first colon or dash
                    parts = re.split(r"[:\u2013\u2014]", opt_text, maxsplit=1)
                    opt_name = parts[0].strip()
                    opt_desc = parts[1].strip() if len(parts) > 1 else opt_text
                    options.append({
                        "system_id": sys_id,
                        "tier": tier,
                        "name": opt_name,
                        "description": opt_desc,
                    })

    return options


def _scrape_generic_system(
    client: WikiClient,
    page: str,
    system: CraftingSystem,
) -> list[dict]:
    """Scrape a crafting system by extracting sections and bullet points."""
    options: list[dict] = []
    sys_id = system.id

    wikitext = client.get_wikitext(page)
    if not wikitext:
        return options

    sections = _extract_sections(wikitext, level=2)
    for section_name, body in sections.items():
        tier = _clean(section_name)
        if not tier or tier.lower() in ("notes", "see also", "external links", "references", "gallery"):
            continue

        # Check for subsections (level 3)
        subsections = _extract_sections(body, level=3)
        if subsections:
            for sub_name, sub_body in subsections.items():
                name = _clean(sub_name)
                if not name:
                    continue
                effects = []
                for line in sub_body.split("\n"):
                    line = line.strip()
                    if line.startswith("*"):
                        effects.append(_clean(line.lstrip("*").strip()))
                desc = "; ".join(effects) if effects else _clean(sub_body[:500])
                if desc:
                    options.append({
                        "system_id": sys_id,
                        "tier": tier,
                        "name": name,
                        "description": desc,
                    })
        else:
            # No subsections — extract bullet points as individual options
            for line in body.split("\n"):
                line = line.strip()
                if line.startswith("*") and not line.startswith("**"):
                    opt_text = _clean(line.lstrip("*").strip())
                    if opt_text and len(opt_text) > 5:
                        parts = re.split(r"[:\u2013\u2014]", opt_text, maxsplit=1)
                        opt_name = parts[0].strip()
                        opt_desc = parts[1].strip() if len(parts) > 1 else opt_text
                        options.append({
                            "system_id": sys_id,
                            "tier": tier,
                            "name": opt_name,
                            "description": opt_desc,
                        })

    return options


def collect_crafting_systems(
    client: WikiClient,
    *,
    on_progress: Callable[[str], None] | None = None,
) -> list[dict]:
    """Scrape all named crafting systems from the wiki.

    Returns a flat list of option dicts ready for ``insert_crafting_options()``.
    """
    all_options: list[dict] = []

    systems = [
        ("Green Steel", _scrape_green_steel, [client]),
        ("Legendary Green Steel", _scrape_legendary_green_steel, [client]),
        ("Thunder-Forged", _scrape_thunder_forged, [client]),
        ("Alchemical", lambda c: _scrape_generic_system(c, "Alchemical_Crafting", CraftingSystem.ALCHEMICAL), [client]),
        ("Dragontouched Armor", lambda c: _scrape_generic_system(c, "Item:Dragontouched_Armor", CraftingSystem.DRAGONTOUCHED), [client]),
        ("Dinosaur Bone", lambda c: _scrape_generic_system(c, "Dinosaur_Bone_crafting", CraftingSystem.DINOSAUR_BONE), [client]),
        ("Slave Lords", lambda c: _scrape_generic_system(c, "Slave_Lords_Crafting", CraftingSystem.SLAVE_LORDS), [client]),
        # Remaining systems
        ("Stone of Change", lambda c: _scrape_generic_system(c, "Stone_of_Change", CraftingSystem.STONE_OF_CHANGE), [client]),
        ("Challenges", lambda c: _scrape_generic_system(c, "Challenges", CraftingSystem.CHALLENGES), [client]),
        ("Cauldron of Cadence", lambda c: _scrape_generic_system(c, "Cauldron_of_Cadence", CraftingSystem.CAULDRON_OF_CADENCE), [client]),
        ("Cauldron of Sora Katra", lambda c: _scrape_generic_system(c, "Cauldron_of_Sora_Katra", CraftingSystem.CAULDRON_OF_SORA_KATRA), [client]),
        ("Dragonscale Armor", lambda c: _scrape_generic_system(c, "Dragonscale_Armor", CraftingSystem.DRAGONSCALE), [client]),
        ("Stormreaver Monument", lambda c: _scrape_generic_system(c, "Stormreaver_Monument", CraftingSystem.STORMREAVER), [client]),
        ("Trace of Madness", lambda c: _scrape_generic_system(c, "Trace_of_Madness", CraftingSystem.TRACE_OF_MADNESS), [client]),
        ("Fountain of Necrotic Might", lambda c: _scrape_generic_system(c, "Fountain_of_Necrotic_Might", CraftingSystem.FOUNTAIN_OF_NECROTIC_MIGHT), [client]),
        ("Nearly Finished", lambda c: _scrape_generic_system(c, "Nearly_Finished", CraftingSystem.NEARLY_FINISHED), [client]),
        ("Incredible Potential", lambda c: _scrape_generic_system(c, "Incredible_Potential", CraftingSystem.INCREDIBLE_POTENTIAL), [client]),
        ("Suppressed Power", lambda c: _scrape_generic_system(c, "Suppressed_Power", CraftingSystem.SUPPRESSED_POWER), [client]),
        ("Lost Purpose", lambda c: _scrape_generic_system(c, "Lost_Purpose", CraftingSystem.LOST_PURPOSE), [client]),
        ("Unholy Defiler", lambda c: _scrape_generic_system(c, "Unholy_Defiler_of_the_Hidden_Hand", CraftingSystem.UNHOLY_DEFILER), [client]),
        ("Epic Crafting", lambda c: _scrape_generic_system(c, "Epic_Crafting", CraftingSystem.EPIC_CRAFTING), [client]),
        ("Mikrom Sum", lambda c: _scrape_generic_system(c, "Mikrom_Sum", CraftingSystem.MIKROM_SUM), [client]),
        ("Zhentarim Attuned", lambda c: _scrape_generic_system(c, "Zhentarim_Attuned", CraftingSystem.ZHENTARIM), [client]),
        ("Schism Shard", lambda c: _scrape_generic_system(c, "Schism_Shard_Crafting", CraftingSystem.SCHISM_SHARD), [client]),
        ("Legendary Crafting", lambda c: _scrape_generic_system(c, "Legendary_Crafting", CraftingSystem.LEGENDARY_CRAFTING), [client]),
        ("Nebula Fragment", lambda c: _scrape_generic_system(c, "Nebula_Fragment_Crafting", CraftingSystem.NEBULA_FRAGMENT), [client]),
        ("Soulforge", lambda c: _scrape_generic_system(c, "Soulforge", CraftingSystem.SOULFORGE), [client]),
        ("Esoteric Table", lambda c: _scrape_generic_system(c, "Esoteric_Table", CraftingSystem.ESOTERIC_TABLE), [client]),
        ("Ritual Table", lambda c: _scrape_generic_system(c, "Ritual_Table", CraftingSystem.RITUAL_TABLE), [client]),
        ("Augmentation Altar", lambda c: _scrape_generic_system(c, "Augmentation_Altar", CraftingSystem.AUGMENTATION_ALTAR), [client]),
        ("Reaper Forge", lambda c: _scrape_generic_system(c, "Reaper_Forge", CraftingSystem.REAPER_FORGE), [client]),
        ("Dampened", lambda c: _scrape_generic_system(c, "Dampened", CraftingSystem.DAMPENED), [client]),
        ("Viktranium", lambda c: _scrape_generic_system(c, "Viktranium_Experiment_crafting", CraftingSystem.VIKTRANIUM), [client]),
        ("Sentient Weapon", lambda c: _scrape_generic_system(c, "Sentient_Weapon", CraftingSystem.SENTIENT_WEAPON), [client]),
    ]

    for name, scraper, args in systems:
        if on_progress:
            on_progress(f"  Scraping {name}...")
        try:
            options = scraper(*args)
            all_options.extend(options)
            if on_progress:
                on_progress(f"    {len(options)} options")
        except Exception as exc:
            logger.warning("Failed to scrape %s: %s", name, exc)
            if on_progress:
                on_progress(f"    ERROR: {exc}")

    # Supplement with static data for systems whose wiki pages are guide-format
    from .crafting_static import get_all_static_options

    static = get_all_static_options()
    all_options.extend(static)
    if on_progress:
        on_progress(f"  {len(static)} static options added (GS, LGS, TF, Dino Bone)")

    return all_options
