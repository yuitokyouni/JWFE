from datetime import date

from world.clock import Clock
from world.scheduler import Frequency, Phase, Scheduler


def test_register_task():
    scheduler = Scheduler()

    task = scheduler.register(
        space="investor",
        frequency=Frequency.DAILY,
        task="investor.trade",
        order=10,
    )

    assert task.space == "investor"
    assert task.frequency == Frequency.DAILY
    assert task.task == "investor.trade"
    assert task.order == 10


def test_daily_task_is_due_every_day():
    scheduler = Scheduler()
    scheduler.register(
        space="investor",
        frequency=Frequency.DAILY,
        task="investor.trade",
    )

    clock = Clock(start_date=date(2026, 1, 15))
    due = scheduler.due_tasks(clock)

    assert [task.task for task in due] == ["investor.trade"]


def test_monthly_task_is_due_only_on_month_end():
    scheduler = Scheduler()
    scheduler.register(
        space="banking",
        frequency=Frequency.MONTHLY,
        task="banking.update_lending_stance",
    )

    normal_day = Clock(start_date=date(2026, 1, 30))
    month_end = Clock(start_date=date(2026, 1, 31))

    assert scheduler.due_tasks(normal_day) == ()
    assert [task.task for task in scheduler.due_tasks(month_end)] == [
        "banking.update_lending_stance"
    ]


def test_quarterly_task_is_due_only_on_quarter_end():
    scheduler = Scheduler()
    scheduler.register(
        space="corporate",
        frequency=Frequency.QUARTERLY,
        task="corporate.report_earnings",
    )

    month_end_not_quarter_end = Clock(start_date=date(2026, 4, 30))
    quarter_end = Clock(start_date=date(2026, 6, 30))

    assert scheduler.due_tasks(month_end_not_quarter_end) == ()
    assert [task.task for task in scheduler.due_tasks(quarter_end)] == [
        "corporate.report_earnings"
    ]


def test_yearly_task_is_due_only_on_year_end():
    scheduler = Scheduler()
    scheduler.register(
        space="macro",
        frequency=Frequency.YEARLY,
        task="macro.update_long_term_trends",
    )

    not_year_end = Clock(start_date=date(2026, 12, 30))
    year_end = Clock(start_date=date(2026, 12, 31))

    assert scheduler.due_tasks(not_year_end) == ()
    assert [task.task for task in scheduler.due_tasks(year_end)] == [
        "macro.update_long_term_trends"
    ]


def test_year_end_returns_daily_monthly_quarterly_and_yearly_tasks():
    scheduler = Scheduler()
    scheduler.register(space="investor", frequency=Frequency.DAILY, task="daily")
    scheduler.register(space="banking", frequency=Frequency.MONTHLY, task="monthly")
    scheduler.register(space="corporate", frequency=Frequency.QUARTERLY, task="quarterly")
    scheduler.register(space="macro", frequency=Frequency.YEARLY, task="yearly")

    clock = Clock(start_date=date(2026, 12, 31))
    due = scheduler.due_tasks(clock)

    assert [task.task for task in due] == [
        "daily",
        "monthly",
        "quarterly",
        "yearly",
    ]


def test_execution_order_is_deterministic_by_frequency_then_order():
    scheduler = Scheduler()

    scheduler.register(space="b", frequency=Frequency.DAILY, task="daily_20", order=20)
    scheduler.register(space="a", frequency=Frequency.DAILY, task="daily_10", order=10)
    scheduler.register(space="a", frequency=Frequency.MONTHLY, task="monthly_0", order=0)

    clock = Clock(start_date=date(2026, 1, 31))
    due = scheduler.due_tasks(clock)

    assert [task.task for task in due] == [
        "daily_10",
        "daily_20",
        "monthly_0",
    ]


def test_can_filter_due_tasks_by_space():
    scheduler = Scheduler()

    scheduler.register(space="investor", frequency=Frequency.DAILY, task="investor.trade")
    scheduler.register(space="banking", frequency=Frequency.DAILY, task="banking.update")

    clock = Clock(start_date=date(2026, 1, 15))
    due = scheduler.due_tasks(clock, space="banking")

    assert [task.task for task in due] == ["banking.update"]


def test_can_filter_due_tasks_by_phase():
    scheduler = Scheduler()

    scheduler.register(
        space="investor",
        frequency=Frequency.DAILY,
        task="investor.trade",
        phase=Phase.MAIN,
    )

    clock = Clock(start_date=date(2026, 1, 15))
    due = scheduler.due_tasks(clock, phase=Phase.MAIN)

    assert [task.task for task in due] == ["investor.trade"]


def test_callable_task_is_allowed():
    scheduler = Scheduler()

    def update_price():
        return "updated"

    scheduler.register(
        space="market",
        frequency=Frequency.DAILY,
        task=update_price,
    )

    clock = Clock(start_date=date(2026, 1, 15))
    due = scheduler.due_tasks(clock)

    assert len(due) == 1
    assert due[0].task is update_price