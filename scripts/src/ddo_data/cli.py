"""CLI entry point for DDO data pipeline."""

import os
from pathlib import Path

import click
from dotenv import load_dotenv

# Load .env from project root (two levels up from scripts/src/ddo_data/)
load_dotenv(Path(__file__).resolve().parents[4] / ".env")

_FALLBACK_DDO_PATH = (
    Path.home()
    / "Library/Application Support/CrossOver/Bottles/Steam"
    / "drive_c/Program Files (x86)/Steam/steamapps/common/Dungeons and Dragons Online"
)
DEFAULT_DDO_PATH = Path(os.environ["DDO_PATH"]) if "DDO_PATH" in os.environ else _FALLBACK_DDO_PATH


def get_dat_files(ddo_path: Path) -> list[Path]:
    """Return sorted list of DDO client .dat archive files in the given directory."""
    return sorted(p for p in ddo_path.glob("client_*.dat"))


def _parse_hex_int(value: str) -> int:
    """Parse a hex (0x...) or decimal string into an integer."""
    return int(value, 16) if value.startswith("0x") else int(value)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--ddo-path",
    type=click.Path(path_type=Path),
    default=DEFAULT_DDO_PATH,
    help="Path to DDO installation directory",
)
@click.pass_context
def cli(ctx: click.Context, ddo_path: Path) -> None:
    """DDO Data Pipeline - Extract and process game data."""
    ctx.ensure_object(dict)
    ctx.obj["ddo_path"] = ddo_path


@cli.command()
@click.pass_context
def info(ctx: click.Context) -> None:
    """Show information about the DDO installation."""
    ddo_path: Path = ctx.obj["ddo_path"]
    click.echo(f"DDO Install Path: {ddo_path}")

    if not ddo_path.exists():
        click.echo("WARNING: DDO installation not found at this path!")
        return

    dat_files = get_dat_files(ddo_path)
    click.echo(f"\nFound {len(dat_files)} .dat files:")
    for f in dat_files:
        size_mb = f.stat().st_size / (1024 * 1024)
        click.echo(f"  {f.name:40s} {size_mb:>8.1f} MB")


@cli.command()
@click.argument("dat_file", type=click.Path(exists=True, path_type=Path))
def parse(dat_file: Path) -> None:
    """Parse a .dat archive file and show its header info."""
    from ddo_data.dat_parser import DatArchive

    archive = DatArchive(dat_file)
    archive.read_header()
    click.echo(archive.header_info())


@cli.command(name="list")
@click.argument("dat_file", type=click.Path(exists=True, path_type=Path))
@click.option("--limit", "-n", type=int, default=0, help="Show only first N entries")
def list_entries(dat_file: Path, limit: int) -> None:
    """List all files in a .dat archive."""
    from ddo_data.dat_parser import DatArchive, scan_file_table

    archive = DatArchive(dat_file)
    archive.read_header()
    click.echo(f"Scanning {dat_file.name}...")

    entries = scan_file_table(archive)
    sorted_entries = sorted(entries.values(), key=lambda e: e.file_id)

    if limit > 0:
        sorted_entries = sorted_entries[:limit]

    click.echo(f"{'File ID':>12s}  {'Offset':>12s}  {'Size':>10s}  {'Disk Size':>10s}  {'Flags':>10s}")
    click.echo("-" * 62)

    for entry in sorted_entries:
        click.echo(
            f"  0x{entry.file_id:08X}  0x{entry.data_offset:08X}  "
            f"{entry.size:>10,}  {entry.disk_size:>10,}  0x{entry.flags:08X}"
        )

    click.echo("-" * 62)
    total_size = sum(e.size for e in entries.values())
    total_mb = total_size / (1024 * 1024)
    click.echo(
        f"{len(entries):,} entries found ({total_mb:.1f} MB total)"
    )
    if limit > 0 and limit < len(entries):
        click.echo(f"(showing first {limit} of {len(entries):,})")


@cli.command(name="dat-extract")
@click.argument("dat_file", type=click.Path(exists=True, path_type=Path))
@click.option("--id", "file_id", type=str, default=None, help="Extract a specific file by hex ID (e.g. 0x0A003E4F)")
@click.option(
    "--output", "-o", type=click.Path(path_type=Path),
    default=Path("/tmp/ddo-extract"), help="Output directory",
)
def dat_extract(dat_file: Path, file_id: str | None, output: Path) -> None:
    """Extract raw files from a .dat archive."""
    from ddo_data.dat_parser import DatArchive, extract_entry, scan_file_table

    archive = DatArchive(dat_file)
    archive.read_header()
    click.echo(f"Scanning {dat_file.name}...")

    entries = scan_file_table(archive)
    click.echo(f"Found {len(entries):,} entries")

    if file_id is not None:
        fid = _parse_hex_int(file_id)
        if fid not in entries:
            click.echo(f"File ID 0x{fid:08X} not found in archive")
            return

        out_path = extract_entry(archive, entries[fid], output)
        click.echo(f"Extracted: {out_path}")
    else:
        click.echo(f"Extracting all {len(entries):,} entries to {output}/")
        errors = 0
        for i, entry in enumerate(sorted(entries.values(), key=lambda e: e.file_id)):
            try:
                extract_entry(archive, entry, output)
            except (ValueError, OSError) as e:
                errors += 1
                if errors <= 10:
                    click.echo(f"  Skip 0x{entry.file_id:08X}: {e}")
                elif errors == 11:
                    click.echo("  (suppressing further errors)")

            if (i + 1) % 1000 == 0:
                click.echo(f"  {i + 1:,} / {len(entries):,}...")

        click.echo(f"Done. Extracted {len(entries) - errors:,} files ({errors} errors)")


@cli.command(name="dat-peek")
@click.argument("dat_file", type=click.Path(exists=True, path_type=Path))
@click.option("--id", "file_id", type=str, required=True, help="File ID in hex (e.g. 0x07001234)")
@click.option("--limit", "-n", type=int, default=256, help="Number of bytes to show")
def dat_peek(dat_file: Path, file_id: str, limit: int) -> None:
    """Hex dump of a single entry's raw data block."""
    from ddo_data.dat_parser import DatArchive, scan_file_table
    from ddo_data.dat_parser.utils import hex_dump

    archive = DatArchive(dat_file)
    entries = scan_file_table(archive)

    fid = _parse_hex_int(file_id)
    if fid not in entries:
        click.echo(f"File ID 0x{fid:08X} not found in archive")
        return

    entry = entries[fid]
    click.echo(
        f"Entry 0x{fid:08X}  offset=0x{entry.data_offset:08X}  size={entry.size:,}"
        f"  disk_size={entry.disk_size:,}  flags=0x{entry.flags:08X}"
    )
    compressed = "yes" if entry.is_compressed else "no"
    cmp_op = "<" if entry.is_compressed else ">="
    click.echo(f"Compressed: {compressed} (disk_size {cmp_op} size+8)")
    click.echo()

    read_size = entry.disk_size if entry.disk_size > 0 else entry.size + 8
    with open(dat_file, "rb") as f:
        f.seek(entry.data_offset)
        raw = f.read(min(read_size, limit))

    # Hex dump with structure annotations
    dump = hex_dump(raw, offset=entry.data_offset, limit=limit)
    lines = dump.split("\n")
    for i, line in enumerate(lines):
        if i == 0:
            line += "  <- block hdr + file_id + type"
        elif i == 1:
            line += "  <- content start"
        click.echo(line)


@cli.command(name="dat-stats")
@click.argument("dat_file", type=click.Path(exists=True, path_type=Path))
def dat_stats(dat_file: Path) -> None:
    """Show compression and file type statistics for a .dat archive."""
    from ddo_data.dat_parser import DatArchive, read_entry_data, scan_file_table
    from ddo_data.dat_parser.extract import identify_content_type

    archive = DatArchive(dat_file)
    archive.read_header()
    click.echo(f"Scanning {dat_file.name}...")

    entries = scan_file_table(archive)
    click.echo(f"Found {len(entries):,} entries (header says {archive.header.file_count:,})")
    click.echo()

    compressed = 0
    uncompressed = 0
    type_counts: dict[str, int] = {}
    errors = 0
    total_size = 0
    total_disk_size = 0

    for entry in entries.values():
        total_size += entry.size
        total_disk_size += entry.disk_size
        if entry.is_compressed:
            compressed += 1
        else:
            uncompressed += 1

    click.echo("Compression:")
    click.echo(f"  Compressed:   {compressed:>8,}  ({100 * compressed / max(len(entries), 1):.1f}%)")
    click.echo(f"  Uncompressed: {uncompressed:>8,}  ({100 * uncompressed / max(len(entries), 1):.1f}%)")
    click.echo(f"  Total size:   {total_size / (1024 * 1024):>8.1f} MB (uncompressed)")
    click.echo(f"  Disk size:    {total_disk_size / (1024 * 1024):>8.1f} MB (on-disk)")
    click.echo()

    # Sample first N uncompressed entries to detect file types by magic bytes
    click.echo("File types (sampled from first 200 uncompressed entries):")
    sampled = 0
    for entry in sorted(entries.values(), key=lambda e: e.file_id):
        if sampled >= 200:
            break
        if entry.is_compressed:
            continue  # skip compressed for now
        try:
            data = read_entry_data(archive, entry)
            content_type = identify_content_type(data[:8])
            type_counts[content_type] = type_counts.get(content_type, 0) + 1
            sampled += 1
        except (ValueError, OSError):
            errors += 1

    for content_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        click.echo(f"  {content_type:<20s} {count:>6,}")
    if errors:
        click.echo(f"  (read errors)       {errors:>6,}")


@cli.command(name="dat-dump")
@click.argument("dat_file", type=click.Path(exists=True, path_type=Path))
@click.option("--id", "file_id", type=str, required=True, help="File ID in hex (e.g. 0x07001234)")
@click.option("--limit", "-n", type=int, default=512, help="Max bytes to dump")
def dat_dump(dat_file: Path, file_id: str, limit: int) -> None:
    """Extract, decompress, and hex dump an entry with structure analysis."""
    from ddo_data.dat_parser import DatArchive, read_entry_data, scan_file_table
    from ddo_data.dat_parser.tagged import scan_tagged_entry
    from ddo_data.dat_parser.utils import hex_dump

    archive = DatArchive(dat_file)
    entries = scan_file_table(archive)

    fid = _parse_hex_int(file_id)
    if fid not in entries:
        click.echo(f"File ID 0x{fid:08X} not found in archive")
        return

    entry = entries[fid]
    compressed = "yes" if entry.is_compressed else "no"
    click.echo(f"Entry 0x{fid:08X}  size={entry.size:,}  disk_size={entry.disk_size:,}  compressed={compressed}")

    try:
        data = read_entry_data(archive, entry)
    except ValueError as e:
        click.echo(f"Error reading entry: {e}")
        return

    click.echo(f"Content: {len(data):,} bytes")
    click.echo()

    # Hex dump
    click.echo(hex_dump(data, limit=limit))

    # Heuristic structure analysis
    result = scan_tagged_entry(data)
    if result.strings:
        click.echo(f"\nUTF-16LE strings found ({len(result.strings)}):")
        for off, text in result.strings[:20]:
            click.echo(f"  0x{off:04X}: {text!r}")
        if len(result.strings) > 20:
            click.echo(f"  ... and {len(result.strings) - 20} more")

    if result.file_refs:
        click.echo(f"\nFile ID references found ({len(result.file_refs)}):")
        for off, ref_id in result.file_refs[:20]:
            click.echo(f"  0x{off:04X}: 0x{ref_id:08X}")
        if len(result.file_refs) > 20:
            click.echo(f"  ... and {len(result.file_refs) - 20} more")

    # TLV hypothesis probing
    from ddo_data.dat_parser.tagged import format_tlv_result, scan_all_hypotheses

    click.echo("\n--- TLV Hypothesis Probing ---")
    for tlv_result in scan_all_hypotheses(data):
        click.echo()
        click.echo(format_tlv_result(tlv_result))


@cli.command(name="dat-survey")
@click.argument("dat_file", type=click.Path(exists=True, path_type=Path))
@click.option("--limit", "-n", type=int, default=0, help="Max entries to survey (0 = all)")
def dat_survey(dat_file: Path, limit: int) -> None:
    """Survey binary entry structure: type codes, sizes, string density."""
    from ddo_data.dat_parser import DatArchive, scan_file_table
    from ddo_data.dat_parser.survey import format_survey, survey_entries

    archive = DatArchive(dat_file)
    archive.read_header()
    click.echo(f"Scanning {dat_file.name}...")

    entries = scan_file_table(archive)
    click.echo(f"Found {len(entries):,} entries. Surveying...")

    result = survey_entries(archive, entries, limit=limit)
    click.echo()
    click.echo(format_survey(result))


@cli.command(name="dat-compare-entries")
@click.argument("dat_file", type=click.Path(exists=True, path_type=Path))
@click.option("--type", "type_code", type=str, required=True, help="First-uint32 type code in hex (e.g. 0x00000001)")
@click.option("--limit", "-n", type=int, default=50, help="Max entries to compare")
def dat_compare_entries(dat_file: Path, type_code: str, limit: int) -> None:
    """Compare entries sharing a type code to find field patterns."""
    from ddo_data.dat_parser import DatArchive, scan_file_table
    from ddo_data.dat_parser.compare import compare_entries_by_type, format_compare_result

    archive = DatArchive(dat_file)
    archive.read_header()
    click.echo(f"Scanning {dat_file.name}...")

    entries = scan_file_table(archive)
    code = _parse_hex_int(type_code)

    click.echo(f"Comparing entries with type code 0x{code:08X}...")
    result = compare_entries_by_type(archive, code, entries, limit=limit)
    click.echo()
    click.echo(format_compare_result(result))


@cli.command(name="dat-compare")
@click.argument("dat_file", type=click.Path(exists=True, path_type=Path))
def dat_compare(dat_file: Path) -> None:
    """Compare brute-force scanner vs B-tree traversal results."""
    from ddo_data.dat_parser import DatArchive, scan_file_table, traverse_btree

    archive = DatArchive(dat_file)
    archive.read_header()

    click.echo(f"Root offset: 0x{archive.header.root_offset:08X}")
    if archive.header.root_offset == 0:
        click.echo("No B-tree root offset set. Cannot compare.")
        return

    click.echo(f"Scanning {dat_file.name} with brute-force scanner...")
    bf_entries = scan_file_table(archive)
    click.echo(f"  Found {len(bf_entries):,} entries")

    click.echo(f"Walking B-tree from root 0x{archive.header.root_offset:08X}...")
    bt_entries = traverse_btree(archive)
    click.echo(f"  Found {len(bt_entries):,} entries")

    bf_ids = set(bf_entries.keys())
    bt_ids = set(bt_entries.keys())

    only_bf = bf_ids - bt_ids
    only_bt = bt_ids - bf_ids
    common = bf_ids & bt_ids

    click.echo(f"\nCommon: {len(common):,}  |  Brute-force only: {len(only_bf):,}  |  B-tree only: {len(only_bt):,}")

    # Check for offset/size mismatches in common entries
    mismatches = 0
    for fid in sorted(common):
        bf, bt = bf_entries[fid], bt_entries[fid]
        if bf.data_offset != bt.data_offset or bf.size != bt.size:
            mismatches += 1
            if mismatches <= 10:
                click.echo(
                    f"  Mismatch 0x{fid:08X}: "
                    f"bf(off=0x{bf.data_offset:08X}, size={bf.size}) vs "
                    f"bt(off=0x{bt.data_offset:08X}, size={bt.size})"
                )
    if mismatches > 10:
        click.echo(f"  ... and {mismatches - 10} more")
    elif mismatches == 0:
        click.echo("  All common entries match on offset and size.")

    if only_bf:
        click.echo("\nBrute-force only (first 10):")
        for fid in sorted(only_bf)[:10]:
            click.echo(f"  0x{fid:08X}")

    if only_bt:
        click.echo("\nB-tree only (first 10):")
        for fid in sorted(only_bt)[:10]:
            click.echo(f"  0x{fid:08X}")


@cli.command(name="dat-validate")
@click.option("--sample", "-n", type=int, default=200, help="Number of entries to sample per hypothesis")
@click.pass_context
def dat_validate(ctx: click.Context, sample: int) -> None:
    """Validate TLV hypotheses against real game data using cross-archive references."""
    from ddo_data.dat_parser.validate import run_validation

    ddo_path: Path = ctx.obj["ddo_path"]
    click.echo(run_validation(ddo_path, sample_size=sample))


@cli.command(name="dat-probe")
@click.argument("dat_file", type=click.Path(exists=True, path_type=Path))
@click.option("--id", "file_id", required=True, help="File ID in hex (e.g. 0x07001234)")
def dat_probe(dat_file: Path, file_id: str) -> None:
    """Probe a single entry's binary structure with pattern detection."""
    from ddo_data.dat_parser.archive import DatArchive
    from ddo_data.dat_parser.extract import read_entry_data, scan_file_table
    from ddo_data.dat_parser.probe import (
        decode_type2,
        decode_type4,
        format_probe_result,
        format_type2,
        format_type4,
        parse_entry_header,
        probe_entry,
    )

    fid = _parse_hex_int(file_id)
    archive = DatArchive(dat_file)
    archive.read_header()
    entries = scan_file_table(archive)

    if fid not in entries:
        click.echo(f"File ID 0x{fid:08X} not found in archive")
        return

    entry = entries[fid]
    data = read_entry_data(archive, entry)

    # Use structured decoder for known entry types, generic probe for others
    header = parse_entry_header(data)
    if header.did == 4:
        result = decode_type4(data)
        click.echo(format_type4(result))
    elif header.did == 2:
        result = decode_type2(data)
        click.echo(format_type2(result))
    else:
        result = probe_entry(data)
        click.echo(format_probe_result(result))


@cli.command(name="dat-registry")
@click.argument("dat_file", type=click.Path(exists=True, path_type=Path))
@click.option("--limit", "-n", type=int, default=0, help="Max entries to scan (0 = all)")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def dat_registry(dat_file: Path, limit: int, as_json: bool) -> None:
    """Build an empirical property key registry from decoded entries."""
    import json as json_mod

    from ddo_data.dat_parser.archive import DatArchive
    from ddo_data.dat_parser.extract import scan_file_table
    from ddo_data.dat_parser.registry import (
        build_registry,
        format_registry,
        format_registry_json,
    )

    archive = DatArchive(dat_file)
    archive.read_header()
    click.echo(f"Scanning {dat_file.name}...")

    entries = scan_file_table(archive)
    click.echo(f"Found {len(entries):,} entries. Building registry...")

    result = build_registry(archive, entries, limit=limit)

    if as_json:
        click.echo(json_mod.dumps(format_registry_json(result), indent=2))
    else:
        click.echo()
        click.echo(format_registry(result))


@cli.command(name="dat-namemap")
@click.option(
    "--wiki-items", type=click.Path(exists=True, path_type=Path),
    default=Path("public/data/items.json"),
    help="Path to wiki items JSON (from 'ddo-data scrape')",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def dat_namemap(ctx: click.Context, wiki_items: Path, as_json: bool) -> None:
    """Cross-reference wiki items with gamelogic to map property key names."""
    import json as json_mod

    from .dat_parser.namemap import (
        build_name_map,
        format_name_map,
        format_name_map_json,
    )

    ddo_path = ctx.obj["ddo_path"]
    result = build_name_map(ddo_path, wiki_items, on_progress=click.echo)

    if as_json:
        click.echo(json_mod.dumps(format_name_map_json(result), indent=2))
    else:
        click.echo()
        click.echo(format_name_map(result))


@cli.command(name="dat-effect-census")
@click.argument("dat_file", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def dat_effect_census(dat_file: Path, as_json: bool) -> None:
    """Histogram stat_def_ids and bonus_type_codes across all 0x70 effect entries."""
    import json as json_mod

    from .dat_parser.archive import DatArchive
    from .dat_parser.btree import traverse_btree
    from .dat_parser.effects import (
        build_effect_census,
        format_effect_census,
        format_effect_census_json,
    )

    archive = DatArchive(dat_file)
    archive.read_header()
    click.echo(f"Scanning {dat_file.name}...")

    entries = traverse_btree(archive)
    click.echo(f"Found {len(entries):,} entries. Building effect census...")

    result = build_effect_census(archive, entries)

    if as_json:
        click.echo(json_mod.dumps(format_effect_census_json(result), indent=2))
    else:
        click.echo()
        click.echo(format_effect_census(result))


@cli.command(name="dat-effect-map")
@click.option(
    "--wiki-items", type=click.Path(exists=True, path_type=Path),
    required=True, help="Path to wiki items JSON with enchantment strings",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option(
    "--min-confidence", type=float, default=0.95,
    help="Minimum confidence threshold for confirmed mappings (0.0-1.0)",
)
@click.pass_context
def dat_effect_map(
    ctx: click.Context, wiki_items: Path, as_json: bool, min_confidence: float,
) -> None:
    """Correlate wiki enchantment strings with binary effects to discover stat/bonus mappings."""
    import json as json_mod

    from .dat_parser.effects import (
        build_effect_map,
        format_effect_map,
        format_effect_map_json,
    )

    ddo_path: Path = ctx.obj["ddo_path"]

    with open(wiki_items) as f:
        items = json_mod.load(f)
    click.echo(f"Loaded {len(items):,} wiki items from {wiki_items}")

    result = build_effect_map(ddo_path, items, on_progress=click.echo)

    if as_json:
        click.echo(json_mod.dumps(format_effect_map_json(result, min_confidence), indent=2))
    else:
        click.echo()
        click.echo(format_effect_map(result, min_confidence))


@cli.command(name="dat-spell-survey")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def dat_spell_survey(ctx: click.Context, as_json: bool) -> None:
    """Survey all 0x47 spell entries: ref counts, slot distributions, 0x0A strings."""
    import json as json_mod

    from .dat_parser.spells_survey import (
        format_spell_survey,
        format_spell_survey_json,
        survey_spell_entries,
    )

    ddo_path: Path = ctx.obj["ddo_path"]
    result = survey_spell_entries(ddo_path, on_progress=click.echo)

    if as_json:
        click.echo(json_mod.dumps(format_spell_survey_json(result), indent=2))
    else:
        click.echo()
        click.echo(format_spell_survey(result))


@cli.command(name="dat-spell-correlate")
@click.option(
    "--wiki-spells", type=click.Path(exists=True, path_type=Path),
    required=True, help="Path to wiki spells JSON",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def dat_spell_correlate(
    ctx: click.Context, wiki_spells: Path, as_json: bool,
) -> None:
    """Cross-reference wiki spells with binary entries to discover slot semantics."""
    import json as json_mod

    from .dat_parser.spells_correlate import (
        format_correlation,
        format_correlation_json,
        run_correlation,
    )

    ddo_path: Path = ctx.obj["ddo_path"]

    with open(wiki_spells) as f:
        spells = json_mod.load(f)
    click.echo(f"Loaded {len(spells):,} wiki spells from {wiki_spells}")

    result = run_correlation(ddo_path, spells, on_progress=click.echo)

    if as_json:
        click.echo(json_mod.dumps(format_correlation_json(result), indent=2))
    else:
        click.echo()
        click.echo(format_correlation(result))


@cli.command()
@click.option(
    "--output", "-o", type=click.Path(path_type=Path),
    default=Path("public/data"), help="Output directory for JSON files",
)
@click.option(
    "--wiki-items", type=click.Path(path_type=Path),
    default=None, help="Path to wiki items.json for merge",
)
@click.option(
    "--wiki-feats", type=click.Path(path_type=Path),
    default=None, help="Path to wiki feats.json for merge",
)
@click.pass_context
def extract(
    ctx: click.Context,
    output: Path,
    wiki_items: Path | None,
    wiki_feats: Path | None,
) -> None:
    """Extract game data from .dat archives to JSON files."""
    from .game_data.feats import export_feats_json, parse_feats
    from .game_data.items import export_items_json, parse_items

    ddo_path: Path = ctx.obj["ddo_path"]

    # Default wiki merge: use existing JSON in output dir if present
    wiki_items_path = wiki_items or (output / "items.json")
    if not wiki_items_path.exists():
        wiki_items_path = None

    click.echo(f"Extracting items to {output}/")
    items = parse_items(
        ddo_path, wiki_items_path=wiki_items_path, on_progress=click.echo,
    )
    export_items_json(items, output / "items.json")
    click.echo(f"  {len(items):,} items written to {output}/items.json")

    wiki_feats_path = wiki_feats or (output / "feats.json")
    if not wiki_feats_path.exists():
        wiki_feats_path = None

    click.echo(f"Extracting feats to {output}/")
    feats = parse_feats(
        ddo_path, wiki_feats_path=wiki_feats_path, on_progress=click.echo,
    )
    export_feats_json(feats, output / "feats.json")
    click.echo(f"  {len(feats):,} feats written to {output}/feats.json")


@cli.command()
@click.argument("dat_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output", "-o", type=click.Path(path_type=Path),
    default=Path("icons"), help="Output directory for PNG icons",
)
@click.option("--limit", "-n", type=int, default=0, help="Max icons to extract (0 = all)")
def icons(dat_file: Path, output: Path, limit: int) -> None:
    """Extract DDS textures from a .dat archive and convert to PNG."""
    from ddo_data.icons import extract_icons

    click.echo(f"Extracting icons from {dat_file.name} to {output}/")
    png_paths = extract_icons(dat_file, output, limit=limit)
    click.echo(f"Extracted {len(png_paths)} icons")


@cli.command(name="dat-identify")
@click.pass_context
def dat_identify(ctx: click.Context) -> None:
    """Identify all gamelogic entries via localization cross-reference.

    Traverses the full B-tree (490K+ entries) and resolves entity names
    from the English string table using the shared 24-bit namespace.
    Reports counts by file_id high byte and entity name prefix patterns.
    """
    from .dat_parser.identify import format_identify, identify_entities

    ddo_path: Path = ctx.obj["ddo_path"]
    result = identify_entities(ddo_path, on_progress=click.echo)
    click.echo()
    click.echo(format_identify(result))


@cli.command(name="build-db")
@click.option(
    "--output", "-o", type=click.Path(path_type=Path),
    default=Path("public/data/ddo.db"), help="Output SQLite database file",
)
@click.option("--no-cache", is_flag=True, help="Ignore cached wiki responses")
@click.option(
    "--limit", "-n", type=int, default=0,
    help="Max pages to fetch per type (0 = all)",
)
@click.option(
    "--type", "data_types",
    type=click.Choice(["items", "feats", "enhancements", "sets", "augments", "spells", "filigrees", "classes"]),
    multiple=True, default=("items", "feats", "enhancements", "sets", "augments", "spells", "filigrees", "classes"),
    help="Which data types to include",
)
@click.pass_context
def build_db(
    ctx: click.Context,
    output: Path,
    no_cache: bool,
    limit: int,
    data_types: tuple[str, ...],
) -> None:
    """Build SQLite game database from DDO Wiki data."""
    from .db import GameDB
    from .wiki.client import WikiClient
    from .wiki.scraper import collect_augments, collect_classes, collect_enhancements, collect_feats, collect_filigrees, collect_items, collect_set_bonuses, collect_spells

    ddo_path: Path = ctx.obj["ddo_path"]
    client = WikiClient(use_cache=not no_cache)
    output.parent.mkdir(parents=True, exist_ok=True)

    with GameDB(output) as db:
        db.create_schema()

        for data_type in data_types:
            click.echo(f"Collecting {data_type}...")
            count = 0
            if data_type == "items":
                wiki_items_list = list(collect_items(client, limit=limit, on_progress=click.echo))
                try:
                    from .game_data.items import parse_items
                    click.echo("Parsing binary items and merging wiki data...")
                    merged = parse_items(ddo_path, wiki_items=wiki_items_list, on_progress=click.echo)
                    count = db.insert_items(merged)
                except Exception as exc:
                    click.echo(f"  Binary parse failed ({exc}), using wiki-only items")
                    count = db.insert_items(wiki_items_list)
            elif data_type == "feats":
                from .wiki.scraper import collect_race_feats
                wiki_feats = list(collect_feats(client, limit=limit, on_progress=click.echo))
                _overlay_feat_binary_data(wiki_feats, ddo_path)
                race_feats = collect_race_feats(client, on_progress=click.echo)
                count = db.insert_feats(wiki_feats, race_feats=race_feats)
            elif data_type == "enhancements":
                from .wiki.scraper import collect_epic_destinies
                wiki_trees = list(collect_enhancements(client, limit=limit, on_progress=click.echo))
                epic_trees = collect_epic_destinies(client, limit=limit, on_progress=click.echo)
                all_trees = wiki_trees + epic_trees
                _overlay_enhancement_localization(all_trees)
                count = db.insert_enhancement_trees(all_trees)
            elif data_type == "sets":
                count = db.insert_set_bonus_effects(collect_set_bonuses(client, on_progress=click.echo))
            elif data_type == "augments":
                wiki_augments = list(collect_augments(client, limit=limit, on_progress=click.echo))
                _overlay_augment_binary_data(wiki_augments, ddo_path)
                count = db.insert_augments(wiki_augments)
            elif data_type == "spells":
                wiki_spells = collect_spells(client, limit=limit, on_progress=click.echo)
                _overlay_spell_binary_data(wiki_spells, ddo_path)
                count = db.insert_spells(wiki_spells)
            elif data_type == "filigrees":
                count = db.insert_filigrees(collect_filigrees(client, on_progress=click.echo))
            elif data_type == "classes":
                class_data = collect_classes(client, on_progress=click.echo)
                count = db.insert_class_progression(class_data)
            else:
                click.echo(f"  Unknown data type: {data_type!r} — skipping")
                continue
            click.echo(f"  {count:,} {data_type} inserted")

    # Second-pass: fetch missing icons for items with wiki_url
    click.echo("Fixing missing icons...")
    with GameDB(output) as db:
        _fix_missing_item_icons(db.conn, client)

    click.echo(f"Database written to {output}")

    # Post-import validation
    with GameDB(output) as db:
        report = db.validate()
        click.echo(f"\n{report}")


@cli.command(name="validate-db")
@click.argument("db_path", type=click.Path(exists=True, path_type=Path))
def validate_db(db_path: Path) -> None:
    """Run data validation assertions against an existing database."""
    from .db import GameDB
    from .db.validate import format_validation, validate_database, validate_seed_against_wiki

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    results = validate_database(conn)
    results.extend(validate_seed_against_wiki(conn))

    click.echo(format_validation(results))

    errors = sum(1 for r in results if not r.passed and r.severity == "error")
    if errors:
        raise SystemExit(1)


def _overlay_item_binary_data(items: list[dict], ddo_path: Path) -> None:
    """Overlay binary data onto wiki item dicts (in-place).

    Matches wiki items to binary 0x79XXXXXX entries by normalized name,
    setting the ``dat_id`` field to the hex file ID (e.g., ``0x79012345``).
    Also overlays binary-extracted fields (rarity, equipment_slot, etc.)
    where the wiki dict has None.
    """
    import html

    def _norm(s: str) -> str:
        return html.unescape(s).strip().replace("_", " ").lower()

    try:
        from .game_data.items import parse_items
        binary_items = parse_items(ddo_path, on_progress=click.echo)
    except Exception as exc:
        click.echo(f"  Binary dat_id overlay skipped: {exc}")
        return

    binary_by_name: dict[str, dict] = {}
    for bi in binary_items:
        name = bi.get("name")
        dat_id = bi.get("id")
        if name and dat_id:
            norm = _norm(name)
            if norm not in binary_by_name:
                binary_by_name[norm] = bi

    matched = 0
    for item in items:
        name = item.get("name")
        if not name:
            continue
        norm = _norm(name)
        bi = binary_by_name.get(norm)
        if not bi and not norm.startswith("legendary "):
            bi = binary_by_name.get("legendary " + norm)
        if not bi and norm.startswith("legendary "):
            bi = binary_by_name.get(norm[len("legendary "):])
        if bi:
            item["dat_id"] = bi["id"]
            # Overlay binary fields where wiki has None
            for field in ("rarity", "equipment_slot", "item_category", "durability", "minimum_level"):
                if item.get(field) is None and bi.get(field) is not None:
                    item[field] = bi[field]
            matched += 1
    click.echo(f"  {matched:,} items matched with binary data")


def _overlay_feat_binary_data(feats: list[dict], ddo_path: Path) -> None:
    """Overlay binary data onto wiki feat dicts (in-place).

    Matches wiki feats to binary entries by normalized name and overlays
    dat_id plus binary-extracted fields (cooldown_seconds, duration_seconds,
    damage_dice_notation, scales_with_difficulty, tooltip, description) where
    the wiki dict has None.

    Silently skips the overlay if the DDO .dat files are unavailable or
    if binary parsing fails for any reason.
    """
    def _norm(s: str) -> str:
        return s.strip().replace("_", " ").lower()

    try:
        from .game_data.feats import parse_feats
        binary_feats = parse_feats(ddo_path, on_progress=click.echo)
    except Exception as exc:
        click.echo(f"  Binary dat_id overlay skipped: {exc}")
        return

    binary_by_name: dict[str, dict] = {}
    for bf in binary_feats:
        name = bf.get("name")
        dat_id = bf.get("dat_id")
        if name and dat_id:
            norm = _norm(name)
            if norm not in binary_by_name:
                binary_by_name[norm] = bf

    matched = 0
    for feat in feats:
        name = feat.get("name")
        if not name:
            continue
        normed = _norm(name)
        bf = binary_by_name.get(normed)
        if bf:
            feat["dat_id"] = bf["dat_id"]
            # Overlay binary fields where wiki has None
            for field in (
                "cooldown_seconds", "duration_seconds", "damage_dice_notation",
                "scales_with_difficulty", "tooltip",
            ):
                if feat.get(field) is None and bf.get(field) is not None:
                    feat[field] = bf[field]
            # Binary description → description column (different key name)
            if feat.get("description") is None and bf.get("binary_description"):
                feat["description"] = bf["binary_description"]
            # Feat type flags from binary (only set if wiki doesn't have them)
            if bf.get("is_active_binary") and not feat.get("active"):
                feat["active"] = True
            if bf.get("is_stance_binary") and not feat.get("stance"):
                feat["stance"] = True
            if bf.get("is_free_binary") and not feat.get("free"):
                feat["free"] = True
            matched += 1
    click.echo(f"  {matched:,} feats matched with binary data")


def _overlay_enhancement_localization(trees: list[dict]) -> None:
    """Overlay localization data from the FID enhancement cache.

    Loads ``fid_enhancement_lookup.json`` and matches cached FIDs to wiki
    enhancements by name+tree. Adds ``dat_id`` and ``localization_tooltips``
    fields to matched enhancement dicts.
    """
    import html
    import json
    from collections import defaultdict

    cache_path = Path(__file__).parent / "dat_parser" / "fid_enhancement_lookup.json"
    if not cache_path.exists():
        return

    with open(cache_path) as f:
        cache = json.load(f)

    if not cache:
        return

    def _norm(s: str) -> str:
        return html.unescape(s).strip().replace("_", " ").lower()

    # Index cache by (norm_name, tree) for fast lookup
    # Multiple FIDs may map to same enhancement (one per rank)
    cache_by_enh: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for fid_hex, entry in cache.items():
        key = (_norm(entry["name"]), entry["tree"])
        cache_by_enh[key].append({"fid": fid_hex, **entry})

    matched = 0
    for tree in trees:
        tname = tree.get("name", "")
        for enh in tree.get("enhancements", []):
            ename = enh.get("name", "")
            key = (_norm(ename), tname)
            cached = cache_by_enh.get(key)
            if not cached:
                continue
            # Use the FID with the longest tooltip as canonical dat_id
            best = max(cached, key=lambda c: len(c.get("tooltip", "")))
            enh["dat_id"] = best["fid"]
            # Per-rank tooltips sorted by length (shortest=rank 1, longest=max rank)
            enh["localization_tooltips"] = [
                c["tooltip"] for c in sorted(cached, key=lambda c: len(c.get("tooltip", "")))
            ]
            matched += 1

    click.echo(f"  {matched:,} enhancements matched with localization FIDs")


def _overlay_augment_binary_data(augments: list[dict], ddo_path: Path) -> None:
    """Overlay binary data onto wiki augment dicts.

    Matches wiki augments to binary 0x79 entries by name.
    Sets ``dat_id`` and overlays ``minimum_level`` from binary where wiki
    doesn't have it. Parses effect_ref localization names for bonus
    descriptions.
    """
    import re

    try:
        from .dat_parser.archive import DatArchive
        from .dat_parser.btree import traverse_btree
        from .dat_parser.extract import read_entry_data
        from .dat_parser.fid_lookups import EFFECT_FID_LOOKUP
        from .dat_parser.namemap import DISCOVERED_KEYS, decode_dup_triple
        from .dat_parser.strings import load_string_table, load_tooltip_table

        english_path = ddo_path / "client_local_English.dat"
        gamelogic_path = ddo_path / "client_gamelogic.dat"
        if not english_path.exists() or not gamelogic_path.exists():
            return

        eng = DatArchive(english_path)
        eng.read_header()
        string_table = load_string_table(eng)
        tooltip_table = load_tooltip_table(eng)

        gl = DatArchive(gamelogic_path)
        gl.read_header()
        entries = traverse_btree(gl)

    except Exception as exc:
        click.echo(f"  Augment binary overlay skipped: {exc}")
        return

    def _norm(s: str) -> str:
        return s.strip().replace("_", " ").lower()

    # Build binary name lookup for 0x79 entries
    binary_by_name: dict[str, list[tuple[int, str]]] = {}
    for fid in entries:
        if (fid >> 24) & 0xFF != 0x79:
            continue
        lower = fid & 0x00FFFFFF
        name = string_table.get(0x25000000 | lower, "")
        if name:
            norm = _norm(name)
            binary_by_name.setdefault(norm, []).append((fid, name.strip()))

    effect_ref_keys = sorted(
        k for k, v in DISCOVERED_KEYS.items() if v["name"].startswith("effect_ref")
    )
    _KEY_MIN_LEVEL = 0x10001C5D

    # Tooltip pattern: "can go in a/any [colors] Augment Slot"
    _color_pat = re.compile(
        r'(?:can go in (?:a|an|any)\s+)(.*?)\s+[Aa]ugment [Ss]lot',
        re.IGNORECASE,
    )

    # Known bonus types/stats for filtering parsed names
    _bonus_types = {
        "enhancement", "insight", "quality", "competence",
        "profane", "sacred", "luck", "morale", "artifact", "exceptional",
    }
    _pat = re.compile(r'^\+(\d+)\s+(.+?)$')

    matched = 0
    bonuses_found = 0
    for aug in augments:
        norm = _norm(aug.get("name", ""))
        candidates = binary_by_name.get(norm)
        if not candidates:
            continue

        fid = candidates[0][0]
        aug["dat_id"] = f"0x{fid:08X}"
        matched += 1

        # Read properties
        entry = entries.get(fid)
        if entry is None:
            continue
        try:
            data = read_entry_data(gl, entry)
        except (ValueError, OSError):
            continue
        if not data or len(data) < 20:
            continue

        props = decode_dup_triple(data)
        prop_dict = {p.key: p.value for p in props}

        # Overlay minimum_level from binary if wiki doesn't have it
        if aug.get("minimum_level") is None and _KEY_MIN_LEVEL in prop_dict:
            aug["minimum_level"] = prop_dict[_KEY_MIN_LEVEL]

        # Parse slot_color from tooltip if wiki doesn't have it
        if not aug.get("slot_color"):
            lower = fid & 0x00FFFFFF
            tip = str(tooltip_table.get(0x25000000 | lower, ""))
            m = _color_pat.search(tip)
            if m:
                color_text = m.group(1).strip().lower()
                if "any color" in color_text or color_text == "color":
                    aug["slot_color"] = "colorless"
                else:
                    # Take first color: "Blue, Green, or Purple" -> "blue"
                    first = re.split(r',\s*|\s+or\s+', color_text)[0].strip()
                    if first:
                        aug["slot_color"] = first

        # Parse effect_ref localization names for bonus descriptions
        binary_bonuses = []
        for k in effect_ref_keys:
            ref_val = prop_dict.get(k)
            if ref_val is None:
                continue
            if (ref_val >> 24) & 0xFF != 0x70:
                continue

            # Check FID lookup first
            fid_result = EFFECT_FID_LOOKUP.get(ref_val)
            if fid_result:
                stat, bt = fid_result
                binary_bonuses.append({
                    "stat": stat, "bonus_type": bt,
                    "_resolution_method": "fid_lookup",
                })
                continue

            # Try localization name parsing
            lower = ref_val & 0x00FFFFFF
            eff_name = string_table.get(0x25000000 | lower, "")
            if not eff_name or len(eff_name) > 80:
                continue
            m = _pat.match(eff_name.strip())
            if not m:
                continue
            value = int(m.group(1))
            rest = m.group(2).strip()
            if value < 1 or value > 200:
                continue
            bonus_type = None
            stat_name = rest
            for bt in sorted(_bonus_types, key=len, reverse=True):
                if rest.lower().startswith(bt + " "):
                    bonus_type = bt.title()
                    stat_name = rest[len(bt) + 1:]
                    break
            binary_bonuses.append({
                "stat": stat_name, "bonus_type": bonus_type,
                "value": value, "_description": eff_name.strip(),
                "_resolution_method": "binary_name",
            })

        if binary_bonuses:
            aug["_binary_bonuses"] = binary_bonuses
            bonuses_found += 1

    click.echo(f"  {matched:,} augments matched with binary ({bonuses_found} with bonus data)")


def _fix_missing_item_icons(
    conn: "sqlite3.Connection",
    client: "WikiClient",
) -> None:
    """Second-pass: fetch icons for items that have wiki_url but no icon."""
    import sqlite3
    from urllib.parse import unquote

    from .wiki.parsers import _extract_icon, extract_template

    missing = conn.execute(
        "SELECT id, name, wiki_url FROM items "
        "WHERE (icon IS NULL OR icon = '') AND wiki_url IS NOT NULL"
    ).fetchall()
    if not missing:
        return

    fixed = 0
    for item_id, name, wiki_url in missing:
        page_title = wiki_url.split("/page/")[-1] if "/page/" in wiki_url else name
        page_title = unquote(page_title)

        wt = client.get_wikitext(page_title)
        if not wt:
            if page_title.startswith("Item:"):
                wt = client.get_wikitext(page_title[5:])
            if not wt:
                continue

        fields = extract_template(wt, "Named item")
        if not fields:
            continue

        for fn in ("picdesc", "pic", "icon"):
            raw = fields.get(fn, "")
            if raw.strip():
                icon = _extract_icon(raw)
                if icon:
                    conn.execute("UPDATE items SET icon = ? WHERE id = ?", (icon, item_id))
                    fixed += 1
                    break

    conn.commit()
    if fixed:
        import logging
        logging.getLogger(__name__).info("Fixed %d missing item icons", fixed)


def _overlay_spell_binary_data(spells: list[dict], ddo_path: Path) -> None:
    """Overlay binary spell data from 0x47 entries onto wiki spell dicts.

    Matches by name, then overlays SP cost from stat 553/554,
    damage_scaling from stat 946, and school from ref slot hash lookup.
    School hash discovered via correlation: slot 15 for DID 0x028B (89%),
    slot 16 for DID 0x008B (91%).
    """
    import struct

    def _norm(s: str) -> str:
        return s.strip().replace("_", " ").lower()

    try:
        from .dat_parser.archive import DatArchive
        from .dat_parser.btree import traverse_btree
        from .dat_parser.extract import read_entry_data
        from .dat_parser.probe import parse_entry_header
        from .dat_parser.strings import load_string_table, load_tooltip_table

        english_path = ddo_path / "client_local_English.dat"
        gamelogic_path = ddo_path / "client_gamelogic.dat"
        if not english_path.exists() or not gamelogic_path.exists():
            return

        # School hash lookup: maps ref slot values to spell school names.
        # DID 0x028B uses slot 15 (89.3%), DID 0x008B uses slot 16 (90.9%).
        # Discovered via dat-spell-correlate with 480 wiki spells, 178 matched.
        school_hash: dict[int, str] = {
            0x00000002: "Enchantment", 0x00000004: "Abjuration",
            0x00000005: "Necromancy", 0x0000000A: "Evocation",
            0x000002D4: "Conjuration", 0x0000037F: "Transmutation",
            0x000003B5: "Evocation", 0x00010000: "Conjuration",
            0x00011000: "Evocation", 0x0002C401: "Necromancy",
            0x0002DB10: "Necromancy", 0x0009A210: "Transmutation",
            0x00100000: "Transmutation", 0x0010000C: "Necromancy",
            0x003F004A: "Transmutation", 0x003FB4B3: "Evocation",
            0x00400000: "Enchantment", 0x00404000: "Illusion",
            0x004061F0: "Abjuration", 0x00409FFF: "Evocation",
            0x00412000: "Transmutation", 0x00417000: "Evocation",
            0x0042C800: "Necromancy", 0x020C0000: "Evocation",
            0x023F1941: "Enchantment", 0x02C40000: "Evocation",
            0x06000003: "Necromancy", 0x0640A000: "Transmutation",
            0x08000003: "Evocation", 0x0A40C000: "Abjuration",
            0x0E000003: "Abjuration", 0x0E010000: "Evocation",
            0x100016CF: "Transmutation", 0x10001898: "Enchantment",
            0x10001BD6: "Transmutation", 0x10780000: "Abjuration",
            0x13000002: "Evocation", 0x13100000: "Abjuration",
            0x1A030000: "Evocation", 0x1C410B30: "Abjuration",
            0x1F412067: "Conjuration", 0x2610001B: "Abjuration",
            0x2E257000: "Transmutation", 0x2E4028B5: "Conjuration",
            0x31000000: "Abjuration", 0x3310001B: "Evocation",
            0x343F8ABC: "Conjuration", 0x3D3FCF11: "Transmutation",
            0x3D40E8D9: "Illusion", 0x3F666666: "Abjuration",
            0x44410E59: "Conjuration", 0x453FE2BE: "Abjuration",
            0x47404318: "Enchantment", 0x48403790: "Conjuration",
            0x4840A224: "Divination", 0x513F145A: "Transmutation",
            0x514177D2: "Enchantment", 0x57407CCA: "Conjuration",
            0x59100004: "Necromancy", 0x5B3FE23E: "Enchantment",
            0x5C402341: "Transmutation", 0x5C4044F5: "Illusion",
            0x74000007: "Abjuration", 0x763FAB85: "Enchantment",
            0x78000016: "Abjuration", 0x7800030E: "Transmutation",
            0x7D40E346: "Abjuration", 0x80B523D7: "Enchantment",
            0x8E10001B: "Enchantment", 0x94402215: "Conjuration",
            0x9A41091E: "Divination", 0x9B000003: "Necromancy",
            0x9D40F000: "Conjuration", 0xA43E02C9: "Transmutation",
            0xB6200000: "Conjuration", 0xB6200010: "Necromancy",
            0xB640A225: "Transmutation", 0xB9000000: "Enchantment",
            0xBB3F5798: "Abjuration", 0xC03F6D79: "Conjuration",
            0xC4000002: "Necromancy", 0xC8000003: "Illusion",
            0xCA40AFE5: "Abjuration", 0xD33FC364: "Enchantment",
            0xD640C000: "Transmutation", 0xD941A116: "Conjuration",
            0xE93FFE4E: "Necromancy", 0xE9408000: "Conjuration",
            0xEC3EC8B0: "Abjuration", 0xF03FA5C2: "Conjuration",
            0xF241108B: "Necromancy", 0xF63F97AF: "Transmutation",
            0xF910001B: "Divination", 0xFA401A20: "Necromancy",
            0xFC3F7F39: "Enchantment", 0xFD400647: "Abjuration",
            0xFF410F41: "Necromancy", 0xFF920000: "Transmutation",
        }

        click.echo("  Loading binary spell data from 0x47 entries...")
        eng = DatArchive(english_path)
        eng.read_header()
        strings = load_string_table(eng)
        tooltips = load_tooltip_table(eng)

        gl = DatArchive(gamelogic_path)
        gl.read_header()
        entries = traverse_btree(gl)

        # Extract spell stats from 0x47 entries
        binary_spells: dict[str, dict] = {}  # normed_name -> {stats}
        for fid in entries:
            if (fid >> 24) & 0xFF != 0x47:
                continue
            lower = fid & 0x00FFFFFF
            name = strings.get(0x25000000 | lower)
            if not name:
                continue

            try:
                data = read_entry_data(gl, entries[fid])
            except (ValueError, OSError):
                continue

            header = parse_entry_header(data)
            if header.ref_count < 3:
                continue

            # Scan ref list for stat dup-triples and school hash
            refs = header.file_ids
            spell_data: dict = {"dat_id": f"0x{fid:08X}"}

            # School from ref slot hash (slot 15 for DID 0x028B, slot 16 for 0x008B)
            school_slot = 15 if header.did == 0x028B else 16 if header.did == 0x008B else None
            if school_slot is not None and school_slot < len(refs):
                school = school_hash.get(refs[school_slot])
                if school:
                    spell_data["school_binary"] = school

            # Tooltip
            tooltip = tooltips.get(0x25000000 | lower)
            if tooltip:
                spell_data["tooltip"] = tooltip

            def _scan_dup_triples(u32_seq: list[int]) -> None:
                """Scan a sequence of u32 values for stat dup-triples."""
                j = 0
                while j + 2 < len(u32_seq):
                    r1 = u32_seq[j]
                    r2 = u32_seq[j + 1]
                    if r1 == r2 and 0 < r1 < 2000:
                        val_raw = u32_seq[j + 2]
                        fval = struct.unpack("<f", struct.pack("<I", val_raw))[0]
                        if fval == fval:  # Not NaN
                            if r1 == 553 and fval < 0:
                                spell_data["sp_cost_binary"] = round(abs(fval))
                            elif r1 == 554 and fval > 0:
                                spell_data["sp_cost_binary"] = round(fval)
                            elif r1 == 946 and fval > 0:
                                spell_data["damage_scaling"] = round(fval, 4)
                            elif r1 == 731 and 0 < val_raw < 100:
                                spell_data["tick_count"] = val_raw
                        j += 3
                    else:
                        j += 1

            # Scan ref list for stat dup-triples
            _scan_dup_triples(refs)

            # Scan body for additional dup-triples (overflow from ref list)
            body = data[header.body_offset:]
            if len(body) >= 12:
                body_u32s = [
                    struct.unpack_from("<I", body, off)[0]
                    for off in range(0, len(body) - 3, 4)
                ]
                _scan_dup_triples(body_u32s)

            normed = _norm(name)
            if normed not in binary_spells:
                binary_spells[normed] = spell_data

        click.echo(f"  {len(binary_spells):,} named 0x47 entries loaded")

        # Match and overlay
        matched = 0
        for spell in spells:
            name = spell.get("name")
            if not name:
                continue
            normed = _norm(name)
            binary = binary_spells.get(normed)
            if not binary:
                continue
            matched += 1
            # Overlay binary fields where wiki is missing
            for key in ("dat_id", "tooltip", "damage_scaling", "tick_count"):
                if binary.get(key) and not spell.get(key):
                    spell[key] = binary[key]
            # SP cost: prefer binary if wiki is missing or zero
            if binary.get("sp_cost_binary") and not spell.get("spell_points"):
                spell["spell_points"] = binary["sp_cost_binary"]
            # Cooldown: set from binary
            if binary.get("cooldown_seconds"):
                spell["cooldown_seconds"] = binary["cooldown_seconds"]
            # School: overlay binary school where wiki is missing
            if binary.get("school_binary") and not spell.get("school"):
                spell["school"] = binary["school_binary"]

        click.echo(f"  {matched:,} wiki spells matched with binary data")

    except Exception as exc:
        click.echo(f"  Binary spell overlay skipped: {exc}")


if __name__ == "__main__":
    cli()
