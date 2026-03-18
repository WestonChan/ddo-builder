"""Tests for entity identification via localization cross-reference."""

from collections import Counter

from ddo_data.dat_parser.identify import (
    IdentifyResult,
    _extract_prefix,
    format_identify,
)


# ---------------------------------------------------------------------------
# _extract_prefix
# ---------------------------------------------------------------------------


class TestExtractPrefix:
    def test_colon_prefix(self) -> None:
        assert _extract_prefix("Quest: The Waterworks") == "Quest"

    def test_multiword_colon_prefix(self) -> None:
        assert _extract_prefix("Spell School: Evocation") == "Spell School"

    def test_parenthetical_suffix(self) -> None:
        assert _extract_prefix("Boots of the Ninja (Leather)") == "Leather"

    def test_first_word_fallback(self) -> None:
        assert _extract_prefix("Fireball") == "Fireball"

    def test_strips_trailing_punctuation(self) -> None:
        # rstrip strips trailing punctuation from the first word
        result = _extract_prefix("Flame, the Burning")
        assert result == "Flame"

    def test_bracketed_suffix_ignored_with_colon(self) -> None:
        # Bracketed part after the colon should not affect prefix extraction
        result = _extract_prefix("Quest: Name [E]")
        assert result == "Quest"

    def test_empty_string_does_not_crash(self) -> None:
        # Should return something, not raise
        result = _extract_prefix("")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# format_identify
# ---------------------------------------------------------------------------


class TestFormatIdentify:
    def _make_result(self) -> IdentifyResult:
        result = IdentifyResult()
        result.total_gamelogic = 1000
        result.total_named = 400
        result.by_high_byte = {0x79: 500, 0x70: 400, 0x07: 100}
        result.named_by_high_byte = {0x79: 300, 0x70: 80, 0x07: 20}
        result.prefix_counts = Counter({"Quest": 150, "Spell": 100, "Feat": 50})
        result.sample_names = {
            0x79: ["Boots of the Magi", "Ring of Fire"],
            0x70: ["Effect A"],
        }
        return result

    def test_total_line_present(self) -> None:
        output = format_identify(self._make_result())
        assert "1,000" in output
        assert "400" in output

    def test_percentage_shown(self) -> None:
        output = format_identify(self._make_result())
        assert "40.0%" in output

    def test_high_byte_rows(self) -> None:
        output = format_identify(self._make_result())
        assert "0x79" in output
        assert "0x70" in output
        assert "0x07" in output

    def test_prefix_counts_shown(self) -> None:
        output = format_identify(self._make_result())
        assert "Quest" in output
        assert "Spell" in output

    def test_zero_total_does_not_crash(self) -> None:
        result = IdentifyResult()
        output = format_identify(result)
        assert isinstance(output, str)
        assert "0" in output
