"""Pure, paradigm-agnostic workload functions used by experiments."""
from __future__ import annotations

import hashlib
from pathlib import Path

import aiofiles
import httpx


def is_prime(n: int) -> bool:
    if n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0:
        return False
    i = 3
    while i * i <= n:
        if n % i == 0:
            return False
        i += 2
    return True


def count_primes_up_to(limit: int) -> int:
    """CPU-bound workload: count primes in [2, limit]."""
    return sum(1 for n in range(2, limit + 1) if is_prime(n))


def hash_bytes(data: bytes, rounds: int) -> str:
    """CPU-bound workload: repeatedly hash `data` `rounds` times."""
    digest = data
    for _ in range(rounds):
        digest = hashlib.sha256(digest).digest()
    return digest.hex()


def fetch_url_sync(client: httpx.Client, url: str) -> int:
    """I/O workload: blocking HTTP GET, returns response body length."""
    response = client.get(url)
    response.raise_for_status()
    return len(response.content)


async def fetch_url_async(client: httpx.AsyncClient, url: str) -> int:
    """I/O workload: async HTTP GET, returns response body length."""
    response = await client.get(url)
    response.raise_for_status()
    return len(response.content)


def read_file_sync(path: Path) -> int:
    """I/O workload: blocking file read, returns byte count."""
    with Path(path).open("rb") as f:
        return len(f.read())


async def read_file_async(path: Path) -> int:
    """I/O workload: async file read via aiofiles, returns byte count."""
    async with aiofiles.open(path, "rb") as f:
        data = await f.read()
    return len(data)
