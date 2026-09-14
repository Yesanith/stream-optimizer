from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Dict, Optional

try:
    import speedtest
except Exception:
    speedtest = None


# stage name, progress 0..1 within the stage, values measured so far
ProgressCallback = Callable[[str, float, Dict[str, float]], None]


class SpeedTestError(Exception):
    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail


@dataclass
class SpeedTestResult:
    download_mbps: float
    upload_mbps: float
    ping_ms: float
    server: str


def _connect(timeout: float):
    last_error: Optional[Exception] = None
    # some networks block one of the two config endpoints so try both
    for secure in (True, False):
        try:
            return speedtest.Speedtest(timeout=timeout, secure=secure)
        except Exception as exc:
            last_error = exc
    raise SpeedTestError("Could not reach speedtest.net. Check your internet connection or firewall.", str(last_error))


def _counter(report: ProgressCallback, stage: str, measured: Dict[str, float]):
    lock = threading.Lock()
    finished = [0]

    # speedtest-cli calls this from its worker threads, once with start=True and once with end=True per request
    def callback(_index, total, start=False, end=False):
        if not end:
            return
        with lock:
            finished[0] += 1
            fraction = min(finished[0] / total, 1.0) if total else 1.0
        report(stage, fraction, dict(measured))

    return callback


def run_speed_test(progress: Optional[ProgressCallback] = None, timeout: float = 15) -> SpeedTestResult:
    if speedtest is None:
        raise SpeedTestError("speedtest-cli is not installed. Run: pip install -r requirements.txt")

    report = progress or (lambda *_: None)
    measured: Dict[str, float] = {}

    report("connecting", 0.0, dict(measured))
    client = _connect(timeout)

    report("server", 0.0, dict(measured))
    try:
        server = client.get_best_server()
    except Exception as exc:
        raise SpeedTestError("No speed test server responded. Try again in a moment.", str(exc))
    measured["ping_ms"] = float(server.get("latency", 0.0))

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
