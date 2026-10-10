from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.cron_match import cron_matches

HK = ZoneInfo("Asia/Hong_Kong")


def _dt(y, m, d, hh, mm) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=HK)


def test_daily_at_0600():
    expr = "0 6 * * *"
    assert cron_matches(expr, _dt(2026, 10, 10, 6, 0))
    assert not cron_matches(expr, _dt(2026, 10, 10, 6, 1))
    assert not cron_matches(expr, _dt(2026, 10, 10, 7, 0))


def test_weekly_sunday():
    # 2026-10-11 is Sunday
    expr = "0 7 * * 0"
    assert cron_matches(expr, _dt(2026, 10, 11, 7, 0))
    assert not cron_matches(expr, _dt(2026, 10, 10, 7, 0))  # Saturday


def test_step_minutes():
    expr = "*/15 * * * *"
    assert cron_matches(expr, _dt(2026, 10, 10, 12, 0))
    assert cron_matches(expr, _dt(2026, 10, 10, 12, 45))
    assert not cron_matches(expr, _dt(2026, 10, 10, 12, 10))


def test_list_and_range():
    assert cron_matches("0 6,7 * * *", _dt(2026, 10, 10, 7, 0))
    assert cron_matches("0 6-8 * * *", _dt(2026, 10, 10, 8, 0))
    assert not cron_matches("0 6-8 * * *", _dt(2026, 10, 10, 9, 0))


def test_invalid_field_count():
    with pytest.raises(ValueError):
        cron_matches("0 6 * *", _dt(2026, 10, 10, 6, 0))
