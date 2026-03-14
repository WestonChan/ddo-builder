"""CLI entry point for DDO data pipeline."""

import os

import click
from dotenv import load_dotenv
from pathlib import Path

# Load .env from project root (two levels up from scripts/src/ddo_data/)
load_dotenv(Path(__file__).resolve().parents[4] / ".env")

_FALLBACK_DDO_PATH = Path.home() / "Library/Application Support/CrossOver/Bottles/Steam/drive_c/Program Files (x86)/Steam/steamapps/common/Dungeons and Dragons Online"
DEFAULT_DDO_PATH = Path(os.environ["DDO_PATH"]) if "DDO_PATH" in os.environ else _FALLBACK_DDO_PATH


def get_dat_files(ddo_path: Path) -> list[Path]:
    """Return sorted list of DDO client .dat archive files in the given directory."""
    return sorted(p for p in ddo_path.glob("client_*.dat"))


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
@click.option("--output", "-o", type=click.Path(path_type=Path), default=Path("/tmp/ddo-extract"), help="Output directory")
def dat_extract(dat_file: Path, file_id: str | None, output: Path) -> None:
    """Extract raw files from a .dat archive."""
    from ddo_data.dat_parser import DatArchive, scan_file_table, extract_entry

    archive = DatArchive(dat_file)
    archive.read_header()
    click.echo(f"Scanning {dat_file.name}...")

    entries = scan_file_table(archive)
    click.echo(f"Found {len(entries):,} entries")

    if file_id is not None:
        fid = int(file_id, 16) if file_id.startswith("0x") else int(file_id)
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


@cli.command()
@click.option("--output", "-o", type=click.Path(path_type=Path), default=Path("public/data"), help="Output directory for JSON files")
@click.pass_context
def extract(ctx: click.Context, output: Path) -> None:
    """Extract game data to JSON files."""
    click.echo(f"Extracting game data to {output}/")
    click.echo("(Not yet implemented)")


@cli.command()
@click.option("--output", "-o", type=click.Path(path_type=Path), default=Path("public/images"), help="Output directory for icons")
@click.pass_context
def icons(ctx: click.Context, output: Path) -> None:
    """Extract and convert item/feat icons from game files."""
    click.echo(f"Extracting icons to {output}/")
    click.echo("(Not yet implemented)")


@cli.command()
@click.option("--output", "-o", type=click.Path(path_type=Path), default=Path("public/data"), help="Output directory for scraped data")
@click.pass_context
def scrape(ctx: click.Context, output: Path) -> None:
    """Scrape supplementary data from DDO Wiki."""
    click.echo(f"Scraping DDO Wiki data to {output}/")
    click.echo("(Not yet implemented)")


if __name__ == "__main__":
    cli()
