"""Tests for lab.workloads."""
from pathlib import Path

import httpx
import pytest
import respx

from lab.workloads import (
    count_primes_up_to,
    fetch_url_async,
    fetch_url_sync,
    hash_bytes,
    is_prime,
    read_file_async,
    read_file_sync,
)


def test_is_prime_handles_edge_cases():
    assert is_prime(2) is True
    assert is_prime(3) is True
    assert is_prime(4) is False
    assert is_prime(1) is False
    assert is_prime(0) is False
    assert is_prime(-5) is False


def test_count_primes_up_to_matches_known_counts():
    # π(10) = 4  (2, 3, 5, 7)
    assert count_primes_up_to(10) == 4
    # π(100) = 25
    assert count_primes_up_to(100) == 25


def test_hash_bytes_is_deterministic():
    data = b"hello world" * 1000
    assert hash_bytes(data, rounds=1) == hash_bytes(data, rounds=1)


def test_hash_bytes_rounds_change_output():
    data = b"xyz"
    assert hash_bytes(data, rounds=1) != hash_bytes(data, rounds=5)


@respx.mock
def test_fetch_url_sync_returns_body_length():
    respx.get("http://example.test/foo").respond(200, text="hello")
    with httpx.Client() as client:
        length = fetch_url_sync(client, "http://example.test/foo")
    assert length == 5


@pytest.mark.asyncio
@respx.mock
async def test_fetch_url_async_returns_body_length():
    respx.get("http://example.test/bar").respond(200, text="hello world")
    async with httpx.AsyncClient() as client:
        length = await fetch_url_async(client, "http://example.test/bar")
    assert length == 11


def test_read_file_sync_returns_byte_count(tmp_path: Path):
    p = tmp_path / "data.bin"
    p.write_bytes(b"x" * 1024)
    assert read_file_sync(p) == 1024


@pytest.mark.asyncio
async def test_read_file_async_returns_byte_count(tmp_path: Path):
    p = tmp_path / "data.bin"
    p.write_bytes(b"y" * 2048)
    assert await read_file_async(p) == 2048
