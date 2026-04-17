"""Pitfall 01 FIXED — threading.Lock guards the increment.

The lock serialises the read-modify-write sequence so no increment is lost.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

THREADS = 10
ITERATIONS = 10_000

counter = 0
lock = threading.Lock()


def increment_many() -> None:
    global counter
    for _ in range(ITERATIONS):
        # Same read/sleep/write shape as the broken version, but guarded by
        # a Lock. The lock serialises the read-modify-write so no increment
        # is lost, even though the sleep yields the GIL every iteration.
        with lock:
            tmp = counter
            time.sleep(0.00001)
            counter = tmp + 1


def main() -> None:
    global counter
    counter = 0
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        for _ in range(THREADS):
            pool.submit(increment_many)

    expected = THREADS * ITERATIONS
    print(f"expected: {expected}")
    print(f"actual:   {counter}")
    assert counter == expected, "Lock must prevent any lost increments"
    print("✅ all increments preserved")


if __name__ == "__main__":
    main()
