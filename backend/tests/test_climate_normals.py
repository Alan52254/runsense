"""Pure unit tests -- no DB needed."""

from __future__ import annotations

from app.climate_normals import get_climate_normal


def test_known_city_english_name_returns_the_right_month():
    august = get_climate_normal("Tokyo", 8)
    assert august is not None
    assert august.mean_c == 26.9


def test_known_city_is_case_insensitive():
    assert get_climate_normal("TOKYO", 8) == get_climate_normal("tokyo", 8)


def test_known_city_chinese_name_matches_the_english_one():
    assert get_climate_normal("倫敦", 1) == get_climate_normal("London", 1)


def test_unknown_city_returns_none_rather_than_guessing():
    assert get_climate_normal("Atlantis", 6) is None


def test_none_or_empty_city_returns_none():
    assert get_climate_normal(None, 6) is None
    assert get_climate_normal("", 6) is None


def test_taipei_summer_is_hotter_than_winter():
    july = get_climate_normal("Taipei", 7)
    january = get_climate_normal("Taipei", 1)
    assert july is not None and january is not None
    assert july.mean_c > january.mean_c
    assert july.low_c > january.high_c  # Taipei's coolest July reading still beats its warmest January one
