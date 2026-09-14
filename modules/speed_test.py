# speedtest-cli ships without type hints
# pyright: reportMissingTypeStubs=false
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Callable, Dict, List, Optional, Tuple, cast

try:
    import speedtest
except Exception:
    speedtest = None


# same geo aware endpoint the speedtest.net website uses
SERVER_API = "https://www.speedtest.net/api/js/servers?engine=js&limit=10&https_functional=true"
PING_SAMPLES = 5

# stage name, progress 0..1 within the stage, values measured so far
ProgressCallback = Callable[[str, float, Dict[str, float]], None]


class SpeedTestError(Exception):
    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


@dataclass
class SpeedTestResult:
    download_mbps: float
    upload_mbps: float
    ping_ms: float
    server: str


def _ignore_progress(stage: str, fraction: float, measured: Dict[str, float]) -> None:
    pass


def _connect(module: ModuleType, timeout: int) -> Any:
    last_error: Optional[Exception] = None
    # some networks block one of the two config endpoints so try both
    for secure in (True, False):
        try:
            return module.Speedtest(timeout=timeout, secure=secure)
        except Exception as exc:
            last_error = exc
    raise SpeedTestError("Could not reach speedtest.net. Check your internet connection or firewall.", str(last_error))


def _nearby_servers(module: ModuleType, client: Any, timeout: int) -> List[Dict[str, Any]]:
    # speedtest-cli's own static list sometimes returns servers from another country, so prefer the api
    try:
        request = urllib.request.Request(SERVER_API, headers={"User-Agent": module.build_user_agent()})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = cast(List[Any], json.loads(response.read().decode("utf-8")))
        entries = [cast(Dict[str, Any], s) for s in payload if isinstance(s, dict)]
        servers = [s for s in entries if s.get("host") and s.get("url")]
        if servers:
            return servers
    except Exception:
        pass

    try:
        client.get_servers()
        return list(client.get_closest_servers(limit=10))
    except Exception as exc:
        raise SpeedTestError("Could not load the speed test server list. Try again in a moment.", str(exc))


def ping_server(host: str, samples: int = PING_SAMPLES, timeout: float = 2) -> Optional[float]:
    # ookla servers answer PING with PONG on the test port, same latency check the official apps do
    name, _, port = host.rpartition(":")
    times: List[float] = []
    try:
        with socket.create_connection((name, int(port)), timeout=timeout) as sock:
            reader = sock.makefile("rb")
            sock.sendall(b"HI\n")
            if not reader.readline().startswith(b"HELLO"):
                return None
            for _ in range(samples):
                start = time.perf_counter()
                sock.sendall(b"PING %d\n" % int(time.time() * 1000))
                if not reader.readline().startswith(b"PONG"):
                    return None
                times.append((time.perf_counter() - start) * 1000)
    except (OSError, ValueError):
        return None
    times.sort()
    return times[len(times) // 2]


def _pick_server(client: Any, servers: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], float]:
    with ThreadPoolExecutor(max_workers=len(servers)) as pool:
        futures = [pool.submit(ping_server, str(server["host"])) for server in servers]
        pings = [future.result() for future in futures]

    reachable = [(ping, server) for ping, server in zip(pings, servers) if ping is not None]
    if reachable:
        ping, server = min(reachable, key=lambda pair: pair[0])
        # only sets the transfer target, its http based latency number is ignored
        client.get_best_server([server])
        return server, ping

    # no server spoke the ookla protocol, fall back to speedtest-cli's http latency check
    fallback: Dict[str, Any] = client.get_best_server(servers)
    return fallback, float(fallback.get("latency", 0.0))


def _counter(report: ProgressCallback, stage: str, measured: Dict[str, float]) -> Callable[..., None]:
    lock = threading.Lock()
    finished = [0]

    # speedtest-cli calls this from its worker threads, once with start=True and once with end=True per request
    def callback(_index: int, total: int, start: bool = False, end: bool = False) -> None:
        if not end:
            return
        with lock:
            finished[0] += 1
            fraction = min(finished[0] / total, 1.0) if total else 1.0
        report(stage, fraction, dict(measured))

    return callback


def run_speed_test(progress: Optional[ProgressCallback] = None, timeout: int = 15) -> SpeedTestResult:
    if speedtest is None:
        raise SpeedTestError("speedtest-cli is not installed. Run: pip install -r requirements.txt")

    report = progress or _ignore_progress
    measured: Dict[str, float] = {}

    report("connecting", 0.0, dict(measured))
    client = _connect(speedtest, timeout)

    report("server", 0.0, dict(measured))
    servers = _nearby_servers(speedtest, client, timeout)
    try:
        server, ping = _pick_server(client, servers)
    except Exception as exc:
        raise SpeedTestError("No speed test server responded. Try again in a moment.", str(exc))
    measured["ping_ms"] = ping

    try:
        report("download", 0.0, dict(measured))
        measured["download_mbps"] = client.download(callback=_counter(report, "download", measured)) / 1e6

        report("upload", 0.0, dict(measured))
        measured["upload_mbps"] = client.upload(callback=_counter(report, "upload", measured), pre_allocate=False) / 1e6
    except Exception as exc:
        raise SpeedTestError("The connection dropped during the test. Try again.", str(exc))

    if measured["upload_mbps"] <= 0:
        raise SpeedTestError("Upload speed was measured as zero. Try again.")

    report("done", 1.0, dict(measured))
    return SpeedTestResult(
        download_mbps=round(measured["download_mbps"], 2),
        upload_mbps=round(measured["upload_mbps"], 2),
        ping_ms=round(measured["ping_ms"], 1),
        server=f"{server.get('sponsor', '?')} - {server.get('name', '?')}, {server.get('country', '?')}",
    )
