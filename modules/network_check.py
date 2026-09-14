from __future__ import annotations

import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from modules.net import classify_error, failure_message, median, most_common, parallel_map
from modules.speed_test import SpeedServer, fetch_server_list, probe_server

# reached by ip, so a broken dns setup can't hide an otherwise working connection
INTERNET_HOST = "1.1.1.1"
INTERNET_PORT = 443
CONNECT_TIMEOUT = 2.5
REQUEST_TIMEOUT = 3.0
HANDSHAKES = 4
# the closest server can be down on its own, one answer out of these is enough
SERVERS_TO_TRY = 3
# a lost syn is resent after about a second, so a handshake this slow almost always hides a lost packet
LOST_PACKET_MS = 900
SLOW_MS = 400
HEADLINE = "Could not test the internet connection."


@dataclass
class Probe:
    name: str
    target: str
    ok: bool
    latency_ms: Optional[float] = None
    # failure kind from modules.net, none when the probe passed
    failure: Optional[str] = None
    detail: str = ""
    attempts: int = 0
    lost: int = 0


@dataclass
class PreflightResult:
    ok: bool
    probes: List[Probe]
    # failure kind that decided a failed check
    reason: Optional[str] = None
    # user facing explanation of a failed check
    message: str = ""
    # problems that don't stop the speed test but make its result less reliable
    warnings: List[str] = field(default_factory=list[str])


def _check_internet() -> Probe:
    target = f"{INTERNET_HOST}:{INTERNET_PORT}"
    times: List[float] = []
    failures: List[str] = []
    for _ in range(HANDSHAKES):
        start = time.perf_counter()
        try:
            socket.create_connection((INTERNET_HOST, INTERNET_PORT), timeout=CONNECT_TIMEOUT).close()
        except OSError as exc:
            failures.append(classify_error(exc))
            # two misses without a single answer is conclusive, no need to sit through every timeout
            if not times and len(failures) >= 2:
                break
            continue
        times.append((time.perf_counter() - start) * 1000)

    attempts = len(times) + len(failures)
    if not times:
        return Probe("Internet", target, False, failure=most_common(failures), attempts=attempts, lost=failures.count("timeout"))
    lost = failures.count("timeout") + sum(1 for t in times if t >= LOST_PACKET_MS)
    return Probe("Internet", target, True, latency_ms=median(times), attempts=attempts, lost=lost)


def _check_server_list() -> Tuple[Probe, List[SpeedServer]]:
    name, target = "Speed test server list", "www.speedtest.net"
    start = time.perf_counter()
    try:
        servers = fetch_server_list(REQUEST_TIMEOUT)
    except Exception as exc:
        return Probe(name, target, False, failure=classify_error(exc), detail=str(exc)), []
    return Probe(name, target, True, latency_ms=(time.perf_counter() - start) * 1000), servers


def _probe_quickly(server: SpeedServer) -> Tuple[Optional[float], Optional[str]]:
    return probe_server(server.host, server.port, samples=1, timeout=CONNECT_TIMEOUT)


def _check_test_servers(servers: List[SpeedServer]) -> Probe:
    results = parallel_map(_probe_quickly, servers)
    target = ", ".join(f"{s.host}:{s.port}" for s in servers)
    answered = [latency for latency, _ in results if latency is not None]
    if answered:
        return Probe("Speed test servers", target, True, latency_ms=min(answered), attempts=len(servers))
    failures = [failure for _, failure in results if failure is not None]
    return Probe("Speed test servers", target, False, failure=most_common(failures), attempts=len(servers))


def _quality_warnings(internet: Probe, test_servers: Optional[Probe]) -> List[str]:
    warnings: List[str] = []
    if internet.ok and internet.lost:
        warnings.append(f"{internet.lost} of {internet.attempts} quick test connections were lost right before the speed test. "
                        "Packet loss makes streams stutter, it usually comes from Wi-Fi interference, a busy router, or a VPN or DPI bypass tool.")
    # 1.1.1.1 is blocked on a few networks, the test server latency stands in there
    latency = internet.latency_ms if internet.ok else (test_servers.latency_ms if test_servers is not None else None)
    if latency is not None and latency > SLOW_MS:
        warnings.append(f"Connections took unusually long to open ({latency:.0f} ms) before the speed test. "
                        "A VPN or proxy that routes traffic far away, or a very busy line, can cause this.")
    return warnings


def run_preflight() -> PreflightResult:
    with ThreadPoolExecutor(max_workers=1) as pool:
        internet_future = pool.submit(_check_internet)
        server_list, servers = _check_server_list()
        test_servers = _check_test_servers(servers[:SERVERS_TO_TRY]) if servers else None
        internet = internet_future.result()
    probes = [p for p in (internet, server_list, test_servers) if p is not None]

    # only what the speed test really needs decides the result, 1.1.1.1 is there to explain a failure
    failed = server_list if not server_list.ok else (test_servers if test_servers is not None and not test_servers.ok else None)
    if failed is None:
        return PreflightResult(True, probes, warnings=_quality_warnings(internet, test_servers))

    reason = failed.failure or "other"
    if not internet.ok and not server_list.ok:
        situation = "Neither Cloudflare (1.1.1.1) nor speedtest.net could be reached."
        # when even a plain ip has no route, that says more than whatever the speedtest.net request ran into
        if internet.failure == "unreachable":
            reason = "unreachable"
    elif not server_list.ok:
        situation = "Cloudflare (1.1.1.1) answers but speedtest.net does not, so something is blocking it."
    elif internet.ok:
        situation = "speedtest.net answers but its test servers on port 8080 do not, so something is blocking that traffic."
    else:
        situation = "The speed test servers on port 8080 do not answer."
    return PreflightResult(False, probes, reason, failure_message(f"{HEADLINE} {situation}", reason))
