"""Read Turbine .dat archive structure (header, file table)."""

import struct
from pathlib import Path
from dataclasses import dataclass


@dataclass
class DatHeader:
    """Header information from a Turbine .dat archive."""
    file_size: int
    version: int
    file_count: int
    # These will be populated as we reverse-engineer more of the format
    raw_header: bytes


class DatArchive:
    """Parser for Turbine .dat archive files used by DDO and LOTRO."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.header: DatHeader | None = None

    def read_header(self) -> DatHeader:
        """Read and parse the .dat file header."""
        with open(self.path, "rb") as f:
            raw = f.read(1024)  # Read first 1KB for header analysis

        file_size = self.path.stat().st_size

        # Turbine .dat header format (based on DATUnpacker source):
        # The exact offsets will need to be verified against actual files.
        # Initial read to capture raw bytes for analysis.
        version = struct.unpack_from("<I", raw, 0x140)[0] if len(raw) > 0x144 else 0
        file_count = struct.unpack_from("<I", raw, 0x148)[0] if len(raw) > 0x14C else 0

        self.header = DatHeader(
            file_size=file_size,
            version=version,
            file_count=file_count,
            raw_header=raw,
        )
        return self.header

    def header_info(self) -> str:
        """Return a human-readable summary of the header."""
        if self.header is None:
            return "Header not read yet. Call read_header() first."

        size_mb = self.header.file_size / (1024 * 1024)
        lines = [
            f"File: {self.path.name}",
            f"Size: {size_mb:.1f} MB",
            f"Version: {self.header.version}",
            f"File count: {self.header.file_count}",
            "",
            "Note: Header offsets are preliminary and need verification",
            "against the DATUnpacker C# source code.",
        ]
        return "\n".join(lines)
