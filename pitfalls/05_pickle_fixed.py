"""Pitfall 05 FIXED — top-level functions pickle cleanly.

Module-level functions are addressable by `module.func_name` at import time,
which is all pickle needs to reconstruct the call on the worker side.
"""
from multiprocessing import Pool


def double(x: int) -> int:
    return x * 2


def main() -> None:
    with Pool(processes=2) as pool:
        results = pool.map(double, [1, 2, 3, 4, 5])
    print(f"results: {results}")
    assert results == [2, 4, 6, 8, 10]
    print("✅ top-level function pickled and executed in child processes")


if __name__ == "__main__":
    main()
