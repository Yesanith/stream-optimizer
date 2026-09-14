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


def tcp_round_trips(host: str, port: int, tries: int = 5, timeout: float = 2, spacing: float = 0.05) -> List[float]:
    # tcp handshake times, each close to one round trip and needs nothing from the server.
    # the short pause keeps one burst of congestion from spoiling every sample
    times: List[float] = []
    for attempt in range(tries):
        if attempt:
            time.sleep(spacing)
        start = time.perf_counter()
        try:
            socket.create_connection((host, port), timeout=timeout).close()
        except OSError:
            # an unreachable host would otherwise burn the full timeout on every try
            break
        times.append((time.perf_counter() - start) * 1000)
    return times


def parallel_map(fn: Callable[[T], R], items: Sequence[T], max_workers: Optional[int] = None) -> List[R]:
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=min(len(items), max_workers or len(items))) as pool:
        futures = [pool.submit(fn, item) for item in items]
        return [future.result() for future in futures]
