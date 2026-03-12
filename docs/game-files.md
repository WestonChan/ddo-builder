# DDO Game Files

DDO is installed via CrossOver/Steam at:
```
~/Library/Application Support/CrossOver/Bottles/Steam/drive_c/Program Files (x86)/Steam/steamapps/common/Dungeons and Dragons Online/
```

Configure this path by setting `DDO_PATH` in `.env` (see `.env.example`), or pass `--dat-path` to the CLI.

## Key `.dat` Files

- `client_gamelogic.dat` (498 MB) — item defs, feat data, enhancement trees, game rules
- `client_local_English.dat` (214 MB) — English text strings, names, descriptions
- `client_general.dat` (438 MB) — UI icons, item icons, feat icons

## Archive Format

The `.dat` files use Turbine's proprietary archive format (shared with LOTRO). Reference: [DATUnpacker](https://github.com/Middle-earth-Revenge/DATUnpacker) (C#/.NET source).
