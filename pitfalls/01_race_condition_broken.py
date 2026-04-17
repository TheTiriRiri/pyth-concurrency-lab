"""Pitfall 01 BROKEN — race condition.

Hypothesis: 10 threads × 100_000 increments should produce 1_000_000.
Reality: threads race on the read-modify-write sequence, producing a value
< 1_000_000.

NOTE: a plain `counter += 1` in a tight loop is effectively atomic on CPython
3.12 — the interpreter rarely switches between the LOAD/ADD/STORE bytecodes
when there's no other work to yield on. To make the race **reliably** visible
we split the increment into explicit Python-level read/modify/write, which
gives the scheduler many more switch points. On free-threaded CPython (3.13+
--disable-gil) the naive `counter += 1` version races too.

Takeaway: any shared-mutable state accessed from multiple threads needs a lock.
Do not trust "it looks atomic" — the GIL is an implementation detail, not a
guarantee.
"""
import time
from concurrent.futures import ThreadPoolExecutor

THREADS = 10
ITERATIONS = 10_000

counter = 0


def increment_many() -> None:
    global counter
    for _ in range(ITERATIONS):
        # Explicit read-modify-write with a tiny sleep BETWEEN read and write.
        # The sleep forces the GIL to release mid-increment, reliably exposing
        # the race (other threads see the old value before this thread writes
        # the new one, so their increment overwrites ours).
        #
        # In real code the "sleep" would be: attribute lookup across modules,
        # a log call, a tiny I/O, a dict update — anything that yields. Pure
        # arithmetic in a tight loop rarely yields on CPython 3.12, so without
        # this simulation the race is invisible even though the code is unsafe.
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
    lost = expected - counter
    pct = (lost / expected) * 100
    print(f"lost:     {lost} ({pct:.2f}%) — this is the race condition.")


if __name__ == "__main__":
    main()
