"""Test offline del calcolo delle statistiche."""
from datetime import date, datetime, timedelta, timezone

from custom_components.italgas.api import Reading
from custom_components.italgas.coordinator import build_statistics, needs_fetch, reading_start


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


NOW = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
TODAY = date(2026, 11, 22)


def test_fetch_on_first_run():
    assert needs_fetch(None, None, NOW, TODAY)


def test_no_fetch_when_previous_month_reading_present():
    # c'è già la lettura del 31/10: niente accessi fino a dicembre
    assert not needs_fetch(date(2026, 10, 31), NOW - timedelta(days=20), NOW, TODAY)
    assert not needs_fetch(date(2026, 10, 31), NOW - timedelta(minutes=5), NOW, TODAY)


def test_fetch_at_most_daily_when_reading_expected():
    today = date(2026, 12, 3)  # attesa la lettura del 30/11
    now = datetime(2026, 12, 3, 12, tzinfo=timezone.utc)
    assert not needs_fetch(date(2026, 10, 31), now - timedelta(hours=6), now, today)
    assert needs_fetch(date(2026, 10, 31), now - timedelta(hours=25), now, today)
