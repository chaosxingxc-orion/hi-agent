"""TDD tests for scripts/_governance/wave.

Single source of truth for current wave label.

current_wave is read from docs/current-wave.txt. Drift between this file,
the latest manifest's `wave` field, the allowlists.yaml `current_wave` field,
and the latest closure notice `Wave:` line is exactly the GS-8/GS-15 bug
class. validate_wave_consistency surfaces any inconsistency.
"""
from __future__ import annotations

import pytest

from scripts._governance import wave


class TestParseWave:
    def test_parses_wave_label(self) -> None:
        assert wave.parse_wave("Wave 17") == 17
        assert wave.parse_wave("Wave 1") == 1
        assert wave.parse_wave("Wave 100") == 100

    def test_parses_int_string(self) -> None:
        assert wave.parse_wave("17") == 17

    def test_parses_int(self) -> None:
        assert wave.parse_wave(17) == 17

    def test_strips_whitespace(self) -> None:
        assert wave.parse_wave("  Wave 17  \n") == 17

    def test_rejects_garbage(self) -> None:
        with pytest.raises(ValueError):
            wave.parse_wave("Wave seventeen")
        with pytest.raises(ValueError):
            wave.parse_wave("not a wave")
        with pytest.raises(ValueError):
            wave.parse_wave("")

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValueError):
            wave.parse_wave("Wave -1")
        with pytest.raises(ValueError):
            wave.parse_wave(-1)


class TestFormatWave:
    def test_formats_int(self) -> None:
        assert wave.format_wave(17) == "Wave 17"
        assert wave.format_wave(1) == "Wave 1"

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValueError):
            wave.format_wave(-1)


class TestValidateWaveConsistency:
    def test_all_equal_returns_empty(self) -> None:
        msgs = wave.validate_wave_consistency(
            current_wave_txt="Wave 17",
            allowlists_yaml=17,
            manifest_wave="Wave 17",
            notice_wave="17",
        )
        assert msgs == []

    def test_drift_reports_each_mismatch(self) -> None:
        msgs = wave.validate_wave_consistency(
            current_wave_txt="Wave 14",
            allowlists_yaml=16,
            manifest_wave="Wave 14",
            notice_wave="Wave 17",
        )
        assert len(msgs) >= 1
        # Should mention the mismatched values
        joined = " ".join(msgs)
        assert "14" in joined or "16" in joined or "17" in joined

    def test_unparseable_source_reported(self) -> None:
        msgs = wave.validate_wave_consistency(
            current_wave_txt="Wave 17",
            broken_source="not a wave label",
        )
        assert any("broken_source" in m for m in msgs)

    def test_skips_none_sources(self) -> None:
        # A None source means "could not be read" — should not block consistency
        # but should be reported.
        msgs = wave.validate_wave_consistency(
            current_wave_txt="Wave 17",
            missing_source=None,
        )
        # None reported as missing
        assert any("missing_source" in m for m in msgs)


class TestCurrentWave:
    def test_current_wave_reads_from_file(self, tmp_path, monkeypatch) -> None:
        f = tmp_path / "current-wave.txt"
        f.write_text("Wave 17\n", encoding="utf-8")
        monkeypatch.setattr(wave, "_WAVE_FILE", f)
        assert wave.current_wave() == "Wave 17"
        assert wave.current_wave_number() == 17

    def test_current_wave_strips_newline(self, tmp_path, monkeypatch) -> None:
        f = tmp_path / "current-wave.txt"
        f.write_text("Wave 17\r\n", encoding="utf-8")
        monkeypatch.setattr(wave, "_WAVE_FILE", f)
        assert wave.current_wave() == "Wave 17"


class TestIsExpired:
    def test_expired_when_le_current(self, tmp_path, monkeypatch) -> None:
        f = tmp_path / "current-wave.txt"
        f.write_text("Wave 17", encoding="utf-8")
        monkeypatch.setattr(wave, "_WAVE_FILE", f)
        assert wave.is_expired("Wave 16") is True
        assert wave.is_expired("Wave 17") is True
        assert wave.is_expired("Wave 18") is False

    def test_unparseable_returns_false(self, tmp_path, monkeypatch) -> None:
        f = tmp_path / "current-wave.txt"
        f.write_text("Wave 17", encoding="utf-8")
        monkeypatch.setattr(wave, "_WAVE_FILE", f)
        # Don't fail-close on garbage — preserves backward compat with _current_wave
        assert wave.is_expired("garbage") is False


class TestBackwardCompatShim:
    """The legacy scripts/_current_wave.py module must keep working."""

    def test_legacy_imports_work(self) -> None:
        from scripts import _current_wave
        assert callable(_current_wave.current_wave)
        assert callable(_current_wave.wave_number)
        assert callable(_current_wave.is_expired)

    def test_legacy_wave_number_parses(self) -> None:
        from scripts import _current_wave
        assert _current_wave.wave_number("Wave 17") == 17
