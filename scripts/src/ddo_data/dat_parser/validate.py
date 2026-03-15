"""Cross-archive validation harness for TLV hypothesis testing.

Tests TLV hypotheses against real DDO game data by checking whether
property values that look like file references actually resolve to
known file IDs across the three archives.
"""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .archive import DatArchive, FileEntry
from .extract import read_entry_data, scan_file_table
from .tagged import _KNOWN_ID_HIGH_BYTES, scan_tlv


@dataclass
class ValidationResult:
    """Scoring result for a single TLV hypothesis against real data."""

    hypothesis: str
    entries_tested: int = 0
    entries_parsed: int = 0
    total_properties: int = 0
    avg_coverage: float = 0.0
    total_errors: int = 0
    ref_candidates: int = 0
    ref_valid: int = 0

    @property
    def parse_rate(self) -> float:
        """Fraction of entries where the hypothesis parsed >= 1 property."""
        if self.entries_tested == 0:
            return 0.0
        return self.entries_parsed / self.entries_tested

    @property
    def ref_accuracy(self) -> float:
        """Fraction of cross-reference candidates that resolved to real IDs."""
        if self.ref_candidates == 0:
            return 0.0
        return self.ref_valid / self.ref_candidates


def build_known_id_set(ddo_path: Path) -> dict[int, set[int]]:
    """Scan all three DDO archives and collect known file IDs.

    Returns a dict mapping high-byte -> set of full file IDs.
    E.g. {0x01: {0x01000001, ...}, 0x07: {...}, 0x0A: {...}}
    """
    dat_names = [
        "client_gamelogic.dat",
        "client_local_English.dat",
        "client_general.dat",
    ]

    known: defaultdict[int, set[int]] = defaultdict(set)

    for name in dat_names:
        dat_file = ddo_path / name
        if not dat_file.exists():
            continue

        archive = DatArchive(dat_file)
        archive.read_header()
        entries = scan_file_table(archive)

        for file_id in entries:
            high_byte = (file_id >> 24) & 0xFF
            known[high_byte].add(file_id)

    return dict(known)


def _flat_known_ids(known: dict[int, set[int]]) -> set[int]:
    """Flatten the known ID dict into a single set."""
    result: set[int] = set()
    for ids in known.values():
        result.update(ids)
    return result


def validate_hypothesis(
    archive: DatArchive,
    entries: dict[int, FileEntry],
    known_ids: set[int],
    hypothesis: str,
    sample_size: int = 200,
) -> ValidationResult:
    """Run a TLV hypothesis against real entries and score it.

    Scoring dimensions:
    - Parse rate: fraction of entries where the hypothesis found >= 1 property
    - Average coverage: mean bytes_parsed/bytes_total across entries
    - Cross-reference accuracy: fraction of file-ref-like values that resolve
    - Error rate: total parse errors
    """
    result = ValidationResult(hypothesis=hypothesis)

    sorted_ids = sorted(entries.keys())
    if sample_size > 0 and len(sorted_ids) > sample_size:
        step = len(sorted_ids) / sample_size
        sampled_ids = [sorted_ids[int(i * step)] for i in range(sample_size)]
    else:
        sampled_ids = sorted_ids

    coverage_sum = 0.0

    for file_id in sampled_ids:
        entry = entries[file_id]
        try:
            data = read_entry_data(archive, entry)
        except (ValueError, OSError):
            continue

        if len(data) < 8:
            continue

        result.entries_tested += 1

        tlv = scan_tlv(data, hypothesis)
        result.total_errors += tlv.errors
        coverage_sum += tlv.coverage

        if tlv.properties:
            result.entries_parsed += 1
            result.total_properties += len(tlv.properties)

            for prop in tlv.properties:
                val = prop.as_uint32
                if val is None:
                    continue
                high_byte = (val >> 24) & 0xFF
                if high_byte in _KNOWN_ID_HIGH_BYTES and (val & 0x00FFFFFF) != 0:
                    result.ref_candidates += 1
                    if val in known_ids:
                        result.ref_valid += 1

    if result.entries_tested > 0:
        result.avg_coverage = coverage_sum / result.entries_tested

    return result


def format_validation_result(result: ValidationResult) -> str:
    """Format a validation result as a human-readable report."""
    lines = [
        f"Hypothesis {result.hypothesis}:",
        f"  Entries tested:       {result.entries_tested}",
        f"  Parse rate:           {result.parse_rate:.1%}"
        f" ({result.entries_parsed}/{result.entries_tested})",
        f"  Avg coverage:         {result.avg_coverage:.1%}",
        f"  Total properties:     {result.total_properties:,}",
        f"  Total errors:         {result.total_errors:,}",
        f"  Cross-ref candidates: {result.ref_candidates:,}",
        f"  Cross-ref valid:      {result.ref_valid:,}"
        f" ({result.ref_accuracy:.1%})",
    ]
    return "\n".join(lines)


def run_validation(ddo_path: Path, sample_size: int = 200) -> str:
    """Run all TLV hypotheses against real DDO data and return a comparison."""
    known = build_known_id_set(ddo_path)
    flat_ids = _flat_known_ids(known)

    total_known = sum(len(ids) for ids in known.values())
    lines = [
        "Cross-Archive Validation Report",
        "=" * 40,
        f"Known file IDs: {total_known:,} across {len(known)} archives",
    ]
    for high_byte, ids in sorted(known.items()):
        lines.append(f"  0x{high_byte:02X}XXXXXX: {len(ids):,} entries")
    lines.append("")

    gamelogic_path = ddo_path / "client_gamelogic.dat"
    if not gamelogic_path.exists():
        return "\n".join(lines + ["ERROR: client_gamelogic.dat not found"])

    archive = DatArchive(gamelogic_path)
    archive.read_header()
    entries = scan_file_table(archive)

    lines.append(f"Gamelogic entries: {len(entries):,}")
    lines.append(f"Sample size: {sample_size}")
    lines.append("")

    results = []
    for hypothesis in ("A", "B", "C"):
        hyp_result = validate_hypothesis(
            archive, entries, flat_ids, hypothesis, sample_size,
        )
        results.append(hyp_result)
        lines.append(format_validation_result(hyp_result))
        lines.append("")

    results.sort(key=lambda r: (r.ref_accuracy, r.avg_coverage), reverse=True)
    winner = results[0]
    lines.append("-" * 40)
    lines.append(
        f"Best hypothesis: {winner.hypothesis}"
        f" (ref_accuracy={winner.ref_accuracy:.1%},"
        f" coverage={winner.avg_coverage:.1%})"
    )

    return "\n".join(lines)
