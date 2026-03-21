"""UTF-16LE string table loader for client_local_English.dat.

Entries in the English localization archive contain UTF-16LE encoded
text strings used for item names, descriptions, and other game text.

Localization entries use a structured format:
  [DID:u32] [ref_count:u8] [file_ids:u32[]] [sub_count:u8]
  then for each sub-entry:
    [ref:u32] [zero:u32] [type:u32] [strlen:VLE] [utf16le text] [5 zero bytes]

Known sub-entry ref values (property definition IDs):
  0x0DA44875 = Name (item/object name) — 116K entries
  0x033D632E = Description (short label, often just the name repeated; sometimes
               dev notes like "Broken" or "Zzzz...") — 78K entries
  0x05E535B5 = PluralName (variant form) — 19K entries
  0x06E399D7 = CraftingResult (recipe success text: "Item Augmented!") — 16K entries
  0x0B609513 = Tooltip (in-game effect description with numeric details) — 13K entries
  0x0A4B0FF5 = ActionText (UI action labels: "Opening lock...", "Healing...") — 4K entries
  0x0478F2A8 = EnchantName (enchantment display names: "Flaming", "Shock") — 2K entries
  0x0ABD46E3 = CraftingMessage (crafting status: "Successfully dissolved!") — 2K entries
  0x080D9E15 = DeedTitle (deed/achievement titles) — 1.5K entries
  0x09C0C57E = DeedDescription (deed objective text) — 1.5K entries
  0x04AB82A8 = EnchantSuffix (item name suffixes: "of Power VII") — 1.4K entries
  0x045EB8B1 = QuestObjective (quest text with <rgb> markup) — 1.3K entries
  0x0F0EFF4E = Summary (condensed one-line description) — 918 entries

UTF-16LE string format informed by LocalDataExtractor (Middle-earth-Revenge).
"""

import struct

from .archive import DatArchive, FileEntry
from .btree import traverse_btree
from .extract import read_entry_data, scan_file_table

# Localization sub-entry ref constants (property definition IDs)
_REF_NAME = 0x0DA44875
_REF_DESC = 0x033D632E
_REF_PLURAL = 0x05E535B5
_REF_CRAFTING_RESULT = 0x06E399D7
_REF_TOOLTIP = 0x0B609513
_REF_ACTION_TEXT = 0x0A4B0FF5
_REF_ENCHANT_NAME = 0x0478F2A8
_REF_CRAFTING_MSG = 0x0ABD46E3
_REF_DEED_TITLE = 0x080D9E15
_REF_DEED_DESC = 0x09C0C57E
_REF_ENCHANT_SUFFIX = 0x04AB82A8
_REF_QUEST_OBJECTIVE = 0x045EB8B1
_REF_SUMMARY = 0x0F0EFF4E


def load_string_table(
    archive: DatArchive,
    entries: dict[int, FileEntry] | None = None,
    limit: int = 0,
) -> dict[int, str]:
    """Extract UTF-16LE text strings from archive entries.

    Uses the B-tree directory to enumerate entries (the brute-force
    scanner misses >98% of entries in version 0x400 archives).

    Tries structured localization format first, falls back to raw
    UTF-16LE decoding for backward compatibility with synthetic test data.

    Args:
        archive: An opened DatArchive (header read automatically if needed).
        entries: Pre-scanned file entries (uses B-tree if None).
        limit: Max entries to process (0 = all).

    Returns:
        Dict mapping file_id -> decoded text string.
    """
    if entries is None:
        if archive.header is None:
            archive.read_header()
        entries = traverse_btree(archive)
        # Fall back to brute-force if B-tree is empty (e.g. synthetic test data)
        if not entries:
            entries = scan_file_table(archive)

    strings: dict[int, str] = {}
    count = 0

    for file_id in sorted(entries.keys()):
        if 0 < limit <= count:
            break

        entry = entries[file_id]
        try:
            data = read_entry_data(archive, entry)
        except (ValueError, OSError):
            continue

        # Try structured localization format first
        text = decode_localization_entry(data)
        if text is None:
            # Fall back to raw UTF-16LE (for synthetic test data / BOM entries)
            text = decode_utf16le(data)
        if text is not None:
            strings[file_id] = text

        count += 1

    return strings


def decode_localization_entry(data: bytes, file_id: int = 0) -> str | None:
    """Extract the name string from a structured localization entry.

    Parses the entry header (DID + refs) and body sub-entries to find
    the "Name" string (ref 0x0DA44875). Falls back to the first valid
    string if the Name ref isn't present.

    The data may or may not start with the DID depending on the archive
    version: 0x200 (gamelogic) includes DID, 0x400 (English) strips it.
    When the DID is absent, ``file_id`` is used for validation.

    Returns None if the entry has no decodable strings.
    """
    if len(data) < 14:
        return None

    # Check if data starts with a 0x25 DID (version 0x200 format).
    # If not, the DID was stripped by read_entry_data (version 0x400 format)
    # and the data starts directly with ref_count.
    did = struct.unpack_from("<I", data, 0)[0]
    if (did >> 24) & 0xFF == 0x25:
        # Version 0x200: DID is at the start
        ref_count = data[4]
        body_offset = 5 + ref_count * 4
    else:
        # Version 0x400: DID stripped; data starts with ref_count
        ref_count = data[0]
        body_offset = 1 + ref_count * 4

    if body_offset + 14 > len(data):
        return None

    body = data[body_offset:]
    sub_count = body[0]

    if sub_count < 1 or sub_count > 10:
        return None

    # Parse sub-entries looking for the Name ref
    first_string = None
    offset = 1  # past sub_count

    for _ in range(sub_count):
        if offset + 13 > len(body):
            break

        ref = struct.unpack_from("<I", body, offset)[0]

        # VLE decode for string length at offset + 12
        strlen_off = offset + 12
        b = body[strlen_off]
        if b < 0x80:
            strlen = b
            data_start = strlen_off + 1
        elif b & 0xC0 != 0xC0:
            if strlen_off + 1 >= len(body):
                break
            strlen = ((b & 0x3F) << 8) | body[strlen_off + 1]
            data_start = strlen_off + 2
        else:
            break

        if strlen < 1 or strlen > 10000:
            break

        byte_len = strlen * 2
        if data_start + byte_len > len(body):
            break

        try:
            text = body[data_start : data_start + byte_len].decode("utf-16-le")
            text = text.rstrip("\x00")
        except (UnicodeDecodeError, ValueError):
            offset = data_start + byte_len + 5
            continue

        if not text or not any(c.isprintable() for c in text):
            offset = data_start + byte_len + 5
            continue

        if ref == _REF_NAME:
            return text

        if first_string is None:
            first_string = text

        # Advance past string data + 5 trailing zero bytes
        offset = data_start + byte_len + 5

    return first_string


def decode_utf16le(data: bytes) -> str | None:
    """Decode bytes as a UTF-16LE string.

    Strips BOM and null terminators. Returns None if the data
    doesn't decode cleanly or contains no printable characters.
    """
    if len(data) < 2:
        return None

    start = 0
    if data[:2] == b"\xff\xfe":
        start = 2

    try:
        text = data[start:].decode("utf-16-le")
    except (UnicodeDecodeError, ValueError):
        return None

    text = text.rstrip("\x00")

    if not text or not any(c.isprintable() for c in text):
        return None

    return text


def decode_all_sub_entries(data: bytes) -> dict[int, str]:
    """Extract ALL sub-entry strings from a structured localization entry.

    Returns a dict mapping sub-entry ref -> decoded text for every
    sub-entry in the localization record. Known refs:
      0x0DA44875 = Name
      0x033D632E = Description (short label)
      0x0B609513 = Tooltip (in-game effect description)
      0x0F0EFF4E = Summary (condensed one-line)
      0x05E535B5 = PluralName
    """
    if len(data) < 14:
        return {}

    did = struct.unpack_from("<I", data, 0)[0]
    if (did >> 24) & 0xFF in (0x25, 0x0A):
        ref_count = data[4]
        body_offset = 5 + ref_count * 4
    else:
        ref_count = data[0]
        body_offset = 1 + ref_count * 4

    if body_offset + 1 > len(data):
        return {}

    body = data[body_offset:]
    sub_count = body[0]

    if sub_count < 1 or sub_count > 10:
        return {}

    results: dict[int, str] = {}
    offset = 1

    for _ in range(sub_count):
        if offset + 13 > len(body):
            break

        ref = struct.unpack_from("<I", body, offset)[0]

        strlen_off = offset + 12
        if strlen_off >= len(body):
            break
        b = body[strlen_off]
        if b < 0x80:
            strlen = b
            data_start = strlen_off + 1
        elif b & 0xC0 != 0xC0:
            if strlen_off + 1 >= len(body):
                break
            strlen = ((b & 0x3F) << 8) | body[strlen_off + 1]
            data_start = strlen_off + 2
        else:
            break

        if strlen < 1 or strlen > 10000:
            break

        byte_len = strlen * 2
        if data_start + byte_len > len(body):
            break

        try:
            text = body[data_start : data_start + byte_len].decode("utf-16-le")
            text = text.rstrip("\x00")
        except (UnicodeDecodeError, ValueError):
            offset = data_start + byte_len + 5
            continue

        if text and any(c.isprintable() for c in text):
            results[ref] = text

        offset = data_start + byte_len + 5

    return results


def load_tooltip_table(
    archive: DatArchive,
    entries: dict[int, FileEntry] | None = None,
    limit: int = 0,
) -> dict[int, str]:
    """Extract tooltip/description strings from archive entries.

    Like load_string_table but returns the Tooltip sub-entry
    (ref 0x0B609513) instead of the Name. Falls back to the Summary
    (0x0F0EFF4E) or Description (0x033D632E) sub-entry if no Tooltip.

    Returns dict mapping file_id -> tooltip text.
    """
    if entries is None:
        if archive.header is None:
            archive.read_header()
        entries = traverse_btree(archive)
        if not entries:
            entries = scan_file_table(archive)

    tooltips: dict[int, str] = {}
    count = 0

    for file_id in sorted(entries.keys()):
        if 0 < limit <= count:
            break

        entry = entries[file_id]
        try:
            data = read_entry_data(archive, entry)
        except (ValueError, OSError):
            continue

        subs = decode_all_sub_entries(data)
        # Prefer tooltip, fall back to summary, then description
        text = (
            subs.get(_REF_TOOLTIP)
            or subs.get(_REF_SUMMARY)
            or subs.get(_REF_DESC)
        )
        if text:
            tooltips[file_id] = text

        count += 1

    return tooltips


def resolve_string_ref(file_id: int, string_table: dict[int, str]) -> str | None:
    """Look up a string by file ID in the string table."""
    return string_table.get(file_id)
