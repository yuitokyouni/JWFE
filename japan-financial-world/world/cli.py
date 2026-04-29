from __future__ import annotations

import argparse
from datetime import date

from world.clock import Clock
from world.kernel import WorldKernel
from world.ledger import Ledger
from world.loader import load_world_yaml
from world.registry import Registry
from world.scheduler import Frequency, Scheduler, TaskSpec
from world.state import State


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run empty world kernel simulation")
    parser.add_argument("--world", required=True, help="Path to world YAML file")
    parser.add_argument("--start", default="2026-01-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=365, help="Number of days to run")
    return parser.parse_args()


def build_kernel(start: date) -> WorldKernel:
    return WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=start),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )


def main() -> None:
    args = parse_args()
    kernel = build_kernel(date.fromisoformat(args.start))

    spec = load_world_yaml(args.world)
    for obj in spec.objects:
        kernel.register_object(obj)

    kernel.register_task(
        TaskSpec(
            id="task:daily_noop",
            frequency=Frequency.DAILY,
            name="daily noop task",
        )
    )
    kernel.register_task(
        TaskSpec(
            id="task:quarterly_noop",
            frequency=Frequency.QUARTERLY,
            name="quarterly noop task",
        )
    )

    kernel.run(days=args.days)

    print("World run completed")
    print(f"Current date: {kernel.clock.current_date}")
    print(f"Objects: {len(kernel.registry.all())}")
    print(f"Ledger records: {len(kernel.ledger.records())}")
    print(f"Snapshots: {len(kernel.state.snapshots())}")


if __name__ == "__main__":
    main()
