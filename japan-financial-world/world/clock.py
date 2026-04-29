from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import calendar


@dataclass
class Clock:
    """
    World clock for date-based simulation.

    Responsibility:
    - Hold the simulation start date and current date.
    - Advance time by one calendar day.
    - Report calendar properties such as month, quarter, and period ends.

    It must not know anything about agents, spaces, markets, scenarios, or tasks.
    """

    start_date: date | None = None
    current_date: date | None = None

    def __post_init__(self) -> None:
        if self.start_date is None and self.current_date is None:
            raise ValueError("start_date or current_date is required")

        if self.start_date is None:
            self.start_date = self.current_date

        if self.current_date is None:
            self.current_date = self.start_date

        if self.current_date < self.start_date:
            raise ValueError("current_date cannot be earlier than start_date")

    @property
    def year(self) -> int:
        return self.current_date.year

    @property
    def month(self) -> int:
        return self.current_date.month

    @property
    def quarter(self) -> int:
        return (self.current_date.month - 1) // 3 + 1

    def step_day(self, days: int = 1) -> date:
        if days < 1:
            raise ValueError("days must be positive")

        self.current_date = self.current_date + timedelta(days=days)
        return self.current_date

    def advance(self, days: int = 1) -> date:
        return self.step_day(days=days)

    def next_date(self) -> date:
        return self.current_date + timedelta(days=1)

    def is_month_end(self) -> bool:
        last_day = calendar.monthrange(
            self.current_date.year,
            self.current_date.month,
        )[1]
        return self.current_date.day == last_day

    def is_quarter_end(self) -> bool:
        return self.is_month_end() and self.current_date.month in {3, 6, 9, 12}

    def is_year_end(self) -> bool:
        return self.current_date.month == 12 and self.current_date.day == 31
