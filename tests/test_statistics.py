"""Test offline del calcolo delle statistiche."""
from datetime import date

from custom_components.italgas.api import Reading
from custom_components.italgas.coordinator import build_statistics, reading_start


def _r(d, v):
    return Reading(date=date.fromisoformat(d), value=v)


READINGS = [_r("2026-08-31", 3653), _r("2026-09-30", 3667), _r("2026-10-31", 3687)]


def test_first_import_starts_from_zero():
    stats = build_statistics(READINGS, None, None, None)
    assert [s["sum"] for s in stats] == [0, 14, 34]
    assert [s["state"] for s in stats] == [3653, 3667, 3687]


def test_incremental_import_continues_sum():
    last = reading_start(date(2026, 9, 30))
    stats = build_statistics(READINGS, last, 3667, 14)
    assert len(stats) == 1
    assert stats[0]["sum"] == 34
    assert stats[0]["start"] == reading_start(date(2026, 10, 31))


def test_nothing_new():
    last = reading_start(date(2026, 10, 31))
    assert build_statistics(READINGS, last, 3687, 34) == []


def test_meter_replacement_counts_new_meter_from_zero():
    stats = build_statistics([_r("2023-08-25", 3835), _r("2023-08-26", 0), _r("2023-08-31", 5), _r("2023-09-30", 31)], None, None, None)
    assert [s["sum"] for s in stats] == [0, 0, 5, 31]
    stats = build_statistics([_r("2026-01-31", 500), _r("2026-02-28", 10)], None, None, None)
    assert [s["sum"] for s in stats] == [0, 10]
