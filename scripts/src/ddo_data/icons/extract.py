"""Extract DDS textures from .dat archives and convert to PNG."""

from pathlib import Path


def extract_icons(dat_path: Path, output_dir: Path) -> list[Path]:
    """Extract icon textures and convert DDS to PNG.

    Uses Pillow for DDS format support.
    Will be implemented once .dat extraction is working.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    return []
