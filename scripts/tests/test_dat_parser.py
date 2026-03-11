"""Tests for the Turbine .dat archive parser."""

import pytest
from pathlib import Path
from ddo_data.dat_parser.archive import DatArchive


def test_dat_archive_init(tmp_path: Path) -> None:
    """Test DatArchive can be initialized with a path."""
    dummy = tmp_path / "test.dat"
    dummy.write_bytes(b"\x00" * 1024)
    archive = DatArchive(dummy)
    assert archive.path == dummy
    assert archive.header is None


def test_dat_archive_read_header(tmp_path: Path) -> None:
    """Test reading header from a dummy .dat file."""
    dummy = tmp_path / "test.dat"
    dummy.write_bytes(b"\x00" * 1024)
    archive = DatArchive(dummy)
    header = archive.read_header()
    assert header.file_size == 1024


@pytest.mark.skipif(
    not (Path.home() / "Library/Application Support/CrossOver/Bottles/Steam/drive_c/Program Files (x86)/Steam/steamapps/common/Dungeons and Dragons Online/client_gamelogic.dat").exists(),
    reason="DDO not installed"
)
def test_real_dat_header() -> None:
    """Test reading header from actual DDO .dat file (skipped if not installed)."""
    dat_path = Path.home() / "Library/Application Support/CrossOver/Bottles/Steam/drive_c/Program Files (x86)/Steam/steamapps/common/Dungeons and Dragons Online/client_gamelogic.dat"
    archive = DatArchive(dat_path)
    header = archive.read_header()
    assert header.file_size > 0
    assert header.file_count >= 0
