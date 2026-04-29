from datetime import date

import pytest

from world.clock import Clock


def test_clock_initializes_current_date_from_start_date():
    clock = Clock(start_date=date(2026, 1, 1))

    assert clock.start_date == date(2026, 1, 1)
    assert clock.current_date == date(2026, 1, 1)


def test_clock_rejects_current_date_before_start_date():
    with pytest.raises(ValueError):
        Clock(
            start_date=date(2026, 1, 2),
            current_date=date(2026, 1, 1),
        )


def test_step_day_advances_one_day_by_default():
    clock = Clock(start_date=date(2026, 1, 1))

    clock.step_day()

    assert clock.current_date == date(2026, 1, 2)


def test_step_day_can_advance_multiple_days():
    clock = Clock(start_date=date(2026, 1, 1))

    clock.step_day(days=10)

    assert clock.current_date == date(2026, 1, 11)


def test_step_day_rejects_non_positive_days():
    clock = Clock(start_date=date(2026, 1, 1))

    with pytest.raises(ValueError):
        clock.step_day(days=0)


def test_month_quarter_year_properties():
    clock = Clock(start_date=date(2026, 5, 15))

    assert clock.month == 5
    assert clock.quarter == 2
    assert clock.year == 2026


def test_month_end_detection():
    assert Clock(start_date=date(2026, 1, 31)).is_month_end()
    assert not Clock(start_date=date(2026, 1, 30)).is_month_end()


def test_february_month_end_detection_in_non_leap_year():
    assert Clock(start_date=date(2026, 2, 28)).is_month_end()


def test_february_month_end_detection_in_leap_year():
    assert Clock(start_date=date(2028, 2, 29)).is_month_end()


def test_quarter_end_detection():
    assert Clock(start_date=date(2026, 3, 31)).is_quarter_end()
    assert Clock(start_date=date(2026, 6, 30)).is_quarter_end()
    assert Clock(start_date=date(2026, 9, 30)).is_quarter_end()
    assert Clock(start_date=date(2026, 12, 31)).is_quarter_end()

    assert not Clock(start_date=date(2026, 4, 30)).is_quarter_end()


def test_year_end_detection():
    assert Clock(start_date=date(2026, 12, 31)).is_year_end()
    assert not Clock(start_date=date(2026, 12, 30)).is_year_end()