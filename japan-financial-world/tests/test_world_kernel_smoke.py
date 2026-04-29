from datetime import date

from world.clock import Clock
from world.kernel import WorldKernel
from world.ledger import Ledger
from world.loader import load_world_yaml
from world.registry import Registry
from world.scheduler import Frequency, Scheduler, TaskSpec
from world.state import State


def test_empty_world_kernel_runs_for_one_year(tmp_path):
    yaml_path = tmp_path / "minimal_world.yaml"
    yaml_path.write_text(
        """
agents:
  - id: agent:dummy_firm
    type: firm
    space: corporate
    attributes:
      name: Dummy Firm

assets:
  - id: asset:dummy_asset
    type: generic_asset
    space: market
    attributes:
      name: Dummy Asset

markets:
  - id: market:dummy_market
    type: generic_market
    space: market
    attributes:
      currency: JPY
""".strip(),
        encoding="utf-8",
    )

    kernel = WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 1, 1)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )

    spec = load_world_yaml(yaml_path)
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

    kernel.run(days=365)

    assert "agent:dummy_firm" in kernel.registry
    assert "asset:dummy_asset" in kernel.registry
    assert "market:dummy_market" in kernel.registry

    assert len(kernel.ledger.filter(event_type="object_registered")) == 3

    daily_records = kernel.ledger.filter(
        event_type="task_executed",
        task_id="task:daily_noop",
    )
    assert len(daily_records) == 365

    quarterly_records = kernel.ledger.filter(
        event_type="task_executed",
        task_id="task:quarterly_noop",
    )
    assert len(quarterly_records) == 4
    assert [record.simulation_date for record in quarterly_records] == [
        "2026-03-31",
        "2026-06-30",
        "2026-09-30",
        "2026-12-31",
    ]

    snapshot_records = kernel.ledger.filter(event_type="state_snapshot_created")
    assert len(snapshot_records) == 12

    assert kernel.clock.current_date == date(2027, 1, 1)
