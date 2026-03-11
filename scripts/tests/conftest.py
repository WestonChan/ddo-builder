"""Shared test fixtures for DDO data pipeline tests."""

import pytest
from pathlib import Path


@pytest.fixture
def ddo_install_path() -> Path:
    """Path to DDO installation (may not exist in CI)."""
    return Path.home() / "Library/Application Support/CrossOver/Bottles/Steam/drive_c/Program Files (x86)/Steam/steamapps/common/Dungeons and Dragons Online"


@pytest.fixture
def sample_dat_header() -> bytes:
    """Minimal sample bytes mimicking a .dat file header for testing."""
    # 1KB of zeros with some placeholder values
    data = bytearray(1024)
    return bytes(data)
