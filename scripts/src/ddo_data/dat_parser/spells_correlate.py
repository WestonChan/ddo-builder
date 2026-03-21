"""Wiki cross-reference correlation engine for DDO spell entries.

Matches wiki spells (from {{Infobox-spell}} templates) to binary 0x47
entries by name, then statistically correlates ref slot values against
known wiki attributes to discover which positions encode which fields.

Key survey findings that shape this analysis:
  - Two DID types: 0x028B (50.6%) and 0x008B (49.1%)
  - Bodies are mostly 0-3 bytes (88%), but tail up to 1832 bytes
  - No 0x0A localization refs found in any slot (school is NOT an 0x0A string)
  - stat_def_ids (946, 947, 950, 708, 731) recur at variable slot positions
  - ref_count ranges from 0 to 252, with peaks at 6, 9, 11, 19, 27, 40
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .spells_survey import SpellEntry, SpellSurveyResult, survey_spell_entries

logger = logging.getLogger(__name__)


def _normalize_name(name: str) -> str:
    """Normalize a spell name for fuzzy matching."""
    return name.strip().replace("_", " ").lower()


@dataclass
class MatchedSpell:
    """A wiki spell matched to one or more binary entries."""

    wiki_name: str
    wiki: dict
    entries: list[SpellEntry]


@dataclass
class SlotCorrelation:
    """A discovered correlation between a ref slot and a wiki attribute."""

    slot_index: int
    wiki_field: str
    match_count: int
    total_checked: int
    samples: list[tuple[str, int, object]]
    """(spell_name, slot_value, wiki_value) triples."""

    @property
    def confidence(self) -> float:
        if self.total_checked == 0:
            return 0.0
        return self.match_count / self.total_checked


@dataclass
class DIDAnalysis:
    """Analysis of how DID type relates to spell attributes."""

    did: int
    count: int
    named_count: int
    wiki_matched: int
    avg_ref_count: float
    avg_body_size: float


@dataclass
class VariantAnalysis:
    """Analysis of class variants for a single spell name."""

    name: str
    variant_count: int
    dids: list[int]
    ref_counts: list[int]
    slot1_values: list[int]
    # Slots that differ between variants
    differing_slots: list[int]
    # Slots that are constant across variants
    constant_slots: list[int]


@dataclass
class SpellCorrelationResult:
    """Complete results from wiki cross-reference correlation."""

    total_wiki_spells: int = 0
    matched_wiki_spells: int = 0
    total_binary_matches: int = 0

    matched_spells: list[MatchedSpell] = field(default_factory=list)
    slot_correlations: list[SlotCorrelation] = field(default_factory=list)

    did_analysis: list[DIDAnalysis] = field(default_factory=list)
    variant_analyses: list[VariantAnalysis] = field(default_factory=list)

    # Per-DID slot correlations
    did_028b_correlations: list[SlotCorrelation] = field(default_factory=list)
    did_008b_correlations: list[SlotCorrelation] = field(default_factory=list)


def match_wiki_spells(
    survey: SpellSurveyResult,
    wiki_spells: list[dict],
) -> list[MatchedSpell]:
    """Match wiki spells to binary entries by normalized name."""
    # Build name -> entries lookup
    entries_by_name: dict[str, list[SpellEntry]] = defaultdict(list)
    for entry in survey.entries:
        if entry.name:
            entries_by_name[_normalize_name(entry.name)].append(entry)

    matched: list[MatchedSpell] = []
    for wiki_spell in wiki_spells:
        wiki_name = wiki_spell.get("name")
        if not wiki_name:
            continue
        norm = _normalize_name(wiki_name)
        entries = entries_by_name.get(norm, [])
        if entries:
            matched.append(MatchedSpell(
                wiki_name=wiki_name,
                wiki=wiki_spell,
                entries=entries,
            ))

    return matched


def _correlate_numeric_field(
    matched: list[MatchedSpell],
    wiki_field: str,
    max_slot: int = 30,
    *,
    did_filter: int | None = None,
) -> list[SlotCorrelation]:
    """Check every slot position for values matching a wiki numeric field.

    For each slot index 0..max_slot, counts how many matched spells have
    a ref value at that slot equal to the wiki field value. Returns
    correlations sorted by confidence (descending).
    """
    correlations: list[SlotCorrelation] = []

    for slot_idx in range(max_slot):
        match_count = 0
        total = 0
        samples: list[tuple[str, int, object]] = []

        for ms in matched:
            wiki_val = ms.wiki.get(wiki_field)
            if wiki_val is None or not isinstance(wiki_val, (int, float)):
                continue

            wiki_int = int(wiki_val)

            for entry in ms.entries:
                if did_filter is not None and entry.did != did_filter:
                    continue
                if slot_idx >= len(entry.refs):
                    continue

                total += 1
                slot_val = entry.refs[slot_idx]
                if slot_val == wiki_int:
                    match_count += 1
                    if len(samples) < 5:
                        samples.append((ms.wiki_name, slot_val, wiki_int))

        if match_count > 0:
            correlations.append(SlotCorrelation(
                slot_index=slot_idx,
                wiki_field=wiki_field,
                match_count=match_count,
                total_checked=total,
                samples=samples,
            ))

    correlations.sort(key=lambda c: -c.confidence)
    return correlations


def _correlate_school_enum(
    matched: list[MatchedSpell],
    max_slot: int = 30,
    *,
    did_filter: int | None = None,
) -> list[SlotCorrelation]:
    """Search for a slot that encodes school as a consistent integer enum.

    Since we know school is NOT a 0x0A string ref, it must be an integer
    code. For each slot, check if the same slot value always maps to the
    same school across different spells.
    """
    schools = [
        "Abjuration", "Conjuration", "Divination", "Enchantment",
        "Evocation", "Illusion", "Necromancy", "Transmutation", "Universal",
    ]
    school_lower = {s.lower(): s for s in schools}

    correlations: list[SlotCorrelation] = []

    for slot_idx in range(max_slot):
        # Build value -> set of schools mapping
        value_to_schools: dict[int, set[str]] = defaultdict(set)
        total = 0

        for ms in matched:
            wiki_school = ms.wiki.get("school")
            if not wiki_school:
                continue
            norm_school = wiki_school.strip().lower()
            if norm_school not in school_lower:
                continue
            canon_school = school_lower[norm_school]

            for entry in ms.entries:
                if did_filter is not None and entry.did != did_filter:
                    continue
                if slot_idx >= len(entry.refs):
                    continue
                total += 1
                value_to_schools[entry.refs[slot_idx]].add(canon_school)

        if not value_to_schools or total == 0:
            continue

        # A good school slot: each value maps to exactly ONE school
        consistent = sum(
            1 for schools_set in value_to_schools.values()
            if len(schools_set) == 1
        )
        total_values = len(value_to_schools)

        if total_values > 0 and consistent / total_values > 0.7:
            # Build code -> school mapping from consistent values
            samples = []
            for val, schools_set in sorted(
                value_to_schools.items(),
                key=lambda kv: len(kv[1]),
            )[:5]:
                if len(schools_set) == 1:
                    school = next(iter(schools_set))
                    samples.append(("enum", val, school))

            correlations.append(SlotCorrelation(
                slot_index=slot_idx,
                wiki_field="school (enum)",
                match_count=consistent,
                total_checked=total_values,
                samples=samples,
            ))

    correlations.sort(key=lambda c: -c.confidence)
    return correlations


def _analyze_variants(matched: list[MatchedSpell]) -> list[VariantAnalysis]:
    """Analyze class variants — which slots differ between variants of the same spell."""
    analyses: list[VariantAnalysis] = []

    for ms in matched:
        if len(ms.entries) < 2:
            continue

        entries = ms.entries
        min_refs = min(e.ref_count for e in entries)
        if min_refs < 3:
            continue

        # Compare slots across variants
        differing: list[int] = []
        constant: list[int] = []

        for slot_idx in range(min_refs):
            values = {e.refs[slot_idx] for e in entries if slot_idx < len(e.refs)}
            if len(values) > 1:
                differing.append(slot_idx)
            else:
                constant.append(slot_idx)

        analyses.append(VariantAnalysis(
            name=ms.wiki_name,
            variant_count=len(entries),
            dids=[e.did for e in entries],
            ref_counts=[e.ref_count for e in entries],
            slot1_values=[e.slot1_variant for e in entries],
            differing_slots=differing,
            constant_slots=constant,
        ))

    analyses.sort(key=lambda a: -a.variant_count)
    return analyses


def _analyze_dids(
    survey: SpellSurveyResult,
    matched: list[MatchedSpell],
) -> list[DIDAnalysis]:
    """Analyze DID types and their relationship to spell attributes."""
    # Group entries by DID
    did_entries: dict[int, list[SpellEntry]] = defaultdict(list)
    for entry in survey.entries:
        did_entries[entry.did].append(entry)

    # Count wiki-matched per DID
    matched_names = {_normalize_name(ms.wiki_name) for ms in matched}
    did_wiki_matched: dict[int, int] = defaultdict(int)
    for entry in survey.entries:
        if entry.name and _normalize_name(entry.name) in matched_names:
            did_wiki_matched[entry.did] += 1

    analyses: list[DIDAnalysis] = []
    for did in sorted(did_entries, key=lambda d: -len(did_entries[d]))[:10]:
        entries = did_entries[did]
        analyses.append(DIDAnalysis(
            did=did,
            count=len(entries),
            named_count=sum(1 for e in entries if e.name),
            wiki_matched=did_wiki_matched.get(did, 0),
            avg_ref_count=sum(e.ref_count for e in entries) / len(entries),
            avg_body_size=sum(e.body_size for e in entries) / len(entries),
        ))

    return analyses


def _correlate_class_level_field(
    matched: list[MatchedSpell],
    max_slot: int = 30,
    *,
    did_filter: int | None = None,
) -> list[SlotCorrelation]:
    """Search for slots encoding per-class spell levels.

    Wiki spells have class_levels like {"Wizard": 3, "Cleric": 4}.
    Look for slots where the value matches ANY class level.
    """
    correlations: list[SlotCorrelation] = []

    for slot_idx in range(max_slot):
        match_count = 0
        total = 0
        samples: list[tuple[str, int, object]] = []

        for ms in matched:
            class_levels = ms.wiki.get("class_levels", {})
            if not class_levels:
                continue

            level_values = set(class_levels.values())

            for entry in ms.entries:
                if did_filter is not None and entry.did != did_filter:
                    continue
                if slot_idx >= len(entry.refs):
                    continue

                total += 1
                slot_val = entry.refs[slot_idx]
                if slot_val in level_values:
                    match_count += 1
                    if len(samples) < 5:
                        matched_levels = {
                            cls: lvl for cls, lvl in class_levels.items()
                            if lvl == slot_val
                        }
                        samples.append((ms.wiki_name, slot_val, matched_levels))

        if match_count > 0:
            correlations.append(SlotCorrelation(
                slot_index=slot_idx,
                wiki_field="class_level",
                match_count=match_count,
                total_checked=total,
                samples=samples,
            ))

    correlations.sort(key=lambda c: -c.confidence)
    return correlations


def run_correlation(
    ddo_path: Path,
    wiki_spells: list[dict],
    *,
    on_progress: Callable[[str], None] | None = None,
) -> SpellCorrelationResult:
    """Run full wiki cross-reference correlation on spell entries."""
    log = on_progress or (lambda msg: None)
    result = SpellCorrelationResult()

    # Phase 1: Survey
    log("Running spell survey...")
    survey = survey_spell_entries(ddo_path, on_progress=on_progress)

    # Phase 2: Match wiki spells
    log(f"\nMatching {len(wiki_spells)} wiki spells to binary entries...")
    matched = match_wiki_spells(survey, wiki_spells)
    result.total_wiki_spells = len(wiki_spells)
    result.matched_wiki_spells = len(matched)
    result.total_binary_matches = sum(len(ms.entries) for ms in matched)
    result.matched_spells = matched
    log(f"  {len(matched)} wiki spells matched "
        f"({result.total_binary_matches} binary entries)")

    # Phase 3: DID analysis
    log("\nAnalyzing DID types...")
    result.did_analysis = _analyze_dids(survey, matched)
    for da in result.did_analysis[:3]:
        log(f"  DID 0x{da.did:08X}: {da.count:,} entries, "
            f"{da.wiki_matched} wiki-matched, "
            f"avg ref_count={da.avg_ref_count:.1f}, "
            f"avg body_size={da.avg_body_size:.1f}")

    # Phase 4: Variant analysis
    log("\nAnalyzing class variants...")
    result.variant_analyses = _analyze_variants(matched)
    multi = [va for va in result.variant_analyses if va.variant_count >= 2]
    log(f"  {len(multi)} spells with 2+ variants")

    # Phase 5: Numeric field correlations
    log("\nCorrelating numeric fields across all entries...")
    for wiki_field in ["spell_points", "level"]:
        corrs = _correlate_numeric_field(matched, wiki_field)
        result.slot_correlations.extend(corrs[:5])
        if corrs:
            best = corrs[0]
            log(f"  {wiki_field}: best slot {best.slot_index} "
                f"({best.match_count}/{best.total_checked} = "
                f"{best.confidence:.1%})")

    # Class level correlations
    log("\nCorrelating class levels...")
    level_corrs = _correlate_class_level_field(matched)
    result.slot_correlations.extend(level_corrs[:5])
    if level_corrs:
        best = level_corrs[0]
        log(f"  class_level: best slot {best.slot_index} "
            f"({best.match_count}/{best.total_checked} = "
            f"{best.confidence:.1%})")

    # School enum correlations
    log("\nCorrelating school (as integer enum)...")
    school_corrs = _correlate_school_enum(matched)
    result.slot_correlations.extend(school_corrs[:5])
    if school_corrs:
        best = school_corrs[0]
        log(f"  school: best slot {best.slot_index} "
            f"({best.match_count}/{best.total_checked} = "
            f"{best.confidence:.1%})")
        for sample in best.samples[:5]:
            log(f"    value {sample[1]} -> {sample[2]}")

    # Per-DID correlations
    log("\nCorrelating per-DID (0x028B)...")
    for wiki_field in ["spell_points", "level"]:
        corrs = _correlate_numeric_field(matched, wiki_field, did_filter=0x028B)
        result.did_028b_correlations.extend(corrs[:3])
        if corrs:
            best = corrs[0]
            log(f"  DID 0x028B {wiki_field}: slot {best.slot_index} "
                f"({best.match_count}/{best.total_checked} = "
                f"{best.confidence:.1%})")

    school_028b = _correlate_school_enum(matched, did_filter=0x028B)
    result.did_028b_correlations.extend(school_028b[:3])
    if school_028b:
        best = school_028b[0]
        log(f"  DID 0x028B school: slot {best.slot_index} "
            f"({best.match_count}/{best.total_checked} = "
            f"{best.confidence:.1%})")

    log("\nCorrelating per-DID (0x008B)...")
    for wiki_field in ["spell_points", "level"]:
        corrs = _correlate_numeric_field(matched, wiki_field, did_filter=0x008B)
        result.did_008b_correlations.extend(corrs[:3])
        if corrs:
            best = corrs[0]
            log(f"  DID 0x008B {wiki_field}: slot {best.slot_index} "
                f"({best.match_count}/{best.total_checked} = "
                f"{best.confidence:.1%})")

    school_008b = _correlate_school_enum(matched, did_filter=0x008B)
    result.did_008b_correlations.extend(school_008b[:3])
    if school_008b:
        best = school_008b[0]
        log(f"  DID 0x008B school: slot {best.slot_index} "
            f"({best.match_count}/{best.total_checked} = "
            f"{best.confidence:.1%})")

    return result


def format_correlation(result: SpellCorrelationResult) -> str:
    """Format correlation results as a human-readable report."""
    lines: list[str] = []

    lines.append("Spell Wiki Correlation Report")
    lines.append("=" * 40)
    lines.append(f"Wiki spells: {result.total_wiki_spells}")
    lines.append(f"Matched to binary: {result.matched_wiki_spells} "
                 f"({result.total_binary_matches} binary entries)")
    lines.append("")

    # DID analysis
    lines.append("DID Analysis:")
    for da in result.did_analysis:
        lines.append(f"  0x{da.did:08X}: {da.count:>6,} entries, "
                     f"{da.wiki_matched:>4} wiki-matched, "
                     f"avg_refs={da.avg_ref_count:.1f}, "
                     f"avg_body={da.avg_body_size:.1f}")
    lines.append("")

    # Variant analysis
    multi = [va for va in result.variant_analyses if va.variant_count >= 3]
    if multi:
        lines.append(f"Variant Analysis ({len(multi)} spells with 3+ variants):")
        for va in multi[:15]:
            diff = ", ".join(str(s) for s in va.differing_slots[:10])
            const = ", ".join(str(s) for s in va.constant_slots[:10])
            lines.append(f"  {va.name!r} x{va.variant_count}: "
                         f"diff=[{diff}] const=[{const}]")
        lines.append("")

    # Slot correlations
    if result.slot_correlations:
        lines.append("Slot Correlations (all entries):")
        for sc in sorted(result.slot_correlations, key=lambda c: -c.confidence):
            if sc.confidence < 0.01:
                continue
            lines.append(f"  Slot {sc.slot_index:>2d} ~ {sc.wiki_field}: "
                         f"{sc.match_count}/{sc.total_checked} "
                         f"({sc.confidence:.1%})")
            for name, sval, wval in sc.samples[:3]:
                lines.append(f"    {name}: slot={sval}, wiki={wval}")
        lines.append("")

    # Per-DID correlations
    for did_label, corrs in [
        ("DID 0x028B", result.did_028b_correlations),
        ("DID 0x008B", result.did_008b_correlations),
    ]:
        if corrs:
            lines.append(f"Slot Correlations ({did_label}):")
            for sc in sorted(corrs, key=lambda c: -c.confidence):
                if sc.confidence < 0.01:
                    continue
                lines.append(f"  Slot {sc.slot_index:>2d} ~ {sc.wiki_field}: "
                             f"{sc.match_count}/{sc.total_checked} "
                             f"({sc.confidence:.1%})")
                for name, sval, wval in sc.samples[:3]:
                    lines.append(f"    {name}: slot={sval}, wiki={wval}")
            lines.append("")

    return "\n".join(lines)


def format_correlation_json(result: SpellCorrelationResult) -> dict:
    """Format correlation results as JSON-serializable dict."""
    return {
        "summary": {
            "total_wiki_spells": result.total_wiki_spells,
            "matched_wiki_spells": result.matched_wiki_spells,
            "total_binary_matches": result.total_binary_matches,
        },
        "did_analysis": [
            {
                "did": f"0x{da.did:08X}",
                "count": da.count,
                "named_count": da.named_count,
                "wiki_matched": da.wiki_matched,
                "avg_ref_count": round(da.avg_ref_count, 1),
                "avg_body_size": round(da.avg_body_size, 1),
            }
            for da in result.did_analysis
        ],
        "slot_correlations": [
            {
                "slot": sc.slot_index,
                "field": sc.wiki_field,
                "matches": sc.match_count,
                "total": sc.total_checked,
                "confidence": round(sc.confidence, 3),
                "samples": [
                    {"name": n, "slot_value": sv, "wiki_value": wv}
                    for n, sv, wv in sc.samples[:5]
                ],
            }
            for sc in result.slot_correlations
            if sc.confidence >= 0.01
        ],
        "variant_analyses": [
            {
                "name": va.name,
                "variants": va.variant_count,
                "differing_slots": va.differing_slots[:20],
                "constant_slots": va.constant_slots[:20],
            }
            for va in result.variant_analyses[:20]
        ],
    }
