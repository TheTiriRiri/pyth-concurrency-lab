"""Pitfall 06 — asyncio.gather vs asyncio.TaskGroup (3.11+).

When one task raises, gather keeps the other tasks running (unless
return_exceptions=False, in which case it re-raises the first error but does
NOT cancel siblings — they run to completion, their results are lost).

TaskGroup, introduced in 3.11, cancels all siblings on the first failure and
raises an ExceptionGroup aggregating every exception raised inside the group.

Run on Python ≥ 3.11.
"""
import asyncio


async def ok(i: int) -> str:
    await asyncio.sleep(0.1)
    return f"ok-{i}"


async def boom(i: int) -> None:
    await asyncio.sleep(0.05)
    raise RuntimeError(f"boom-{i}")


async def gather_demo() -> None:
    print("--- asyncio.gather(return_exceptions=False) ---")
    try:
        results = await asyncio.gather(ok(1), boom(2), ok(3))
        print(f"results: {results}")
    except Exception as exc:
        print(f"caught: {type(exc).__name__}: {exc}")
        # Siblings were NOT cancelled; they completed in the background. We lost their results.

    print("\n--- asyncio.gather(return_exceptions=True) ---")
    results = await asyncio.gather(ok(1), boom(2), ok(3), return_exceptions=True)
    print(f"results: {results}")


async def taskgroup_demo() -> None:
    print("\n--- asyncio.TaskGroup ---")
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(ok(1))
            tg.create_task(boom(2))
            tg.create_task(ok(3))
    except* RuntimeError as eg:  # noqa: E999 — except* is 3.11+
        print(f"caught ExceptionGroup with {len(eg.exceptions)} exception(s):")
        for exc in eg.exceptions:
            print(f"  - {type(exc).__name__}: {exc}")


async def main() -> None:
    await gather_demo()
    await taskgroup_demo()
    print(
        "\nTakeaway:\n"
        "  gather: errors don't cancel siblings; return_exceptions=True is a blunt hammer.\n"
        "  TaskGroup: structured concurrency — siblings cancel on failure, errors aggregate."
    )


if __name__ == "__main__":
    asyncio.run(main())
