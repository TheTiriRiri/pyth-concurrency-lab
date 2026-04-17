"""Pitfall 02 BROKEN — deadlock from inconsistent lock order.

Two threads acquire locks in opposite order. Both can block waiting on the
other, causing a deadlock. A threading.Timer watchdog detects the hang and
exits cleanly so the demo does not require Ctrl+C.

Why not signal.alarm? SIGALRM handlers run in the main thread between bytecode
instructions. A thread stuck inside lock.acquire() never yields, so the handler
never fires. threading.Timer + os._exit is the mechanism that works.
"""
import argparse
import os
import sys
import threading
import time

lock_a = threading.Lock()
lock_b = threading.Lock()


def worker_ab(label: str) -> None:
    with lock_a:
        print(f"[{label}] holding A, requesting B...")
        time.sleep(0.1)  # ensure the other thread has time to grab B
        with lock_b:
            print(f"[{label}] got B (should never reach here)")


def worker_ba(label: str) -> None:
    with lock_b:
        print(f"[{label}] holding B, requesting A...")
        time.sleep(0.1)
        with lock_a:
            print(f"[{label}] got A (should never reach here)")


def watchdog(timeout: float) -> None:
    print(f"🔒 DEADLOCK CAUGHT after {timeout:.1f}s — as expected.")
    print("    Both threads are blocked waiting on each other.")
    sys.stdout.flush()
    os._exit(0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    timer = threading.Timer(args.timeout, watchdog, args=(args.timeout,))
    timer.daemon = True
    timer.start()

    t1 = threading.Thread(target=worker_ab, args=("T1",))
    t2 = threading.Thread(target=worker_ba, args=("T2",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    timer.cancel()
    print("no deadlock — lucky scheduling?")


if __name__ == "__main__":
    main()
