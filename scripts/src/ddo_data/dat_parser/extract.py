"""Extract specific files from Turbine .dat archives."""

from pathlib import Path
from .archive import DatArchive


def extract_by_type(archive: DatArchive, file_type: str, output_dir: Path) -> list[Path]:
    """Extract all files of a given type from the archive.

    Args:
        archive: Opened DatArchive instance
        file_type: File extension to extract (e.g., 'dds', 'xml')
        output_dir: Directory to write extracted files

    Returns:
        List of paths to extracted files
    """
    # Placeholder - will implement once header parsing is verified
    output_dir.mkdir(parents=True, exist_ok=True)
    return []
