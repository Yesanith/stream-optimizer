from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class Platform:
    key: str
    name: str
    max_bitrate_kbps: int
    max_height: int


PLATFORMS: Dict[str, Platform] = {
    "twitch": Platform("twitch", "Twitch", 8000, 1080),
    "kick": Platform("kick", "Kick", 12000, 1080),
    "youtube": Platform("youtube", "YouTube", 51000, 1440),
    "other": Platform("other", "Other", 8000, 1080),
}


def platform_by_name(name: str) -> Platform:
    return next(p for p in PLATFORMS.values() if p.name == name)
