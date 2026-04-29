from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable

from world.clock import Clock


class Frequency(str, Enum):
    DAILY = "daily"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class Phase(str, Enum):
    """
    Placeholder for future intraday / intra-period phase control.

    For now, MAIN is enough.
    Later examples:
    - PRE_MARKET
    - MARKET
    - POST_MARKET
    - SETTLEMENT
    """

    MAIN = "main"


TaskCallable = Callable[..., Any]
TaskBody = TaskCallable | str


@dataclass(frozen=True)
class TaskSpec:
    id: str
    frequency: Frequency
    name: str
    target_id: str | None = None
    action: Callable[[Any], None] | None = None
    space: str = "world"
    order: int = 0
    phase: Phase = Phase.MAIN


@dataclass(frozen=True)
class ScheduledTask:
    """
    A scheduled task registered to the world scheduler.

    The scheduler does not interpret the task body.
    The task body may be:
    - a callable
    - a string placeholder
    - later, a command object or event reference
    """

    space: str
    frequency: Frequency
    task: TaskBody
    name: str | None = None
    order: int = 0
    phase: Phase = Phase.MAIN
    id: str | None = None
    target_id: str | None = None

    def display_name(self) -> str:
        if self.name is not None:
            return self.name

        if isinstance(self.task, str):
            return self.task

        return getattr(self.task, "__name__", repr(self.task))


@dataclass
class Scheduler:
    """
    Date-based task scheduler for the world simulation.

    Responsibility:
    - Register tasks by frequency, space, phase, and order.
    - Return tasks that are due on the current clock date.
    - Preserve deterministic execution order.

    It must not:
    - decide what agents do
    - mutate spaces
    - contain scenario-specific logic
    - inspect corporate/banking/investor internals
    """

    _tasks: list[ScheduledTask] = field(default_factory=list)
    _task_ids: set[str] = field(default_factory=set)

    def register(
        self,
        task_spec: TaskSpec | None = None,
        /,
        *,
        space: str | None = None,
        frequency: Frequency | str | None = None,
        task: TaskBody | None = None,
        name: str | None = None,
        order: int = 0,
        phase: Phase | str = Phase.MAIN,
    ) -> ScheduledTask:
        if task_spec is not None:
            if task_spec.id in self._task_ids:
                raise ValueError(f"Duplicate task id: {task_spec.id}")
            self._task_ids.add(task_spec.id)
            scheduled_task = ScheduledTask(
                space=task_spec.space,
                frequency=Frequency(task_spec.frequency),
                task=task_spec.action or task_spec.id,
                name=task_spec.name,
                order=task_spec.order,
                phase=Phase(task_spec.phase),
                id=task_spec.id,
                target_id=task_spec.target_id,
            )
            self._tasks.append(scheduled_task)
            return scheduled_task

        if space is None or frequency is None or task is None:
            raise TypeError("space, frequency, and task are required")

        frequency = Frequency(frequency)
        phase = Phase(phase)

        scheduled_task = ScheduledTask(
            space=space,
            frequency=frequency,
            task=task,
            name=name,
            order=order,
            phase=phase,
            id=None,
            target_id=None,
        )

        self._tasks.append(scheduled_task)
        return scheduled_task

    def all_tasks(self) -> tuple[ScheduledTask, ...]:
        return tuple(self._sorted_tasks(self._tasks))

    def due_tasks(
        self,
        clock: Clock,
        *,
        phase: Phase | str | None = None,
        space: str | None = None,
    ) -> tuple[ScheduledTask, ...]:
        if phase is not None:
            phase = Phase(phase)

        due_frequencies = self._due_frequencies(clock)

        tasks = [
            task
            for task in self._tasks
            if task.frequency in due_frequencies
            and (phase is None or task.phase == phase)
            and (space is None or task.space == space)
        ]

        return tuple(self._sorted_tasks(tasks))

    def _due_frequencies(self, clock: Clock) -> set[Frequency]:
        due = {Frequency.DAILY}

        if clock.is_month_end():
            due.add(Frequency.MONTHLY)

        if clock.is_quarter_end():
            due.add(Frequency.QUARTERLY)

        if clock.is_year_end():
            due.add(Frequency.YEARLY)

        return due

    def _sorted_tasks(
        self,
        tasks: Iterable[ScheduledTask],
    ) -> list[ScheduledTask]:
        frequency_rank = {
            Frequency.DAILY: 10,
            Frequency.MONTHLY: 20,
            Frequency.QUARTERLY: 30,
            Frequency.YEARLY: 40,
        }

        phase_rank = {
            Phase.MAIN: 100,
        }

        return sorted(
            tasks,
            key=lambda task: (
                phase_rank[task.phase],
                frequency_rank[task.frequency],
                task.order,
                task.space,
                task.display_name(),
            ),
        )
