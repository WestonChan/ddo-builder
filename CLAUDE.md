# DDO Build Planner

A full build planner for Dungeons & Dragons Online (DDO) — character builds and gear planning.

## Quick Reference

```bash
# Frontend
npm run dev          # Dev server at http://localhost:5173/ddo-builder/
npm run build        # Production build
npm run lint         # ESLint
npm run format       # Prettier

# Python data pipeline (run from scripts/)
pip install -e "scripts/.[dev]"  # Install with dev deps (or: uv pip install -e "scripts/.[dev]")
ddo-data --help                  # CLI commands
ddo-data info                    # Show DDO install info and .dat files
ddo-data parse <file>            # Parse a .dat archive header
pytest scripts/                  # Run Python tests
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

## Conventions

- **Frontend:** React + TypeScript + Vite. Use feature-based organization. Router basename is `/ddo-builder` (for GitHub Pages).
- **Styling:** Dark theme with gold (#c9a848) accents. CSS modules or plain CSS in component directories.
- **Python:** Package lives in `scripts/` with `pyproject.toml`. Use `click` for CLI commands. Type hints required.
- **Data flow:** Python scripts extract game data → JSON files in `public/data/` → React app reads them at runtime.
- **Hosting:** GitHub Pages (static only). Auto-deployed via GitHub Actions on push to `main`.

## Reference Docs

- `docs/ddowiki-api.md` — How to look up DDO game info from ddowiki.com via WebFetch
- `docs/game-files.md` — DDO installation path, `.dat` file details, and archive format
