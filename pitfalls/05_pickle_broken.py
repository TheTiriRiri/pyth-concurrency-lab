"""Pitfall 05 BROKEN — multiprocessing cannot pickle lambdas or local functions.

multiprocessing.Pool serialises the target function to send it to worker
processes. Lambdas and nested functions cannot be pickled, so this script
raises PicklingError before any work runs.
"""
from multiprocessing import Pool


def main() -> None:
    # Nested function — also unpicklable.
    def local_double(x: int) -> int:
        return x * 2

    print("Attempting Pool.map with a nested function...")
    try:
        with Pool(processes=2) as pool:
            results = pool.map(local_double, [1, 2, 3])
        print(f"results: {results}  (unexpected — should have raised)")
    except Exception as exc:
        print(f"❌ {type(exc).__name__}: {exc}")

    print("\nAttempting Pool.map with a lambda...")
    try:
        with Pool(processes=2) as pool:
            results = pool.map(lambda x: x * 2, [1, 2, 3])
        print(f"results: {results}")
    except Exception as exc:
        print(f"❌ {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
