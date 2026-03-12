# DDO Build Planner

A full build planner for [Dungeons & Dragons Online](https://www.ddo.com/) — plan character builds and gear sets.

**Live site:** [westonchan.github.io/ddo-builder](https://westonchan.github.io/ddo-builder/)

## Features (Planned)

- Character builder: race, class splits, feats, enhancements
- Gear planner: items, augments, set bonuses
- Shareable builds via URL
- Data extracted directly from DDO game files

## Tech Stack

- **Frontend:** React + TypeScript + Vite
- **Hosting:** GitHub Pages
- **Data Pipeline:** Python scripts for parsing DDO game files and scraping DDO Wiki

## Configuration

Copy `.env.example` to `.env` and set your DDO installation path:

```bash
cp .env.example .env
```

Edit `.env` to match your system. The default assumes a CrossOver/Steam install on macOS.

## Getting Started

### Frontend

```bash
npm install
npm run dev
```

### Data Pipeline

```bash
cd scripts
pip install -e ".[dev]"
ddo-data --help
ddo-data info
```

### Available Commands

| Command | Description |
|---|---|
| `npm run dev` | Start local dev server |
| `npm run build` | Production build |
| `npm run lint` | Run ESLint |
| `npm run format` | Format code with Prettier |
| `ddo-data info` | Show DDO installation info |
| `ddo-data parse <file>` | Parse a .dat archive header |

## License

MIT
