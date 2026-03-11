"""Decompress compressed entries from Turbine .dat archives."""

import zlib


def decompress_entry(data: bytes) -> bytes:
    """Decompress a compressed .dat archive entry.

    Turbine archives use zlib compression for some entries.
    The exact compression format needs to be verified against
    the DATUnpacker source code.
    """
    try:
        return zlib.decompress(data)
    except zlib.error:
        # May not be compressed, or may use a different format
        return data
