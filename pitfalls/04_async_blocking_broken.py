"""Pitfall 04 BROKEN — blocking call inside an async function freezes the loop.

Three tasks each "sleep" 1 second. With non-blocking awaits they would complete
in ~1s total. With time.sleep (which does NOT yield control) they complete in
~3s — the event loop is blocked during each call.
"""
import asyncio
import time


async def bad_task(i: int) -> None:
    print(f"  [{i}] start")
    time.sleep(1)  # 🚨 blocks the event loop
    print(f"  [{i}] done")


async def main() -> None:
    t = time.perf_counter()
    await asyncio.gather(*[bad_task(i) for i in range(3)])
    elapsed = time.perf_counter() - t
    print(f"\nelapsed: {elapsed:.2f}s")
    print("Expected ~1s if tasks ran concurrently. ~3s means the loop was blocked.")


if __name__ == "__main__":
    asyncio.run(main())
