"""CLI entry point for DDO data pipeline."""

import click
from pathlib import Path

DEFAULT_DDO_PATH = Path.home() / "Library/Application Support/CrossOver/Bottles/Steam/drive_c/Program Files (x86)/Steam/steamapps/common/Dungeons and Dragons Online"


@click.group()
@click.option(
    "--dat-path",
    type=click.Path(exists=True, path_type=Path),
    default=DEFAULT_DDO_PATH,
    help="Path to DDO installation directory",
)
@click.pass_context
def cli(ctx: click.Context, dat_path: Path) -> None:
    """DDO Data Pipeline - Extract and process game data."""
    ctx.ensure_object(dict)
    ctx.obj["dat_path"] = dat_path


@cli.command()
@click.pass_context
def info(ctx: click.Context) -> None:
    """Show information about the DDO installation."""
    dat_path: Path = ctx.obj["dat_path"]
    click.echo(f"DDO Install Path: {dat_path}")

    if not dat_path.exists():
        click.echo("WARNING: DDO installation not found at this path!")
        return

    dat_files = sorted(dat_path.glob("*.dat"))
    click.echo(f"\nFound {len(dat_files)} .dat files:")
    for f in dat_files:
        size_mb = f.stat().st_size / (1024 * 1024)
        click.echo(f"  {f.name:40s} {size_mb:>8.1f} MB")


@cli.command()
@click.argument("dat_file")
@click.pass_context
def parse(ctx: click.Context, dat_file: str) -> None:
    """Parse a .dat archive file and show its header info."""
    dat_path: Path = ctx.obj["dat_path"]
    file_path = dat_path / dat_file

    if not file_path.exists():
        click.echo(f"File not found: {file_path}")
        return

    from ddo_data.dat_parser.archive import DatArchive

    archive = DatArchive(file_path)
    archive.read_header()
    click.echo(archive.header_info())


@cli.command()
@click.option("--output", "-o", type=click.Path(path_type=Path), default=Path("src/data"), help="Output directory for JSON files")
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
@click.option("--output", "-o", type=click.Path(path_type=Path), default=Path("src/data"), help="Output directory for scraped data")
@click.pass_context
def scrape(ctx: click.Context, output: Path) -> None:
    """Scrape supplementary data from DDO Wiki."""
    click.echo(f"Scraping DDO Wiki data to {output}/")
    click.echo("(Not yet implemented)")


if __name__ == "__main__":
    cli()
