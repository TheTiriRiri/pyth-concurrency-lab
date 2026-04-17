"""Pitfall 04 FIXED — two valid ways to unblock the loop.

(a) Replace the blocking call with its async equivalent (asyncio.sleep).
(b) If the blocking call is unavoidable (third-party library), push it to a
    thread with asyncio.to_thread.

Both recover the expected ~1s total runtime.
"""
import asyncio
import time


async def fixed_async_sleep(i: int) -> None:
    print(f"  [a/{i}] start")
    await asyncio.sleep(1)
    print(f"  [a/{i}] done")


async def fixed_to_thread(i: int) -> None:
    print(f"  [b/{i}] start")
    await asyncio.to_thread(time.sleep, 1)
    print(f"  [b/{i}] done")


async def run_variant(name: str, coro_factory) -> None:
    print(f"\n--- {name} ---")
    t = time.perf_counter()
    await asyncio.gather(*[coro_factory(i) for i in range(3)])
    print(f"elapsed: {time.perf_counter() - t:.2f}s")


async def main() -> None:
    await run_variant("(a) await asyncio.sleep", fixed_async_sleep)
    await run_variant("(b) await asyncio.to_thread(time.sleep, ...)", fixed_to_thread)


if __name__ == "__main__":
    asyncio.run(main())
