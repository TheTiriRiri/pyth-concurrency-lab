"""Pitfall 02 FIXED — consistent lock order.

Both threads always acquire lock_a before lock_b. No cyclic wait is possible,
so no deadlock can form.
"""
import threading
import time

lock_a = threading.Lock()
lock_b = threading.Lock()


def worker(label: str) -> None:
    with lock_a:
        print(f"[{label}] holding A, requesting B...")
        time.sleep(0.05)
        with lock_b:
            print(f"[{label}] got B, doing work")


def main() -> None:
    t1 = threading.Thread(target=worker, args=("T1",))
    t2 = threading.Thread(target=worker, args=("T2",))
    t1.start(); t2.start()
    t1.join(); t2.join()
    print("✅ no deadlock — both threads used the same lock order")


if __name__ == "__main__":
    main()
