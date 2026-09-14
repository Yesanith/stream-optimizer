from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, cast
from urllib.parse import urlparse

from modules.errors import OptimizerError
from modules.net import fetch_json, parallel_map, tcp_latency

TWITCH_INGEST_API = "https://ingest.twitch.tv/ingests"
# amazon ivs publishes its regional ingests in the same format twitch uses
IVS_INGEST_API = "https://ingest.contribute.live-video.net/api/v2/FindIngest"
YOUTUBE_PRIMARY = "rtmps://a.rtmps.youtube.com:443/live2"
YOUTUBE_BACKUP = "rtmps://b.rtmps.youtube.com:443/live2?backup=1"
# the stream url kick shows in its dashboard, the host picks an ivs region by itself
KICK_INGEST = "rtmps://fa723fc1b171.global-contribute.live-video.net/app"

# rtmp over tcp copes well with round trips under 100 ms, past 200 ms packet loss starts to cost real throughput
GOOD_LATENCY_MS = 100
FAIR_LATENCY_MS = 200
# a smaller gap than this means kick's automatic route is already about as good as the nearest region
ROUTE_GAP_MS = 15


class IngestError(OptimizerError):
    pass


@dataclass
class IngestServer:
    name: str
    url: str
    latency_ms: Optional[float] = None


@dataclass
class IngestReport:
    platform_key: str
    # whether obs lets the user pick a server for this platform
    selectable: bool
    note: str
    servers: List[IngestServer] = field(default_factory=list[IngestServer])
    recommended: Optional[IngestServer] = None


def latency_rating(latency_ms: float) -> str:
    if latency_ms <= GOOD_LATENCY_MS:
        return "good"
    if latency_ms <= FAIR_LATENCY_MS:
        return "fair"
    return "poor"


def probe_latency(url: str) -> Optional[float]:
    parsed = urlparse(url)
    if not parsed.hostname:
        return None
    try:
        port = parsed.port or (443 if parsed.scheme == "rtmps" else 1935)
    except ValueError:
        return None
    return tcp_latency(parsed.hostname, port)


def _probe_server(server: IngestServer) -> Optional[float]:
    return probe_latency(server.url)


def _measure(servers: List[IngestServer]) -> None:
    for server, latency in zip(servers, parallel_map(_probe_server, servers)):
        server.latency_ms = latency


def _fastest(servers: List[IngestServer]) -> Optional[IngestServer]:
    reachable = [s for s in servers if s.latency_ms is not None]
    return min(reachable, key=lambda s: s.latency_ms or 0.0) if reachable else None


def _load_ingest_list(url: str, source: str, timeout: float) -> List[IngestServer]:
    try:
        payload = fetch_json(url, timeout)
    except Exception as exc:
        raise IngestError(f"Could not load the {source} server list. Check your connection and try again.", str(exc))

    entries = cast(Dict[str, Any], payload).get("ingests") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise IngestError(f"{source} returned a server list in an unexpected format.")

    servers: List[IngestServer] = []
    for entry in cast(List[Any], entries):
        if not isinstance(entry, dict):
            continue
        item = cast(Dict[str, Any], entry)
        template = item.get("url_template")
        availability = item.get("availability", 1.0)
        if not isinstance(template, str) or (isinstance(availability, (int, float)) and availability <= 0):
            continue
        server_url = template.replace("/{stream_key}", "")
        servers.append(IngestServer(str(item.get("name", server_url)), server_url))

    if not servers:
        raise IngestError(f"{source} returned an empty server list. Try again later.")
    return servers


def _twitch(timeout: float) -> IngestReport:
    servers = _load_ingest_list(TWITCH_INGEST_API, "Twitch", timeout)
    _measure(servers)
    best = _fastest(servers)
    if best is None:
        note = "No Twitch server answered. A firewall may be blocking port 1935."
    elif best.name == "Default":
        note = "Twitch's global Default server is your fastest route, so OBS's automatic server choice is fine."
    else:
        note = f"In OBS choose \"{best.name}\" under Settings > Stream > Server."
    return IngestReport("twitch", True, note, servers, best)


def _youtube(timeout: float) -> IngestReport:
    primary = IngestServer("Primary YouTube ingest server", YOUTUBE_PRIMARY)
    backup = IngestServer("Backup YouTube ingest server", YOUTUBE_BACKUP)
    servers = [primary, backup]
    _measure(servers)
    # both hostnames are routed to a nearby ingest, the backup only exists for redundancy
    if primary.latency_ms is not None:
        return IngestReport("youtube", True, "YouTube routes you to a nearby ingest automatically. Keep the primary server in OBS.", servers, primary)
    if backup.latency_ms is not None:
        return IngestReport("youtube", True, "The primary server did not answer, use the backup server for now.", servers, backup)
    return IngestReport("youtube", True, "No YouTube ingest server answered. A firewall may be blocking port 443.", servers)


def _kick(timeout: float) -> IngestReport:
    kick = IngestServer("Automatic routing", KICK_INGEST)
    try:
        regions = [s for s in _load_ingest_list(IVS_INGEST_API, "Amazon IVS", timeout) if s.name != "Default"]
    except IngestError:
        # the region comparison is extra context, the kick check works without it
        regions = []
    _measure([kick, *regions])

    if kick.latency_ms is None:
        return IngestReport("kick", False, "Kick's ingest did not answer. A firewall may be blocking port 443.", [kick])

    nearest = _fastest(regions)
    if nearest is not None and nearest.latency_ms is not None and kick.latency_ms - nearest.latency_ms >= ROUTE_GAP_MS:
        route = f"Kick picks the region itself, {kick.latency_ms - nearest.latency_ms:.0f} ms slower than your nearest one ({nearest.name})."
    elif nearest is not None:
        route = "Kick picks the region itself and lands close to your nearest one."
    else:
        route = "Kick picks the region itself, there is no server to choose."
    return IngestReport("kick", False, f"{route} Use your dashboard's Stream URL if it differs.", [kick], kick)


def _other(timeout: float) -> IngestReport:
    return IngestReport("other", False, "Use the server URL your platform gives you.")


CHECKS: Dict[str, Callable[[float], IngestReport]] = {
    "twitch": _twitch,
    "youtube": _youtube,
    "kick": _kick,
    "other": _other,
}


def check_ingest(platform_key: str, timeout: float = 10) -> IngestReport:
    if platform_key not in CHECKS:
        raise IngestError(f"No ingest check for platform {platform_key}.")
    return CHECKS[platform_key](timeout)
