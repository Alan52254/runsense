from datetime import date, timedelta

from scripts.shift_demo_dates import shift_json


def test_shift_nested_dates_preserves_measurements_and_relative_offsets():
    original = {"weather": {"2026-10-20": {"at": "2026-10-20T12:34:56+09:00"}},
                "days": ["2026-10-20", "2026-10-22"], "pace": 300,
                "offset_s": [0, 60], "text": "Plan 2026-10-20–2026-10-22"}
    shifted = shift_json(original, timedelta(days=3))
    assert shifted["weather"]["2026-10-23"]["at"] == "2026-10-23T12:34:56+09:00"
    assert shifted["days"] == ["2026-10-23", "2026-10-25"]
    assert shifted["pace"] == 300 and shifted["offset_s"] == [0, 60]
    assert shifted["text"] == "Plan 2026-10-23–2026-10-25"
    assert original["days"][0] == "2026-10-20"
    assert shift_json(shifted, timedelta(days=-3)) == original


def test_shift_handles_year_boundary_and_ignores_non_dates():
    assert shift_json(["2026-12-31", "v2026-99-99", None], timedelta(days=3)) == ["2027-01-03", "v2026-99-99", None]
