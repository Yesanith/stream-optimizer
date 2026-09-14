# speedtest-cli ships without type hints
# pyright: reportMissingTypeStubs=false
from __future__ import annotations

import io
import os
import socket
import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, cast

from modules.errors import OptimizerError
from modules.net import USER_AGENT, fetch_json, median, parallel_map

try:
    import speedtest
except Exception:
    speedtest = None


# same geo aware server list the speedtest.net website uses
SERVER_API = "https://www.speedtest.net/api/js/servers?engine=js&limit=10&https_functional=true"

PING_SAMPLES = 5
STREAMS = 4
TEST_SECONDS = 8.0
# tcp slow start and socket buffers filling up distort the first seconds of every transfer
WARMUP_SECONDS = 2.0
SAMPLE_SECONDS = 0.1
# a live number from a single sample right after warmup jumps around, wait for this much steady data first
LIVE_MIN_SECONDS = 0.5
DOWNLOAD_CHUNK = 25_000_000
UPLOAD_CHUNK = 2_000_000
IO_BYTES = 64 * 1024
SOCKET_TIMEOUT = 5.0
MAX_ATTEMPTS = 3
# a reading this low wrecks the recommendation, so it has to hold up on a second server first
CONFIRM_BELOW_MBPS = 5.0
# spread of the half second readings, relative to the average, above which a result counts as unstable
UNSTABLE_VARIATION = 0.35

# stage name, progress 0..1 within the stage, values measured so far
ProgressCallback = Callable[[str, float, Dict[str, float]], None]


class SpeedTestError(OptimizerError):
    pass


@dataclass
class SpeedServer:
    name: str
    host: str
    port: int
    ping_ms: Optional[float] = None


@dataclass
class Transfer:
    mbps: float
    stable: bool
    failed_streams: int


@dataclass
class SpeedTestResult:
    download_mbps: float
    upload_mbps: float
    ping_ms: float
    server: str
    # how far the reading can be trusted, shown to the user as is
    warnings: List[str] = field(default_factory=list[str])


def _ignore_progress(stage: str, fraction: float, measured: Dict[str, float]) -> None:
    pass


def _servers_from_entries(entries: List[Dict[str, Any]]) -> List[SpeedServer]:
    servers: List[SpeedServer] = []
    for entry in entries:
        name, _, port = str(entry.get("host", "")).rpartition(":")
        if not name or not port.isdigit():
            continue
        label = f"{entry.get('sponsor', '?')} - {entry.get('name', '?')}, {entry.get('country', '?')}"
        servers.append(SpeedServer(label, name, int(port)))
    return servers


def _nearby_servers(timeout: float) -> List[SpeedServer]:
    user_agent = speedtest.build_user_agent() if speedtest is not None else USER_AGENT
    try:
        payload = fetch_json(SERVER_API, timeout, user_agent)
        servers = _servers_from_entries([cast(Dict[str, Any], s) for s in cast(List[Any], payload) if isinstance(s, dict)])
        if servers:
            return servers
    except Exception:
        pass

    # the api is down or blocked, speedtest-cli's own list is less accurate but still usable
    message = "Could not load the speed test server list. Check your internet connection or firewall."
    if speedtest is None:
        raise SpeedTestError(message)
    last_error: Optional[Exception] = None
    for secure in (True, False):
        try:
            client: Any = speedtest.Speedtest(timeout=int(timeout), secure=secure)
            client.get_servers()
            servers = _servers_from_entries([cast(Dict[str, Any], s) for s in client.get_closest_servers(limit=10)])
            if servers:
                return servers
        except Exception as exc:
            last_error = exc
    raise SpeedTestError(message, str(last_error))


def ping_server(host: str, port: int, samples: int = PING_SAMPLES, timeout: float = 2) -> Optional[float]:
    # ookla servers answer PING with PONG on the test port, same latency check the official apps do
    times: List[float] = []
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
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
    return median(times)


def _ping(server: SpeedServer) -> Optional[float]:
    return ping_server(server.host, server.port)


def _rank_by_ping(servers: List[SpeedServer]) -> List[SpeedServer]:
    for server, ping in zip(servers, parallel_map(_ping, servers)):
        server.ping_ms = ping
    return sorted((s for s in servers if s.ping_ms is not None), key=lambda s: s.ping_ms or 0.0)


class _Meter:
    def __init__(self, streams: int) -> None:
        self.counts = [0] * streams
        self.failures = 0
        self._lock = threading.Lock()

    def add(self, slot: int, amount: int) -> None:
        # each slot has a single writer thread, the sampler reading a slightly stale total is fine
        self.counts[slot] += amount

    def fail(self) -> None:
        with self._lock:
            self.failures += 1

    def total(self) -> int:
        return sum(self.counts)


def _open(server: SpeedServer) -> Tuple[socket.socket, io.BufferedReader]:
    sock = socket.create_connection((server.host, server.port), timeout=SOCKET_TIMEOUT)
    reader = sock.makefile("rb")
    try:
        sock.sendall(b"HI\n")
        if not reader.readline().startswith(b"HELLO"):
            raise OSError("server did not answer HI")
    except OSError:
        sock.close()
        raise
    return sock, reader


def _download_stream(server: SpeedServer, slot: int, meter: _Meter, stop: threading.Event) -> None:
    try:
        sock, _ = _open(server)
    except OSError:
        meter.fail()
        return
    with sock:
        try:
            while not stop.is_set():
                sock.sendall(b"DOWNLOAD %d\n" % DOWNLOAD_CHUNK)
                remaining = DOWNLOAD_CHUNK
                while remaining > 0:
                    if stop.is_set():
                        return
                    data = sock.recv(min(IO_BYTES, remaining))
                    if not data:
                        raise OSError("server closed the connection")
                    remaining -= len(data)
                    meter.add(slot, len(data))
        except OSError:
            if not stop.is_set():
                meter.fail()


def _upload_body() -> bytes:
    header = b"UPLOAD %d 0\n" % UPLOAD_CHUNK
    # random bytes so nothing along the path can compress the payload
    return header + os.urandom(UPLOAD_CHUNK - len(header) - 1) + b"\n"


def _upload_stream(server: SpeedServer, slot: int, meter: _Meter, stop: threading.Event, body: bytes) -> None:
    try:
        sock, reader = _open(server)
    except OSError:
        meter.fail()
        return
    view = memoryview(body)
    with sock:
        try:
            while not stop.is_set():
                for offset in range(0, len(view), IO_BYTES):
                    if stop.is_set():
                        return
                    piece = view[offset:offset + IO_BYTES]
                    sock.sendall(piece)
                    meter.add(slot, len(piece))
                if not reader.readline().startswith(b"OK"):
                    raise OSError("server did not confirm the upload")
        except OSError:
            if not stop.is_set():
                meter.fail()


def _rate(samples: List[Tuple[float, int]]) -> float:
    (start, first), (end, last) = samples[0], samples[-1]
    return (last - first) * 8 / (end - start) / 1e6 if end > start else 0.0


def _summarize(samples: List[Tuple[float, int]], failures: int) -> Transfer:
    steady = [s for s in samples if s[0] >= WARMUP_SECONDS]
    if len(steady) < 2:
        return Transfer(0.0, False, failures)
    mbps = _rate(steady)
    step = max(round(0.5 / SAMPLE_SECONDS), 1)
    windows = [_rate(steady[i:i + step + 1]) for i in range(0, len(steady) - step, step)]
    stable = len(windows) < 3 or mbps <= 0 or statistics.pstdev(windows) / mbps <= UNSTABLE_VARIATION
    return Transfer(mbps, stable, failures)


def _transfer(server: SpeedServer, direction: str, on_sample: Callable[[float, Optional[float]], None]) -> Transfer:
    meter = _Meter(STREAMS)
    stop = threading.Event()
    if direction == "download":
        threads = [threading.Thread(target=_download_stream, args=(server, slot, meter, stop), daemon=True) for slot in range(STREAMS)]
    else:
        body = _upload_body()
        threads = [threading.Thread(target=_upload_stream, args=(server, slot, meter, stop, body), daemon=True) for slot in range(STREAMS)]

    samples: List[Tuple[float, int]] = [(0.0, 0)]
    start = time.perf_counter()
    for thread in threads:
        thread.start()
    try:
        while True:
            time.sleep(SAMPLE_SECONDS)
            elapsed = time.perf_counter() - start
            samples.append((elapsed, meter.total()))
            # the live number uses the same steady window as the result so it settles on the final value
            steady = [s for s in samples if s[0] >= WARMUP_SECONDS]
            settled = len(steady) >= 2 and steady[-1][0] - steady[0][0] >= LIVE_MIN_SECONDS
            on_sample(min(elapsed / TEST_SECONDS, 1.0), _rate(steady) if settled else None)
            if elapsed >= TEST_SECONDS or meter.failures >= STREAMS:
                break
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=2)
    return _summarize(samples, meter.failures)


def _measure_direction(ranked: List[SpeedServer], direction: str, report: ProgressCallback,
                       measured: Dict[str, float]) -> Tuple[Transfer, SpeedServer, List[str]]:
    key = f"{direction}_mbps"

    def on_sample(fraction: float, live_mbps: Optional[float]) -> None:
        # nothing is shown during warmup, upload in particular reads far too high while socket buffers fill
        if live_mbps is None:
            measured.pop(key, None)
        else:
            measured[key] = live_mbps
        report(direction, fraction, dict(measured))

    clean: List[Tuple[Transfer, SpeedServer]] = []
    partial: List[Tuple[Transfer, SpeedServer]] = []
    for server in ranked[:MAX_ATTEMPTS]:
        transfer = _transfer(server, direction, on_sample)
        if transfer.mbps <= 0:
            continue
        (clean if transfer.failed_streams == 0 else partial).append((transfer, server))
        # a healthy reading is enough, a low one has to hold up on a second server
        if clean and (clean[0][0].mbps >= CONFIRM_BELOW_MBPS or len(clean) >= 2):
            break

    pool = clean or partial
    if not pool:
        raise SpeedTestError(f"The {direction} test could not get data through to any server. Check your connection and try again.")
    transfer, server = max(pool, key=lambda pair: pair[0].mbps)

    warnings: List[str] = []
    if not clean:
        warnings.append(f"Some connections dropped during the {direction} test, your real {direction} speed may be higher than measured.")
    elif len(clean) >= 2 and clean[0][0].mbps < CONFIRM_BELOW_MBPS:
        warnings.append(f"The {direction} speed came out low, so it was measured on a second server too and the higher reading is used.")
    elif transfer.mbps < CONFIRM_BELOW_MBPS:
        warnings.append(f"The {direction} speed came out low and could not be confirmed on a second server.")
    if not transfer.stable:
        warnings.append(f"The {direction} speed changed a lot during the test. If something else was using the connection, run the test again.")

    measured[key] = transfer.mbps
    return transfer, server, warnings


def run_speed_test(progress: Optional[ProgressCallback] = None, timeout: float = 10) -> SpeedTestResult:
    report = progress or _ignore_progress
    measured: Dict[str, float] = {}

    report("connecting", 0.0, dict(measured))
    servers = _nearby_servers(timeout)

    report("server", 0.0, dict(measured))
    ranked = _rank_by_ping(servers)
    if not ranked:
        raise SpeedTestError("No speed test server answered. A firewall may be blocking port 8080, try again in a moment.")
    measured["ping_ms"] = ranked[0].ping_ms or 0.0

    download, down_server, down_warnings = _measure_direction(ranked, "download", report, measured)
    upload, up_server, up_warnings = _measure_direction(ranked, "upload", report, measured)
    report("done", 1.0, dict(measured))

    server = down_server.name if up_server is down_server else f"{down_server.name} (upload: {up_server.name})"
    return SpeedTestResult(
        download_mbps=round(download.mbps, 2),
        upload_mbps=round(upload.mbps, 2),
        ping_ms=round(down_server.ping_ms or measured["ping_ms"], 1),
        server=server,
        warnings=down_warnings + up_warnings,
    )
