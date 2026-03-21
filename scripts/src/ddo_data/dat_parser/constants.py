"""Shared constants for the DDO .dat archive parser."""

# File ID high bytes observed across DDO archives.
# Used to identify cross-archive references in binary entry data.
KNOWN_ID_HIGH_BYTES = {0x01, 0x07, 0x0A, 0x40, 0x41, 0x47, 0x78}

# Human-readable labels for the three main archive types.
FILE_ID_LABELS = {
    0x01: "general",
    0x07: "gamelogic",
    0x0A: "English",
    0x47: "gamelogic-spell",
}
