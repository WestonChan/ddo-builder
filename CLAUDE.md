# DDO Build Planner

A full build planner for Dungeons & Dragons Online (DDO) — character builds and gear planning.

## Quick Reference

```bash
# Frontend
npm run dev          # Dev server at http://localhost:5173/ddo-builder/
npm run build        # Production build
npm run lint         # ESLint
npm run format       # Prettier

# Python data pipeline
cd scripts
pip install -e ".[dev]"  # Install with dev deps (or: uv pip install -e ".[dev]")
ddo-data --help          # CLI commands
ddo-data info            # Show DDO install info and .dat files
ddo-data parse <file>    # Parse a .dat archive header
pytest                   # Run Python tests
```

## Project Structure

- **Feature-based frontend** — components, hooks, and types are grouped by feature under `src/features/`, not by type
  - `src/features/character/` — character builder (class, race, feats, enhancements)
  - `src/features/gear/` — gear planner (items, augments, sets)
  - `src/features/shared/` — reusable components
- **App shell** — `src/app/` contains the root App, router, and layout
- **Python data pipeline** — `scripts/` is a standalone Python package (`ddo-data`)
  - `scripts/src/ddo_data/dat_parser/` — Turbine .dat archive parser (binary format)
  - `scripts/src/ddo_data/game_data/` — parsers for items, feats, enhancements, classes, races
  - `scripts/src/ddo_data/icons/` — DDS texture extraction and PNG conversion
  - `scripts/src/ddo_data/wiki/` — DDO Wiki scraper (supplementary data)
  - `scripts/tests/` — pytest tests

## DDO Game Files

DDO is installed via CrossOver/Steam at:
```
~/Library/Application Support/CrossOver/Bottles/Steam/drive_c/Program Files (x86)/Steam/steamapps/common/Dungeons and Dragons Online/
```

Key `.dat` files:
- `client_gamelogic.dat` (498 MB) — item defs, feat data, enhancement trees, game rules
- `client_local_English.dat` (214 MB) — English text strings, names, descriptions
- `client_general.dat` (438 MB) — UI icons, item icons, feat icons

The `.dat` files use Turbine's proprietary archive format (shared with LOTRO). Reference: [DATUnpacker](https://github.com/Middle-earth-Revenge/DATUnpacker) (C#/.NET source).

## Conventions

- **Frontend:** React + TypeScript + Vite. Use feature-based organization. Router basename is `/ddo-builder` (for GitHub Pages).
- **Styling:** Dark theme with gold (#c9a848) accents. CSS modules or plain CSS in component directories.
- **Python:** Package lives in `scripts/` with `pyproject.toml`. Use `click` for CLI commands. Type hints required.
- **Data flow:** Python scripts extract game data → JSON files in `src/data/` → React app reads them at runtime.
- **Hosting:** GitHub Pages (static only). Auto-deployed via GitHub Actions on push to `main`.
