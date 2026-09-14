from __future__ import annotations

import errno
import http.client
import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Sequence, TypeVar

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


class ProtocolError(OSError):
    # the other side answered, but not with what the protocol expects
    pass


_TIMEOUT_CODES = {errno.ETIMEDOUT, 10060}
_REFUSED_CODES = {errno.ECONNREFUSED, 10061}
_RESET_CODES = {errno.ECONNRESET, errno.ECONNABORTED, 10053, 10054}
# windows socket errors keep their own numbers in winerror, errno only covers the posix ones
_UNREACHABLE_CODES = {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ENETDOWN, 10050, 10051, 10065}

FAILURE_HINTS: Dict[str, str] = {
    "timeout": "The connection timed out. Traffic that disappears without an answer usually points to a firewall rule, "
               "a DPI bypass tool such as GoodbyeDPI, or a VPN.",
    "refused": "The connection was refused. Usually a firewall or antivirus rule is blocking this program or the port, "
               "or a VPN or proxy is rejecting the connection.",
    "reset": "The connection was cut off. DPI bypass tools such as GoodbyeDPI, VPNs and antivirus web filters can reset connections they don't expect.",
    "dns": "The server name could not be looked up. Check that you are online, and whether a VPN or DPI bypass tool changed your DNS settings.",
    "tls": "The secure connection failed. A proxy, antivirus HTTPS scanning or a DPI bypass tool may be interfering with encrypted traffic.",
    "unreachable": "There is no network route. Check that you are connected to the internet and that a VPN isn't stuck connecting.",
    "bad_response": "Something other than the expected server answered. A proxy, a Wi-Fi login page, an antivirus filter "
                    "or a DPI bypass tool may be intercepting the traffic.",
    "http": "The server answered with an error. A proxy or web filter may be blocking the request, or the service is having problems.",
    "other": "The connection failed for an unexpected reason, possibly a firewall, VPN or DPI bypass tool.",
}

CONNECTION_ADVICE = ("If you use GoodbyeDPI, a VPN, a proxy or a similar tool, make sure this program (or Python) is on its whitelist "
                     "or exception list, or turn the tool off while the speed test runs. Windows Firewall and antivirus exceptions are worth checking too.")


def classify_error(exc: BaseException) -> str:
    # order matters, several of these subclass the plain os and value errors checked further down
    if isinstance(exc, urllib.error.HTTPError):
        return "http"
    if isinstance(exc, urllib.error.URLError):
        return classify_error(exc.reason) if isinstance(exc.reason, BaseException) else "other"
    if isinstance(exc, socket.gaierror):
        return "dns"
    if isinstance(exc, ssl.SSLError):
        return "tls"
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(exc, ConnectionRefusedError):
        return "refused"
    if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
        return "reset"
    if isinstance(exc, (ProtocolError, http.client.HTTPException, ValueError)):
        return "bad_response"
    if isinstance(exc, OSError):
        code = getattr(exc, "winerror", None) or exc.errno
        for kind, codes in (("timeout", _TIMEOUT_CODES), ("refused", _REFUSED_CODES), ("reset", _RESET_CODES), ("unreachable", _UNREACHABLE_CODES)):
            if code in codes:
                return kind
    return "other"


def most_common(kinds: Sequence[str], default: str = "other") -> str:
    return Counter(kinds).most_common(1)[0][0] if kinds else default


def failure_message(context: str, kind: str) -> str:
    hint = FAILURE_HINTS.get(kind, FAILURE_HINTS["other"])
    # tool advice is noise when the computer is simply offline
    advice = "" if kind == "unreachable" else f" {CONNECTION_ADVICE}"
    return f"{context} {hint}{advice}"
