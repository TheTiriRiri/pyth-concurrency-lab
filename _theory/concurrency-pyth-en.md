# Concurrency in Python: Threading vs Multiprocessing vs Asyncio

## The Problem: Python does one thing at a time by default

When you need to do many things "at once" (e.g., fetch 100 web pages, process 100 images), you have **three classical approaches** — plus one emerging fourth (free-threaded Python, see the end).

All three live under a common, unified API: [`concurrent.futures`](https://docs.python.org/3/library/concurrent.futures.html), which exposes `ThreadPoolExecutor` and `ProcessPoolExecutor` with the same interface. `asyncio` is a separate world, but integrates with both via `asyncio.to_thread()` and `loop.run_in_executor()`.

## Mental model: where is the work actually happening?

Every concurrency decision hinges on one question: **where does your program spend its wall-clock time?**

| Work type   | Time spent in…                                    | Bottleneck                 | Tool              |
| ----------- | ------------------------------------------------- | -------------------------- | ----------------- |
| I/O-bound   | Kernel syscalls, waiting for sockets/disk         | Latency, concurrent file descriptors | threading, asyncio |
| CPU-bound   | Python bytecode, NumPy kernels, regex, JSON parse | GIL serializes bytecode    | multiprocessing   |
| Mixed       | Both, often in the same task                      | Whichever dominates        | asyncio + ProcessPool |

If your hot path releases the GIL (NumPy BLAS, I/O syscalls, hashlib, zlib, most C extensions), threading behaves almost like true parallelism. If it doesn't (pure-Python loops, dict/list manipulation), only processes scale.

---

## 1. Multithreading (`threading`)

**What it is:** Multiple threads in a single process. Threads share the same memory.

```python
from concurrent.futures import ThreadPoolExecutor
import httpx

urls = ["http://a.com", "http://b.com", "http://c.com"]

# Reuse a single client — connection pooling, one TLS handshake per host.
with httpx.Client(timeout=10.0) as client:
    def fetch(url: str) -> str:
        return client.get(url).text  # blocks on the network

    # max_workers=3 here is just for the demo; the library default is
    # min(32, os.cpu_count() + 4), which is usually the right starting point for I/O.
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(fetch, urls))
```

### Analogy
> One cook (CPU) with three burners. Puts a pot on one, waits for it to boil → jumps to the next one. Doesn't cook faster, but doesn't waste time waiting.

### The key thing — GIL (Global Interpreter Lock)
Python's lock that ensures **only one thread executes Python bytecode** at any given moment on the classic CPython build. Threads switch (the interpreter preempts every ~5 ms), but they don't actually run in parallel on CPU-bound Python code.

> **2026 note:** Since Python 3.13, a free-threaded build exists (PEP 703, `--disable-gil`). See the final section.

### ✅ Pros
- Simple — same API as synchronous code, just parallel
- Great when the program is waiting (network, disk, database) — **I/O-bound**
- Shared memory — easy (but dangerous) communication between threads
- `concurrent.futures.ThreadPoolExecutor` is production-grade out of the box
- Scales to low hundreds of workers for I/O without problem

### ❌ Cons
- GIL blocks true parallelism on CPU-bound Python code
- **Race conditions** — two threads modifying the same object concurrently; preemption can happen between any two bytecodes
- Hard to debug — non-deterministic interleaving
- Synchronization primitives required (`threading.Lock`, `queue.Queue`, `threading.Event`)

### 🎯 When to use
Many I/O operations, **dozens to low hundreds** of concurrent tasks: fetching pages, database queries, file reads. A sensible default when the workload is blocking and you don't want to rewrite everything as `async`.

---

## 2. Multiprocessing (`multiprocessing`)

**What it is:** Multiple separate processes, each with its own Python interpreter and its own memory. **Bypasses the GIL.**

```python
from concurrent.futures import ProcessPoolExecutor

def heavy_compute(n: int) -> int:
    return sum(i * i for i in range(n))  # CPU-heavy

# CRITICAL on Windows / macOS (spawn start method):
# without this guard, child processes will re-import the module and
# recursively spawn more processes — RuntimeError.
if __name__ == "__main__":
    data = [10_000_000, 20_000_000, 30_000_000]

    with ProcessPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(heavy_compute, data))
```

### Analogy
> Three separate cooks, each with their own kitchen. They **actually** cook simultaneously. But to share ingredients, they have to package them up and carry them between kitchens.

### ✅ Pros
- **True parallelism** — uses multiple CPU cores
- Bypasses the GIL
- Isolation — a crash in one process doesn't kill the rest
- Same `concurrent.futures` API as threads — swap one line to switch

### ❌ Cons
- Spawn overhead depends on start method:
  - `fork` (legacy Linux default): ~1–10 ms, but **unsafe when mixed with threads**. Emits `DeprecationWarning` since 3.12; Linux default switches away from it in 3.14+
  - `spawn` (Windows/macOS default, and a safe explicit choice everywhere): 50–500 ms, each process re-imports modules
  - `forkserver` (becoming the Linux default): middle ground, recommended for any code that mixes threads with process pools
- IPC is expensive — arguments and return values must be **pickled** and copied in both directions
- Not every object is picklable (lambdas, local functions, open file handles, DB connections)
- Rarely the right tool for pure I/O — concurrency is capped by `cpu_count()` and overhead adds up
- Requires the `if __name__ == "__main__"` guard on Windows/macOS (and anywhere using `spawn`)
- Logging needs explicit setup per process — typically `QueueHandler` + a single listener thread in the parent
- Default `max_workers = os.cpu_count()`
- Tip: for zero-copy IPC with NumPy arrays/tensors, see `multiprocessing.shared_memory` (3.8+)

### 🎯 When to use
CPU-bound work: image processing, NumPy/pandas pipelines, ML feature extraction, cryptography, parsing, compilation. Also viable for **mixed workloads** where each unit of work is both heavy and does some I/O.

In the data-science ecosystem, **`joblib`** (built on `loky`) is the de-facto wrapper — more robust pickling (cloudpickle) and saner semaphore management than stock `multiprocessing`.

---

## 3. Asyncio (`asyncio`)

**What it is:** A single thread with an event loop. Code explicitly yields at `await` points so the loop can run something else in the meantime. Built on `async`/`await`.

```python
import asyncio
import httpx

async def fetch(client: httpx.AsyncClient, url: str) -> str:
    response = await client.get(url)  # yields to the event loop
    return response.text

async def main() -> list[str]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        # TaskGroup (Python 3.11+) — preferred over asyncio.gather:
        # if one task raises, siblings are cancelled cleanly (ExceptionGroup).
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(fetch(client, url)) for url in urls]
        # All tasks are guaranteed done here; safe to read .result().
        return [t.result() for t in tasks]

results = asyncio.run(main())
```

> **Tip:** for long-running services that spin up the loop once, prefer `asyncio.Runner()` (3.11+) — it gives you an explicit lifecycle, a stable `ContextVar` context across `run()` calls, and cleaner shutdown than repeatedly calling `asyncio.run`.

### Producer/consumer with `asyncio.Queue`

The canonical backpressure pattern — a bounded queue between a fan-out producer and a fixed-size worker pool. This composes better than ad-hoc `gather` + `Semaphore` once the pipeline has more than one stage.

```python
async def producer(queue: asyncio.Queue[str], urls: list[str]) -> None:
    for url in urls:
        await queue.put(url)  # blocks when queue is full — natural backpressure
    for _ in range(N_WORKERS):
        await queue.put(None)  # sentinel per worker

async def worker(queue: asyncio.Queue[str], client: httpx.AsyncClient) -> None:
    while (url := await queue.get()) is not None:
        try:
            await client.get(url, timeout=10)
        finally:
            queue.task_done()

async def main(urls: list[str]) -> None:
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=200)
    async with httpx.AsyncClient() as client, asyncio.TaskGroup() as tg:
        tg.create_task(producer(queue, urls))
        for _ in range(N_WORKERS):
            tg.create_task(worker(queue, client))
```

### Bridging to sync code

Asyncio is single-threaded, so one blocking call freezes **everything**. Use `asyncio.to_thread()` (3.9+) for blocking I/O and `run_in_executor()` with a `ProcessPoolExecutor` for CPU work:

```python
from pathlib import Path

# Blocking I/O from async context — offload to a thread.
# Pass a callable — DO NOT call it eagerly (a common bug).
data = await asyncio.to_thread(Path("big.log").read_text)

# CPU-bound work from async context — offload to a process:
loop = asyncio.get_running_loop()
result = await loop.run_in_executor(process_pool, heavy_compute, 10_000_000)
```

### Timeouts, cancellation, and backpressure

Three things that bite every real asyncio codebase:

```python
# Timeouts (3.11+): cancels the block on expiry, raises TimeoutError.
async with asyncio.timeout(5):
    await fetch(client, url)

# Backpressure: 10_000 tasks = 10_000 open sockets. Bound concurrency.
sem = asyncio.Semaphore(100)
async def fetch_bounded(url: str) -> str:
    async with sem:
        return await fetch(client, url)

# Cancellation is part of the contract: never catch bare `except Exception`
# without re-raising CancelledError.
try:
    await something()
except asyncio.CancelledError:
    # cleanup, then:
    raise
except Exception:
    ...
```

### Analogy
> One cook, but **super organized**. Puts a pot on, immediately chops vegetables, immediately sets water to boil. Never stands idle. One cook does the work of three, because they don't waste a single second waiting.

### ✅ Pros
- **Most efficient for I/O** — tens of thousands of connections in a single thread
- Coroutines are tiny — ~2 KB each vs ~8 MB default stack per OS thread
- **No low-level races between bytecodes** — context switches only at `await` (but see Cons)
- Standard in modern Python (FastAPI, aiohttp, httpx, asyncpg, SQLAlchemy 2.x async)
- Structured concurrency via `TaskGroup` + `ExceptionGroup` is first-class since 3.11

### ❌ Cons
- **Viral / all-or-nothing** — once a function is `async`, every caller up the chain must be `async` (or use `asyncio.run`/`to_thread`)
- **Logical race conditions still exist** — between `await` points, another coroutine can mutate shared state. You may still need `asyncio.Lock`.
- Steeper learning curve (event loop, tasks, cancellation, exception groups)
- Useless for CPU-bound — a hot loop blocks the entire event loop
- Library ecosystem split — `requests` is sync, you need `httpx`/`aiohttp`; many DB drivers have separate sync/async variants

> **Alternatives:** `trio` (structured concurrency from day one) and `anyio` (portable abstraction over asyncio/trio) are worth knowing for library authors.

### 🎯 When to use
Massive network operations — APIs, websockets, web servers, scrapers with thousands of concurrent connections. Default choice for new network-heavy services.

---

## Deep dives

Three topics that the short form above glosses over but every expert must internalize. These are the most common production-grade footguns — skip on a first read if you're still getting comfortable with the basics.

### 1. Asyncio internals & the task-gc footgun

Under the hood, `asyncio` is a selector loop (epoll on Linux, kqueue on BSD/macOS, IOCP on Windows) driving a queue of callbacks. Key object hierarchy:

- **Coroutine** — a suspended function, built from `async def`. Inert until awaited or wrapped in a Task. Has no scheduling on its own.
- **Future** — low-level placeholder for a result. Set by the loop or by foreign code (e.g. `run_coroutine_threadsafe`).
- **Task** — a `Future` that *drives* a coroutine. Created by `asyncio.create_task()` / `TaskGroup.create_task()`. Schedules itself on the loop.

The loop runs callbacks until none are ready, then blocks in the selector until a file descriptor or timer fires. `call_soon` enqueues a callback for the next iteration; `call_later`/`call_at` schedule it on the loop's monotonic clock.

**The task-gc footgun.** This code has a bug:

```python
async def spawn_background_work():
    asyncio.create_task(do_something())  # ❌ return value discarded
```

`create_task` returns a Task, which the loop holds **weakly**. If nothing else keeps a strong reference, the garbage collector can (and eventually will) collect the Task *mid-flight*, cancelling it silently with a cryptic "Task was destroyed but it is pending!" warning on stderr. Fix:

```python
_background_tasks: set[asyncio.Task] = set()

def spawn(coro):
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task
```

Better: use `TaskGroup` so the lifetime is explicit and bounded. If you find yourself maintaining a `set` of background tasks, that's usually a smell — your concurrency is unstructured.

**`contextvars`** (PEP 567) is the async-native replacement for thread-local storage. Each task gets a copy of the calling context at creation time — critical for request-scoped state (user ID, trace ID, DB transaction) in async web frameworks.

### 2. Cancellation: the contract everyone gets wrong

Cancellation is **cooperative** and **exception-based** in asyncio. `task.cancel()` schedules a `CancelledError` to be raised at the next `await` point inside the coroutine. Since Python 3.8, `CancelledError` inherits from `BaseException`, *not* `Exception` — specifically so naive handlers don't swallow it:

```python
try:
    await something()
except Exception:  # ✅ doesn't catch CancelledError — good
    log_and_continue()
```

The three rules:

1. **Never swallow `CancelledError` without re-raising.** If you must do cleanup, do it, then `raise`. Otherwise the cancellation is lost and whoever called you waits forever.
2. **Shielding is a tool, not a default.** `await asyncio.shield(critical_cleanup())` protects the inner coroutine from outer cancellation, but the outer cancellation still propagates to the shield itself — so you need `try/finally` discipline around it.
3. **TaskGroups cancel siblings on first failure.** If task A raises, the group cancels B, C, D and aggregates everything into an `ExceptionGroup` (PEP 654). Use `except* SomeError:` to handle specific branches.

**Graceful shutdown** is where cancellation meets the real world: SIGTERM → loop receives the signal → all tasks cancelled → pending I/O drains → process exits. Template:

```python
async def main():
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    async def server_with_shutdown():
        # serve() should cooperatively watch `stop` and return cleanly.
        server_task = asyncio.create_task(serve(stop))
        await stop.wait()
        server_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await server_task

    async with asyncio.TaskGroup() as tg:
        tg.create_task(server_with_shutdown())
```

Avoid `raise asyncio.CancelledError` inside a `TaskGroup` block: it's converted into a `BaseExceptionGroup` that leaks out of the `async with`. Prefer an explicit `Event` + cancel of the inner task, or return normally once `stop` is set.

This is the pattern behind `uvicorn --graceful-timeout`, Kubernetes preStop hooks, and basically every production async service.

### 3. When threads are parallel after all: GIL release in C extensions

The mantra "threads don't parallelize on CPU-bound Python" is true *for pure-Python bytecode*. The GIL is held by the interpreter eval loop — but any C extension can release it via `Py_BEGIN_ALLOW_THREADS` / `Py_END_ALLOW_THREADS` around code that doesn't touch Python objects.

Concretely, these release the GIL and **do** parallelize across threads:

| Operation                                        | GIL released | Why it matters                          |
| ------------------------------------------------ | ------------ | --------------------------------------- |
| `numpy` vectorized ops on large arrays (BLAS)    | yes          | threading scales linearly on matrix math |
| `numpy` ufuncs, FFT, linear algebra              | yes          | idem                                    |
| `hashlib` (sha256, blake2, …) on large buffers   | yes (≥ `HASHLIB_GIL_MINSIZE`, ~2 KB) | parallel hashing actually works        |
| `zlib`, `bz2`, `lzma` compress/decompress        | yes          | parallel compression                    |
| `sqlite3` queries (serialized mode)              | yes          | parallel DB work                        |
| File I/O (`read`/`write`), socket I/O            | yes          | why threading works for I/O            |
| `Pillow` image ops (most)                        | yes          | parallel image pipelines               |
| `lxml` parsing                                   | yes          | parallel XML                            |
| `cryptography` / OpenSSL primitives              | yes          | parallel TLS, AES, RSA                  |
| `pyarrow` compute kernels                        | yes          | parallel columnar ops                   |
| `re.match` / regex                               | **no**       | pure C but holds GIL                   |
| `json.loads` / `json.dumps`                      | **no**       | ditto                                   |
| Pure-Python `for` loop, dict/list manipulation   | **no**       | bytecode under GIL                     |

Practical consequence: a NumPy-heavy workload often does **not** need multiprocessing. Benchmark before reaching for processes — on an 8-core box, `ThreadPoolExecutor` + NumPy can match `ProcessPoolExecutor` with zero pickling overhead.

Beware of **copy-on-write breakage with `fork`**: CPython's refcount sits inside every object header, so even *reading* an object (which bumps refcount) dirties memory pages and defeats CoW. Pre-fork web workers (gunicorn) that expect to share a big model in-memory often end up with N copies anyway. PEP 683 (immortal objects, 3.12+) only helps for a narrow set of singletons — `None`, `True`/`False`, small ints, interned strings — not your module-level tuples, dicts, or loaded ML weights.

---

## Common pitfalls

| Pitfall | Symptom | Fix |
|---|---|---|
| `time.sleep(5)` inside a coroutine | Whole event loop frozen | `await asyncio.sleep(5)` |
| Forgetting `await` | Returns a coroutine object, no work done | Lint with `ruff`/`mypy`; `await` it |
| `asyncio.gather` + exception | Siblings keep running, cleanup skipped | Use `asyncio.TaskGroup` (3.11+) |
| Missing `if __name__ == "__main__":` | Infinite process spawn on Win/macOS | Add the guard |
| Pickling a lambda in `ProcessPoolExecutor` | `PicklingError` | Use a module-level function |
| Sharing a DB connection across processes | Corrupted state, locked handles | Open one per process |
| Mutating a dict from multiple threads | Silent data corruption | `threading.Lock` or `queue.Queue` |
| Blocking call in async code (e.g. `requests.get`) | Event loop stalls | `await asyncio.to_thread(...)` or switch to async client |
| Calling the function inside `asyncio.to_thread(fn())` | Runs on event loop anyway | Pass the callable: `to_thread(fn)` |
| Swallowing `CancelledError` with `except Exception` | Tasks can't be cancelled, hangs on shutdown | Catch and re-raise `CancelledError` |
| Unbounded `TaskGroup` / `gather` over N inputs | Socket/FD exhaustion, memory blowup | `asyncio.Semaphore(limit)` |
| Using `fork` start method with threads | Deadlocks, corrupted state | Use `forkserver` or `spawn` (`mp.get_context("forkserver")`) |
| Per-process logging collisions | Interleaved/lost log lines | `QueueHandler` in workers, one listener in parent |

---

## Summary

|                     | **Threading**                      | **Multiprocessing**   | **Asyncio**                 |
| ------------------- | ---------------------------------- | --------------------- | --------------------------- |
| **Parallelism**     | preemptive, GIL-serialized         | true parallel         | cooperative (single thread) |
| **Best for**        | I/O (dozens)                       | CPU-bound             | I/O (thousands+)            |
| **Overhead**        | medium (~8 MB/thread)              | high (~30–100 MB/proc) | tiny (~2 KB/coroutine)      |
| **Difficulty**      | medium                             | medium                | high                        |
| **Data races**      | yes                                | no shared state by default (races return if you opt into `shared_memory`/`Manager`) | no low-level; logical races at `await` points |
| **Memory model**    | shared                             | separate + IPC        | shared (single thread)      |
| **Unified API**     | `concurrent.futures`               | `concurrent.futures`  | `asyncio` + event loop      |

---

## Rough benchmark intuition

*Fetching 1000 URLs (~100 ms latency each), single machine:*

| Approach                     | Wall time | Notes                                  |
| ---------------------------- | --------- | -------------------------------------- |
| Sequential `requests`        | ~100 s    | Baseline                               |
| `ThreadPoolExecutor(50)`     | ~2–3 s    | Limited by thread count & memory       |
| `asyncio` + `httpx`          | ~1 s      | Scales to 10k+ connections trivially   |
| `ProcessPoolExecutor(8)`     | ~13 s     | Each of the 8 workers blocks sequentially on the network (1000 ÷ 8 × 0.1 s) because `requests` is synchronous; IPC adds on top — wrong tool for pure I/O |

*Numbers are illustrative — measure your own workload.*

---

## Decision tree

```
What do you have a lot of?
├── Waiting (network, disk, database) → I/O-bound
│   ├── Dozens of tasks           → threading
│   └── Hundreds / thousands      → asyncio
├── Mixed (I/O + CPU per item)    → asyncio + run_in_executor(ProcessPool)
└── Computation (math, ML, images) → CPU-bound
    └── multiprocessing (or free-threaded Python on 3.13+)
```

---

## 🆕 The future: two parallel tracks beyond the GIL

### Free-threaded Python (PEP 703)

Since **Python 3.13** there is an optional build without the GIL (`python3.13t`, flag `--disable-gil`). In this mode threads **actually** run Python code in parallel — `threading` becomes viable for CPU-bound work.

Status as of 2026:
- **Experimental**, opt-in. Single-threaded overhead was noticeable on 3.13 (10–40% on some workloads due to biased refcounting + disabled specialization); substantially improved on 3.14.
- C extension ecosystem is still catching up (NumPy, Pillow, lxml ship free-threaded wheels; long tail lags)
- Expected to become the default somewhere around Python 3.15–3.16

### Per-interpreter GIL / subinterpreters (PEP 684, PEP 734)

Since **Python 3.12** each subinterpreter has its own GIL, and 3.13+ exposes a Python-level API. Python **3.14** adds `concurrent.futures.InterpreterPoolExecutor` — a drop-in cousin of `ProcessPoolExecutor` but with process-like isolation at thread-like cost (no fork, no full interpreter bootstrap).

It's a third point on the design space:

|                        | Threads | Subinterpreters | Processes |
| ---------------------- | ------- | --------------- | --------- |
| True parallelism (GIL) | no (until 3.13t) | yes             | yes       |
| Memory sharing         | full    | none (by design) | none     |
| Startup cost           | µs      | ms              | tens–hundreds of ms |
| Data transfer          | direct  | channels / pickle | pickle + IPC |

For production today: assume the GIL exists. But know both escape hatches are maturing fast.

---

## 💬 In a job interview

> "Threading and asyncio solve the **I/O-bound** problem — threading is simpler and integrates with blocking libraries, asyncio is more efficient at scale and is the modern default for network services. Multiprocessing solves **CPU-bound**, because it bypasses the GIL and gives you true parallelism — at the cost of IPC overhead and pickling constraints.
>
> In practice: **FastAPI = asyncio**, **data processing = multiprocessing**, **simple scraping scripts = threading**. And mixed workloads are usually asyncio with a `ProcessPoolExecutor` hanging off `run_in_executor` for the hot path.
>
> Looking forward, free-threaded Python (PEP 703, 3.13+) will eventually make threading competitive for CPU-bound work too — but that's not production-ready yet."

---

## Mixed workload: asyncio + ProcessPool end-to-end

The real-world pattern: fetch many pages concurrently (I/O), then run an expensive pure-Python transformation on each (CPU). Single tool is wrong for both halves — combine them.

```python
import asyncio
from concurrent.futures import ProcessPoolExecutor
import httpx

def extract_features(html: str) -> dict:
    # Pretend this is heavy: tokenize, parse, regex, whatever.
    return {"len": len(html), "words": len(html.split())}

async def process(url: str, client: httpx.AsyncClient,
                  pool: ProcessPoolExecutor, sem: asyncio.Semaphore) -> dict:
    async with sem:  # backpressure on network concurrency
        r = await client.get(url, timeout=10)
    loop = asyncio.get_running_loop()
    # CPU hot path offloaded to a separate process — event loop stays free.
    return await loop.run_in_executor(pool, extract_features, r.text)

async def main(urls: list[str]) -> list[dict]:
    sem = asyncio.Semaphore(100)
    with ProcessPoolExecutor() as pool:  # defaults to os.cpu_count()
        async with httpx.AsyncClient() as client:
            async with asyncio.TaskGroup() as tg:
                tasks = [tg.create_task(process(url, client, pool, sem))
                         for url in urls]
            return [t.result() for t in tasks]

if __name__ == "__main__":
    asyncio.run(main([...]))
```

Key points: `asyncio` owns the I/O and orchestration; `ProcessPoolExecutor` owns the cores; `Semaphore` bounds the fan-out; `TaskGroup` gives structured cancellation. This composition scales from one box to a production ingest pipeline.

---

## Path to expertise: topics to master

The three sections above are the core. What separates "knows concurrency" from "runs production concurrent systems" is the list below. Treat it as a curriculum — each bullet is roughly one afternoon of reading + experimentation.

### Foundations

- **Python memory model & atomicity** — which bytecodes are atomic (`a = b`, `d[k] = v` on a built-in dict) and which aren't (`a += 1`, `d.setdefault` in older versions). The switch interval (`sys.setswitchinterval`, default 5 ms) preempts between bytecodes, not inside them.
- **Synchronization primitives in depth** — `Lock` vs `RLock` (reentrancy), `Semaphore` vs `BoundedSemaphore`, `Event`, `Condition`, `Barrier`. Lock ordering to prevent deadlocks. **Prefer `queue.Queue` over explicit locks** — it's the canonical thread-safe message-passing primitive.
- **Structured concurrency as a paradigm** — why `trio` exists (nurseries, cancel scopes), why "fire and forget" is an antipattern, Rob Pike's "concurrency is not parallelism".
- **Async generators & context managers** — `async for`, `async with`, `@asynccontextmanager`, `aclose()` semantics, why async-generator cleanup was buggy pre-3.10.

### Runtime behavior

- **Event loop internals** — selectors (epoll/kqueue/IOCP), `call_soon` vs `call_later` vs `call_at`, why `time.sleep` blocks everything, the single-thread invariant.
- **`contextvars` (PEP 567)** — async-native replacement for `threading.local`. Each Task inherits a context snapshot. Critical for request-scoped state (trace IDs, auth, DB transactions) in ASGI frameworks.
- **Signals + threads + async** — only the main thread handles signals; `loop.add_signal_handler` is the async-safe API; graceful shutdown in containers (SIGTERM → drain → exit).
- **Interop: sync ↔ async** — `asyncio.run_coroutine_threadsafe`, `loop.call_soon_threadsafe`, `janus.Queue` for thread-async bridging. `nest_asyncio` exists but is usually a smell — investigate the real architectural problem.

### Production skills

- **Observability for concurrency** — `PYTHONASYNCIODEBUG=1`, `loop.slow_callback_duration`, `faulthandler` for deadlock diagnosis, `py-spy` (sampling profiler, sees async stacks without instrumentation), OpenTelemetry async context propagation.
- **Performance measurement** — latency vs throughput, tail percentiles (p95/p99), head-of-line blocking, why `asyncio.gather(*10_000)` is slower than a bounded worker pool.
- **Pool sizing & Little's Law** — `N_workers = throughput × latency`. For I/O, size by desired concurrency and bandwidth-delay product; for CPU, by physical cores. Mind `ulimit -n` (file descriptors) and kernel connection limits.
- **Backpressure patterns** — bounded queues (`asyncio.Queue(maxsize=N)`), token-bucket rate limiting, circuit breakers (`pybreaker`), timeouts everywhere as a hard rule.
- **Thread safety in libraries** — read the docs carefully. Most DB drivers: connection not thread-safe, cursor even less so. `requests.Session` is almost-but-not-quite safe. SQLAlchemy session scoping. HTTP clients with connection pools are generally safe; ORMs rarely are.
- **Testing concurrent code** — `pytest-asyncio`, `anyio.pytest-plugin`, why concurrent tests are flaky, `hypothesis` stateful testing, deterministic schedulers (`trio.testing`).

### Framework & ecosystem

- **ASGI vs WSGI** — lifecycle differences, why FastAPI/Starlette vs Flask/Django-sync, gunicorn + uvicorn workers, async SQLAlchemy, `asyncpg` vs `psycopg3` async.
- **`uvloop`** — drop-in event loop replacement, 2–4× faster than the stdlib selector loop. Default in most production async stacks.
- **Alternative runtimes** — `trio` for new projects that can commit to it, `anyio` for libraries that want to support both. Understand when the stdlib asyncio is the right choice anyway (ecosystem).
- **Distributed concurrency** — when single-node isn't enough: `celery`, `dramatiq`, `arq` (async-native), `ray` for ML/compute, `dask` for data. Know when to cross the network and when it's overkill.

### CPython internals & history

- **How the GIL works** — `ceval.c`, `take_gil`/`drop_gil`, the switch interval, why naive refcounting made the GIL hard to remove.
- **PEP 703 mechanics** — biased reference counting, deferred RC, immortal objects (PEP 683), why specialization is initially disabled in free-threaded builds.
- **PEP 684/734** — per-interpreter GIL, memory isolation model, cross-interpreter channels.
- **Historical attempts** — Stackless, Gilectomy (Larry Hastings), Jython/IronPython (no GIL by virtue of JVM/CLR), PyPy STM. Understanding why they failed explains why PEP 703 is the way it is.

---

## Further reading

- [`asyncio`](https://docs.python.org/3/library/asyncio.html) — official docs
- [`concurrent.futures`](https://docs.python.org/3/library/concurrent.futures.html) — unified thread/process API
- [`multiprocessing`](https://docs.python.org/3/library/multiprocessing.html) — and its programming guidelines
- [PEP 703 — Making the GIL optional](https://peps.python.org/pep-0703/)
- [PEP 684 — Per-interpreter GIL](https://peps.python.org/pep-0684/) / [PEP 734 — Multiple interpreters in stdlib](https://peps.python.org/pep-0734/)
- [`trio`](https://trio.readthedocs.io/) / [`anyio`](https://anyio.readthedocs.io/) — alternative / portable async runtimes (structured concurrency as the primary model)
- [`joblib`](https://joblib.readthedocs.io/) — robust process-pool wrapper standard in the data-science stack
- David Beazley, *Understanding the Python GIL* (still the best mental model)
