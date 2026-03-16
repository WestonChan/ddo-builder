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
    from ddo_data.dat_parser.tagged import hex_dump

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
    from ddo_data.dat_parser.tagged import hex_dump, scan_tagged_entry

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


@cli.command()
@click.option(
    "--output", "-o", type=click.Path(path_type=Path),
    default=Path("public/data"), help="Output directory for JSON files",
)
@click.pass_context
def extract(ctx: click.Context, output: Path) -> None:
    """Extract game data to JSON files."""
    click.echo(f"Extracting game data to {output}/")
    click.echo("(Not yet implemented)")


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


@cli.command()
@click.option(
    "--output", "-o", type=click.Path(path_type=Path),
    default=Path("public/data"), help="Output directory for scraped data",
)
@click.pass_context
def scrape(ctx: click.Context, output: Path) -> None:
    """Scrape supplementary data from DDO Wiki."""
    click.echo(f"Scraping DDO Wiki data to {output}/")
    click.echo("(Not yet implemented)")


if __name__ == "__main__":
    cli()
