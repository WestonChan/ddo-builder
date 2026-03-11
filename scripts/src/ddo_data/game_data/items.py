"""Parse DDO item definitions from extracted game data."""

from pathlib import Path


def parse_items(data_dir: Path) -> list[dict]:
    """Parse item definitions and return as list of dicts.

    Will be implemented once we can extract XML/data from .dat files.
    """
    return []


def export_items_json(items: list[dict], output: Path) -> None:
    """Export parsed items to a JSON file."""
    import json
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        json.dump(items, f, indent=2)
