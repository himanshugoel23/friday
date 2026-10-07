from friday.core.events import Event, EventBus, TaskStatusChanged
from friday.core.models import TaskStatus


async def test_publish_reaches_subscribers_and_base_class_handlers(bus: EventBus):
    seen: list[str] = []

    async def specific(e: TaskStatusChanged) -> None:
        seen.append(f"specific:{e.new}")

    async def catch_all(e: Event) -> None:
        seen.append("all")

    bus.subscribe(TaskStatusChanged, specific)
    bus.subscribe(Event, catch_all)
    await bus.publish(TaskStatusChanged(task_id="t", user_id="u", old=None, new=TaskStatus.CALLING))
    assert sorted(seen) == ["all", "specific:calling"]


async def test_failing_handler_does_not_break_others(bus: EventBus):
    seen: list[int] = []

    async def boom(e: Event) -> None:
        raise RuntimeError("boom")

    async def ok(e: Event) -> None:
        seen.append(1)

    bus.subscribe(Event, boom)
    bus.subscribe(Event, ok)
    await bus.publish(Event())
    assert seen == [1]


async def test_unsubscribe(bus: EventBus):
    seen: list[int] = []

    async def h(e: Event) -> None:
        seen.append(1)

    bus.subscribe(Event, h)
    bus.unsubscribe(Event, h)
    await bus.publish(Event())
    assert seen == []
