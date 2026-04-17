"""Local aiohttp server for deterministic network experiments.

Exposes:
    GET /delay/{seconds}   — sleeps N seconds, returns {"ok": true}
    GET /payload/{bytes}   — returns N random bytes (seeded once, then cached)

Usage:
    with MockServer() as server:
        base = server.base_url
        # spawn workers against base + "/delay/1" etc.
"""
from __future__ import annotations

import asyncio
import random
import socket
import threading
from typing import Optional

from aiohttp import web


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build_payload_cache() -> dict[int, bytes]:
    # Deterministic payloads for reproducibility.
    rng = random.Random(42)
    cache: dict[int, bytes] = {}
    for size in (1_000, 10_000, 50_000, 100_000, 1_000_000):
        cache[size] = bytes(rng.randrange(256) for _ in range(size))
    return cache


class MockServer:
    def __init__(self, port: Optional[int] = None):
        self.port = port or _free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._runner: Optional[web.AppRunner] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._stop_request: Optional[asyncio.Future] = None
        self._payload_cache = _build_payload_cache()

    async def _handle_delay(self, request: web.Request) -> web.Response:
        seconds = float(request.match_info["seconds"])
        await asyncio.sleep(seconds)
        return web.json_response({"ok": True, "slept": seconds})

    async def _handle_payload(self, request: web.Request) -> web.Response:
        size = int(request.match_info["bytes"])
        data = self._payload_cache.get(size)
        if data is None:
            # On-demand, still deterministic per-size via seed(size).
            rng = random.Random(size)
            data = bytes(rng.randrange(256) for _ in range(size))
            self._payload_cache[size] = data
        return web.Response(body=data, content_type="application/octet-stream")

    async def _serve(self) -> None:
        app = web.Application()
        app.router.add_get("/delay/{seconds}", self._handle_delay)
        app.router.add_get("/payload/{bytes}", self._handle_payload)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", self.port)
        await site.start()

        # CREATE THE FUTURE BEFORE signalling readiness — otherwise __exit__
        # can race past _ready.wait() and see _stop_request is None, leaking
        # the server thread.
        self._stop_request = asyncio.get_running_loop().create_future()
        self._ready.set()

        try:
            await self._stop_request
        finally:
            await self._runner.cleanup()

    def _thread_main(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        finally:
            self._loop.close()

    def __enter__(self) -> "MockServer":
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            raise RuntimeError("MockServer failed to start within 5 seconds")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._loop and self._stop_request and not self._stop_request.done():
            self._loop.call_soon_threadsafe(self._stop_request.set_result, None)
        if self._thread:
            self._thread.join(timeout=5.0)


if __name__ == "__main__":
    import time
    with MockServer() as server:
        print(f"MockServer running at {server.base_url}")
        print("Try: curl http://127.0.0.1:{port}/delay/1".replace("{port}", str(server.port)))
        time.sleep(30)
