from __future__ import annotations

import json
import socket
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, List, Optional, Sequence, TypeVar

T = TypeVar("T")
R = TypeVar("R")

USER_AGENT = "stream-optimizer"


def fetch_json(url: str, timeout: float, user_agent: str = USER_AGENT) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def tcp_latency(host: str, port: int, tries: int = 4, timeout: float = 2) -> Optional[float]:
    # tcp handshake time, close to one round trip and needs nothing from the server
    times: List[float] = []
    for _ in range(tries):
        start = time.perf_counter()
        try:
            socket.create_connection((host, port), timeout=timeout).close()
        except OSError:
            # an unreachable host would otherwise burn the full timeout on every try
            break
        times.append((time.perf_counter() - start) * 1000)
    return median(times) if times else None


def parallel_map(fn: Callable[[T], R], items: Sequence[T]) -> List[R]:
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=len(items)) as pool:
        futures = [pool.submit(fn, item) for item in items]
        return [future.result() for future in futures]
