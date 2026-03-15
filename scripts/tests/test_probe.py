"""Tests for the data-driven binary format probe."""

import io
import struct

import pytest

from ddo_data.dat_parser.probe import (
    DecodedProperty,
    GameEntryHeader,
    ProbeResult,
    Type2Entry,
    Type4Entry,
    decode_type2,
    decode_type4,
    find_definition_refs,
    find_file_id_refs,
    find_float_values,
    find_length_prefixed_strings,
    format_probe_result,
    format_type2,
    format_type4,
    parse_entry_header,
    probe_entry,
    read_pascal_string,
    read_tsize,
    read_uint8,
    read_uint32,
    read_vle,
)

# ---------------------------------------------------------------------------
# VLE encoding tests
# ---------------------------------------------------------------------------


class TestReadVLE:
    def test_single_byte(self) -> None:
        """Values 0-127 are encoded as a single byte."""
        assert read_vle(io.BytesIO(b"\x00")) == 0
        assert read_vle(io.BytesIO(b"\x01")) == 1
        assert read_vle(io.BytesIO(b"\x7F")) == 127

    def test_two_byte(self) -> None:
        """Values with high bit set use 2-byte encoding."""
        # 0x80 | (high >> 8), low
        # Value 256 = 0x100: a = 0x80 | 0x01 = 0x81, b = 0x00
        ins = io.BytesIO(b"\x81\x00")
        assert read_vle(ins) == 256

        # Value 200 = 0xC8: a = 0x80 | 0x00 = 0x80, b = 0xC8
        ins = io.BytesIO(b"\x80\xC8")
        assert read_vle(ins) == 200

    def test_uint32_marker(self) -> None:
        """0xE0 prefix indicates a full uint32 LE follows."""
        val = struct.pack("<I", 0x12345678)
        ins = io.BytesIO(b"\xE0" + val)
        assert read_vle(ins) == 0x12345678

    def test_four_byte(self) -> None:
        """0xC0+ prefix uses 4-byte encoding: (a & 0x3F) << 24 | b << 16 | c."""
        # a = 0xC1 (0x40 set), b = 0x02, c = uint16 LE 0x0304
        ins = io.BytesIO(b"\xC1\x02\x04\x03")
        result = read_vle(ins)
        expected = (0x01 << 24) | (0x02 << 16) | 0x0304
        assert result == expected

    def test_empty_stream_raises(self) -> None:
        """Reading VLE from empty stream raises ValueError."""
        with pytest.raises(ValueError, match="end of stream"):
            read_vle(io.BytesIO(b""))

    def test_uint32_marker_truncated(self) -> None:
        """0xE0 followed by fewer than 4 bytes raises ValueError."""
        with pytest.raises(ValueError, match="end of stream"):
            read_vle(io.BytesIO(b"\xE0\x01\x02"))

    def test_two_byte_truncated(self) -> None:
        """Two-byte encoding with missing second byte raises ValueError."""
        with pytest.raises(ValueError, match="end of stream"):
            read_vle(io.BytesIO(b"\x80"))

    def test_four_byte_truncated(self) -> None:
        """Four-byte encoding (0xC0+) with missing trailing bytes raises ValueError."""
        with pytest.raises(ValueError, match="end of stream"):
            read_vle(io.BytesIO(b"\xC1\x02"))


class TestReadTsize:
    def test_basic(self) -> None:
        """read_tsize skips 1 byte then reads VLE."""
        # skip byte (0xFF), then VLE byte (0x05)
        ins = io.BytesIO(b"\xFF\x05")
        assert read_tsize(ins) == 5

    def test_skip_byte_consumed(self) -> None:
        """The skip byte is consumed but its value is irrelevant."""
        ins = io.BytesIO(b"\x00\x0A")
        assert read_tsize(ins) == 10
        assert ins.tell() == 2

    def test_empty_stream_raises(self) -> None:
        """Empty stream raises ValueError before VLE read."""
        with pytest.raises(ValueError, match="end of stream"):
            read_tsize(io.BytesIO(b""))


class TestReadUtils:
    def test_read_uint32(self) -> None:
        ins = io.BytesIO(struct.pack("<I", 0xDEADBEEF))
        assert read_uint32(ins) == 0xDEADBEEF

    def test_read_uint8(self) -> None:
        ins = io.BytesIO(b"\x42")
        assert read_uint8(ins) == 0x42

    def test_read_uint32_truncated(self) -> None:
        """Truncated uint32 raises ValueError."""
        with pytest.raises(ValueError, match="end of stream"):
            read_uint32(io.BytesIO(b"\x01\x02"))

    def test_read_uint8_empty(self) -> None:
        """Empty stream raises ValueError for uint8."""
        with pytest.raises(ValueError, match="end of stream"):
            read_uint8(io.BytesIO(b""))

    def test_read_pascal_string(self) -> None:
        """VLE length prefix followed by Latin-1 text."""
        text = b"Hello"
        ins = io.BytesIO(bytes([len(text)]) + text)
        assert read_pascal_string(ins) == "Hello"

    def test_read_pascal_string_truncated(self) -> None:
        ins = io.BytesIO(b"\x0AHi")
        with pytest.raises(ValueError, match="truncated"):
            read_pascal_string(ins)


# ---------------------------------------------------------------------------
# Entry header tests
# ---------------------------------------------------------------------------


class TestParseEntryHeader:
    def test_zero_refs(self) -> None:
        """DID with 0 file ID references."""
        data = struct.pack("<I", 2) + b"\x00" + b"\xAA" * 10
        header = parse_entry_header(data)
        assert header.did == 2
        assert header.ref_count == 0
        assert header.file_ids == []
        assert header.body_offset == 5

    def test_one_ref(self) -> None:
        """DID with 1 file ID reference."""
        data = struct.pack("<I", 4) + b"\x01" + struct.pack("<I", 0x07000F15)
        header = parse_entry_header(data)
        assert header.did == 4
        assert header.ref_count == 1
        assert header.file_ids == [0x07000F15]
        assert header.body_offset == 9

    def test_multiple_refs(self) -> None:
        """DID with 5 file ID references."""
        ids = [0x0700033D, 0x0700021A, 0x07001F83, 0x070046D9, 0x07007FB7]
        data = struct.pack("<I", 4) + b"\x05"
        for fid in ids:
            data += struct.pack("<I", fid)
        header = parse_entry_header(data)
        assert header.did == 4
        assert header.ref_count == 5
        assert header.file_ids == ids
        assert header.body_offset == 25

    def test_too_short(self) -> None:
        with pytest.raises(ValueError, match="too short"):
            parse_entry_header(b"\x01\x00")


# ---------------------------------------------------------------------------
# Pattern detector tests
# ---------------------------------------------------------------------------


class TestFindDefinitionRefs:
    def test_finds_0x10_refs(self) -> None:
        data = b"\x00" * 4 + struct.pack("<I", 0x1000084C) + b"\x00" * 4
        refs = find_definition_refs(data)
        assert refs == [(4, 0x1000084C)]

    def test_ignores_non_0x10(self) -> None:
        data = struct.pack("<I", 0x07001234)
        refs = find_definition_refs(data)
        assert refs == []

    def test_start_offset(self) -> None:
        data = struct.pack("<I", 0x10000001) + struct.pack("<I", 0x10000002)
        refs = find_definition_refs(data, start=4)
        assert refs == [(4, 0x10000002)]


class TestFindFileIdRefs:
    def test_finds_known_high_bytes(self) -> None:
        data = struct.pack("<III", 0x07001234, 0x0A005678, 0x01009ABC)
        refs = find_file_id_refs(data)
        # Byte-level scanning may find boundary artifacts between adjacent values;
        # verify the 3 real values are present
        values = {v for _, v in refs}
        assert 0x07001234 in values
        assert 0x0A005678 in values
        assert 0x01009ABC in values

    def test_ignores_zero_low_bytes(self) -> None:
        """0x07000000 is not a valid file ID (low 24 bits are 0)."""
        data = struct.pack("<I", 0x07000000)
        refs = find_file_id_refs(data)
        assert refs == []


class TestFindLengthPrefixedStrings:
    def test_finds_ascii_string(self) -> None:
        text = b"Hello World"
        data = b"\x00" * 4 + bytes([len(text)]) + text + b"\x00" * 4
        strings = find_length_prefixed_strings(data)
        assert len(strings) == 1
        assert strings[0] == (4, "Hello World")

    def test_ignores_short_strings(self) -> None:
        """Strings shorter than 4 chars are ignored."""
        data = b"\x03Hi!"
        strings = find_length_prefixed_strings(data)
        assert strings == []

    def test_ignores_non_printable(self) -> None:
        data = b"\x05\x01\x02\x03\x04\x05"
        strings = find_length_prefixed_strings(data)
        assert strings == []


class TestFindFloatValues:
    def test_finds_meaningful_floats(self) -> None:
        data = struct.pack("<f", 1.0)
        floats = find_float_values(data)
        assert len(floats) == 1
        assert floats[0][0] == 0
        assert abs(floats[0][1] - 1.0) < 1e-6

    def test_ignores_zero(self) -> None:
        data = struct.pack("<f", 0.0)
        floats = find_float_values(data)
        assert floats == []


# ---------------------------------------------------------------------------
# Probe integration tests
# ---------------------------------------------------------------------------


class TestProbeEntry:
    def test_type4_with_refs(self) -> None:
        """Probe a synthetic type-4 entry with file ID refs."""
        ids = [0x0700033D, 0x0700021A]
        data = struct.pack("<I", 4) + b"\x02"
        for fid in ids:
            data += struct.pack("<I", fid)
        data += b"\x00" * 8  # body padding

        result = probe_entry(data)
        assert result.header.did == 4
        assert result.header.ref_count == 2
        assert result.header.file_ids == ids
        assert result.raw_size == len(data)

    def test_type1_with_ascii_string(self) -> None:
        """Probe an entry containing a length-prefixed ASCII string."""
        text = b"this has something to do with pulsing the health ring"
        data = struct.pack("<I", 1) + b"\x00"  # DID=1, 0 refs
        data += b"\x00" * 4  # some padding before string
        data += bytes([len(text)]) + text  # length-prefixed string

        result = probe_entry(data)
        assert result.header.did == 1
        assert len(result.ascii_strings) == 1
        assert result.ascii_strings[0][1] == text.decode("ascii")

    def test_entry_with_def_refs(self) -> None:
        """Probe an entry containing definition references."""
        data = struct.pack("<I", 2) + b"\x00"  # DID=2, 0 refs
        data += struct.pack("<III", 0x1000084C, 0x00000000, 0x100010B4)

        result = probe_entry(data)
        # Byte-level scanning may find boundary artifacts; verify real refs present
        def_values = {v for _, v in result.def_refs}
        assert 0x1000084C in def_values
        assert 0x100010B4 in def_values

    def test_coverage_calculation(self) -> None:
        """Coverage reflects how much of the body is accounted for."""
        data = struct.pack("<I", 2) + b"\x00"  # 5-byte header
        data += struct.pack("<f", 42.0)  # 4 bytes of float
        data += b"\x00" * 4  # 4 bytes unrecognized

        result = probe_entry(data)
        # Body is 8 bytes, float accounts for 4 → 50%
        assert 0.4 <= result.parse_coverage <= 0.6


class TestFormatProbeResult:
    def test_basic_formatting(self) -> None:
        header = GameEntryHeader(did=4, ref_count=1, file_ids=[0x07000F15], body_offset=9)
        result = ProbeResult(
            header=header,
            raw_size=39,
            def_refs=[(15, 0x100010B4)],
            ascii_strings=[],
            file_id_refs=[],
            float_values=[(20, 1.0)],
            parse_coverage=0.35,
        )
        output = format_probe_result(result)
        assert "DID: 4" in output
        assert "0x07000F15" in output
        assert "0x100010B4" in output
        assert "35.0%" in output


# ---------------------------------------------------------------------------
# Type-4 decoder tests
# ---------------------------------------------------------------------------


class TestDecodeType4:
    def _make_type4(
        self,
        file_ids: list[int] | None = None,
        props_data: bytes = b"",
        prop_count: int = 0,
    ) -> bytes:
        """Build a synthetic type-4 entry with given properties."""
        ids = file_ids or []
        data = struct.pack("<I", 4)  # DID=4
        data += bytes([len(ids)])
        for fid in ids:
            data += struct.pack("<I", fid)
        # Body: pad u32 + flag byte + prop count + properties
        data += struct.pack("<I", 0)  # pad
        data += b"\x00"  # flag
        data += bytes([prop_count])
        data += props_data
        return data

    def test_empty_properties(self) -> None:
        """Type-4 entry with 0 properties."""
        data = self._make_type4(prop_count=0)
        result = decode_type4(data)
        assert result.header.did == 4
        assert result.properties == []
        assert result.remaining_bytes == 0

    def test_simple_properties(self) -> None:
        """Type-4 entry with simple [key:u32][value:u32=0] pairs."""
        props = struct.pack("<II", 0x100010B4, 0) + struct.pack("<II", 0x100010B7, 0)
        data = self._make_type4(prop_count=2, props_data=props)
        result = decode_type4(data)
        assert len(result.properties) == 2
        assert result.properties[0].key == 0x100010B4
        assert result.properties[0].value == 0
        assert not result.properties[0].is_array
        assert result.properties[1].key == 0x100010B7
        assert result.remaining_bytes == 0

    def test_array_property(self) -> None:
        """Type-4 entry with an array property (value > 0 = element count)."""
        # key=0x10000E79, count=3, elements=[0x70001234, 0x70005678, 0x70009ABC]
        props = struct.pack("<II", 0x10000E79, 3)
        props += struct.pack("<III", 0x70001234, 0x70005678, 0x70009ABC)
        data = self._make_type4(prop_count=1, props_data=props)
        result = decode_type4(data)
        assert len(result.properties) == 1
        prop = result.properties[0]
        assert prop.key == 0x10000E79
        assert prop.is_array
        assert prop.value == [0x70001234, 0x70005678, 0x70009ABC]
        assert result.remaining_bytes == 0

    def test_mixed_properties(self) -> None:
        """Type-4 entry mixing simple and array properties."""
        props = b""
        props += struct.pack("<II", 0x10001A58, 0)  # simple
        props += struct.pack("<II", 0x10001B58, 2)  # array count=2
        props += struct.pack("<II", 0x70006C3B, 0x70006C3C)  # elements
        props += struct.pack("<II", 0x0000001B, 0)  # simple (small int key)
        data = self._make_type4(prop_count=3, props_data=props)
        result = decode_type4(data)
        assert len(result.properties) == 3
        assert not result.properties[0].is_array
        assert result.properties[1].is_array
        assert result.properties[1].value == [0x70006C3B, 0x70006C3C]
        assert not result.properties[2].is_array
        assert result.remaining_bytes == 0

    def test_with_header_file_ids(self) -> None:
        """Type-4 entry with file ID refs in header."""
        props = struct.pack("<II", 0x10000E7C, 0)
        data = self._make_type4(
            file_ids=[0x07000F15, 0x0700021A],
            prop_count=1,
            props_data=props,
        )
        result = decode_type4(data)
        assert result.header.ref_count == 2
        assert result.header.file_ids == [0x07000F15, 0x0700021A]
        assert len(result.properties) == 1

    def test_too_short_body(self) -> None:
        """Entry with body too short for property parsing."""
        data = struct.pack("<I", 4) + b"\x00"  # DID=4, 0 refs, no body
        result = decode_type4(data)
        assert result.properties == []
        assert result.remaining_bytes == 0


class TestFormatType4:
    def test_output(self) -> None:
        entry = Type4Entry(
            header=GameEntryHeader(did=4, ref_count=1, file_ids=[0x07000F15], body_offset=9),
            raw_size=39,
            properties=[
                DecodedProperty(key=0x100010B4, value=0),
                DecodedProperty(key=0x10001B58, value=[0x70006C3B, 0x70006C3C]),
            ],
            remaining_bytes=0,
        )
        output = format_type4(entry)
        assert "DID: 4" in output
        assert "0x07000F15" in output
        assert "0x100010B4 = 0" in output
        assert "0x70006C3B" in output
        assert "Unparsed" not in output


# ---------------------------------------------------------------------------
# Type-2 decoder tests
# ---------------------------------------------------------------------------


class TestDecodeType2:
    def _make_simple_type2(
        self,
        file_ids: list[int] | None = None,
        props_data: bytes = b"",
        prop_count: int = 0,
    ) -> bytes:
        """Build a synthetic simple type-2 entry (type-4-like, pad=1)."""
        ids = file_ids or []
        data = struct.pack("<I", 2)  # DID=2
        data += bytes([len(ids)])
        for fid in ids:
            data += struct.pack("<I", fid)
        # Body: pad u32=1 + flag byte + prop count + properties
        data += struct.pack("<I", 1)  # pad = 1 (distinguishes simple type-2)
        data += b"\x00"  # flag
        data += bytes([prop_count])
        data += props_data
        return data

    def _make_complex_type2(
        self,
        file_ids: list[int] | None = None,
        tsize_skip: int = 0xFF,
        tsize_count: int = 0,
        body_after_tsize: bytes = b"",
    ) -> bytes:
        """Build a synthetic complex type-2 entry (tsize-based)."""
        ids = file_ids or []
        data = struct.pack("<I", 2)  # DID=2
        data += bytes([len(ids)])
        for fid in ids:
            data += struct.pack("<I", fid)
        # Body: tsize (skip byte + VLE count) + remaining
        data += bytes([tsize_skip])  # skip byte
        data += bytes([tsize_count])  # VLE count (single byte for <128)
        data += body_after_tsize
        return data

    def test_simple_empty(self) -> None:
        """Simple type-2 with 0 properties."""
        data = self._make_simple_type2(prop_count=0)
        result = decode_type2(data)
        assert result.variant == "simple"
        assert result.outer_count == 0
        assert result.properties == []
        assert result.remaining_bytes == 0

    def test_simple_with_properties(self) -> None:
        """Simple type-2 with key-value pairs (same format as type-4)."""
        props = struct.pack("<II", 0x100010B4, 0) + struct.pack("<II", 0x100010B7, 0)
        data = self._make_simple_type2(prop_count=2, props_data=props)
        result = decode_type2(data)
        assert result.variant == "simple"
        assert result.outer_count == 2
        assert len(result.properties) == 2
        assert result.properties[0].key == 0x100010B4
        assert result.properties[1].key == 0x100010B7
        assert result.remaining_bytes == 0

    def test_simple_with_array(self) -> None:
        """Simple type-2 with an array property."""
        props = struct.pack("<II", 0x10000E79, 2)  # key, array count=2
        props += struct.pack("<II", 0x70001234, 0x70005678)  # elements
        data = self._make_simple_type2(prop_count=1, props_data=props)
        result = decode_type2(data)
        assert result.variant == "simple"
        assert len(result.properties) == 1
        assert result.properties[0].is_array
        assert result.properties[0].value == [0x70001234, 0x70005678]
        assert result.remaining_bytes == 0

    def test_simple_with_file_ids(self) -> None:
        """Simple type-2 with header file ID refs."""
        props = struct.pack("<II", 0x10000001, 0)
        data = self._make_simple_type2(
            file_ids=[0x07000F15, 0x0700021A],
            prop_count=1,
            props_data=props,
        )
        result = decode_type2(data)
        assert result.variant == "simple"
        assert result.header.ref_count == 2
        assert result.header.file_ids == [0x07000F15, 0x0700021A]

    def test_complex_pairs_empty(self) -> None:
        """Complex type-2 with tsize count=0."""
        data = self._make_complex_type2(tsize_count=0)
        result = decode_type2(data)
        assert result.variant == "complex-pairs"
        assert result.outer_count == 0
        assert result.properties == []

    def test_complex_pairs_with_properties(self) -> None:
        """Complex type-2 where greedy pairs parse exactly."""
        body = struct.pack("<II", 0x100010B4, 0)  # 1 key-value pair
        data = self._make_complex_type2(tsize_count=1, body_after_tsize=body)
        result = decode_type2(data)
        assert result.variant == "complex-pairs"
        assert result.outer_count == 1
        assert len(result.properties) == 1
        assert result.properties[0].key == 0x100010B4

    def test_complex_partial_fallback(self) -> None:
        """Complex type-2 where pairs don't fit -> pattern detection."""
        # 2 properties claimed but body has 12 bytes (not 16 = 2*8)
        body = struct.pack("<III", 0x1000084C, 0x00000001, 0x100010B4)
        data = self._make_complex_type2(tsize_count=2, body_after_tsize=body)
        result = decode_type2(data)
        assert result.variant == "complex-partial"
        assert result.outer_count == 2
        assert result.remaining_bytes > 0
        # Pattern detection should find the def refs
        def_values = {v for _, v in result.body_def_refs}
        assert 0x1000084C in def_values

    def test_complex_partial_with_strings(self) -> None:
        """Complex type-2 with ASCII strings detected in body."""
        text = b"Enhancement_WarforgedBody"
        body = struct.pack("<I", 0x1000084C)  # a def ref
        body += bytes([len(text)]) + text  # length-prefixed string
        data = self._make_complex_type2(tsize_count=1, body_after_tsize=body)
        result = decode_type2(data)
        assert result.variant == "complex-partial"
        assert len(result.body_ascii_strings) >= 1
        found = any("Enhancement_WarforgedBody" in s for _, s in result.body_ascii_strings)
        assert found

    def test_short_body(self) -> None:
        """Type-2 entry with body too short for any strategy."""
        data = struct.pack("<I", 2) + b"\x00" + b"\xAA"  # 1-byte body
        result = decode_type2(data)
        assert result.variant == "unknown"
        assert result.remaining_bytes == 1

    def test_too_short_for_header(self) -> None:
        """Entry with insufficient data for header raises ValueError."""
        with pytest.raises(ValueError, match="too short"):
            decode_type2(b"\x02\x00")


class TestFormatType2:
    def test_simple_output(self) -> None:
        entry = Type2Entry(
            header=GameEntryHeader(did=2, ref_count=1, file_ids=[0x07000F15], body_offset=9),
            raw_size=25,
            variant="simple",
            outer_count=1,
            properties=[DecodedProperty(key=0x100010B4, value=0)],
            remaining_bytes=0,
        )
        output = format_type2(entry)
        assert "DID: 2" in output
        assert "Variant: simple" in output
        assert "0x07000F15" in output
        assert "0x100010B4 = 0" in output

    def test_complex_partial_output(self) -> None:
        entry = Type2Entry(
            header=GameEntryHeader(did=2, ref_count=0, file_ids=[], body_offset=5),
            raw_size=50,
            variant="complex-partial",
            outer_count=3,
            remaining_bytes=40,
            body_def_refs=[(4, 0x1000084C), (12, 0x100010B4)],
            body_ascii_strings=[(20, "test_string")],
            body_floats=[(30, 1.0)],
        )
        output = format_type2(entry)
        assert "Variant: complex-partial" in output
        assert "Properties: 3" in output
        assert "definition registry" in output.lower()
        assert "0x1000084C" in output
        assert "test_string" in output
        assert "1" in output  # 1.0 formatted as "1" by :.4g

    def test_complex_pairs_no_unparsed(self) -> None:
        entry = Type2Entry(
            header=GameEntryHeader(did=2, ref_count=0, file_ids=[], body_offset=5),
            raw_size=15,
            variant="complex-pairs",
            outer_count=1,
            properties=[DecodedProperty(key=0x1B, value=0)],
            remaining_bytes=0,
        )
        output = format_type2(entry)
        assert "complex-pairs" in output
        assert "Unparsed" not in output
