"""Pitfall 03 — the GIL made visible.

Same CPU-bound workload, three ways: sequential, threading(2), threading(4).
If the GIL really blocks parallel Python execution, the threaded runs should
be no faster than sequential (and often slower, due to context-switch overhead).

This is not a broken/fixed pair — the GIL is the lesson itself. The "fix" for
CPU-bound work is multiprocessing (see experiments/01 and 04).
"""
import time
from concurrent.futures import ThreadPoolExecutor

LIMIT = 2_000_000
N_TASKS = 4


def count_primes(limit: int) -> int:
    n = 0
    for i in range(2, limit + 1):
        is_prime = i > 1
        j = 2
        while j * j <= i:
            if i % j == 0:
                is_prime = False
                break
            j += 1
        if is_prime:
            n += 1
    return n


def run(name: str, fn):
    t = time.perf_counter()
    fn()
    elapsed = time.perf_counter() - t
    print(f"  {name:<18} {elapsed:6.2f}s")


def main() -> None:
    print("Same CPU workload, 4 tasks:")
    run("sequential", lambda: [count_primes(LIMIT) for _ in range(N_TASKS)])
    for workers in (2, 4, 8):
        def _fn(w=workers):
            with ThreadPoolExecutor(max_workers=w) as pool:
                list(pool.map(count_primes, [LIMIT] * N_TASKS))
        run(f"threading({workers})", _fn)

    print(
        "\nObservation: threading times match (or exceed) sequential — this is the GIL.\n"
        "The CPython interpreter holds a single lock while executing bytecode, so\n"
        "Python-level CPU work cannot actually run in parallel across threads."
    )


if __name__ == "__main__":
    main()
