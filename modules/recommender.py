from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from modules.system_info import SystemInfo


UPLOAD_USAGE = 0.70
AUDIO_KBPS = 160
MIN_VIDEO_KBPS = 300
KEYFRAME_SECONDS = 2


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


@dataclass(frozen=True)
class Tier:
    label: str
    width: int
    height: int
    fps: int
    min_kbps: int
    # past this extra bitrate barely improves quality at this resolution
    max_useful_kbps: int


TIERS = (
    Tier("480p30", 854, 480, 30, 1000, 2000),
    Tier("720p30", 1280, 720, 30, 2500, 4500),
    Tier("720p60", 1280, 720, 60, 3500, 6000),
    Tier("1080p30", 1920, 1080, 30, 4500, 6000),
    Tier("1080p60", 1920, 1080, 60, 6000, 12000),
    Tier("1440p60", 2560, 1440, 60, 9000, 24000),
)

# x264 shares the cpu with the game so it gets a much lower ceiling than hardware encoders
X264_PROFILE = {
    "low": ("720p30", "superfast"),
    "mid": ("720p60", "veryfast"),
    "high": ("1080p30", "veryfast"),
    "very_high": ("1080p60", "veryfast"),
    "ultra": ("1080p60", "faster"),
}

HW_ENCODER_CAP = {
    "low": "720p60",
    "mid": "1080p60",
    "high": "1080p60",
    "very_high": "1440p60",
    "ultra": "1440p60",
}

ENCODER_NAMES = {
    "nvenc": "NVIDIA NVENC H.264",
    "amf": "AMD HW H.264 (AVC)",
    "x264": "x264",
}

LEVEL_ORDER = {"critical": 0, "warning": 1, "info": 2}


@dataclass(frozen=True)
class Advice:
    level: str
    code: str
    message: str


@dataclass
class Recommendation:
    platform: Platform
    tier: Tier
    encoder: str
    encoder_name: str
    preset: str
    video_kbps: int
    audio_kbps: int
    keyframe_s: int
    rate_control: str
    profile: str
    cpu_class: str
    advice: List[Advice]

    def as_text(self) -> str:
        return "\n".join([
            f"Platform: {self.platform.name}",
            f"Output Resolution: {self.tier.width}x{self.tier.height}",
            f"FPS: {self.tier.fps}",
            f"Encoder: {self.encoder_name}",
            f"Rate Control: {self.rate_control}",
            f"Video Bitrate: {self.video_kbps} Kbps",
            f"Audio Bitrate: {self.audio_kbps} Kbps",
            f"Keyframe Interval: {self.keyframe_s} s",
            f"Preset: {self.preset}",
            f"Profile: {self.profile}",
        ])


def cpu_class(physical_cores: int, logical_cores: int) -> str:
    if logical_cores <= 4:
        return "low"
    if physical_cores < 6:
        return "mid"
    if physical_cores < 8:
        return "high"
    if physical_cores < 12:
        return "very_high"
    return "ultra"


def pick_encoder(system: SystemInfo) -> str:
    if system.has_nvenc:
        return "nvenc"
    if system.has_amf:
        return "amf"
    return "x264"


def hardware_preset(encoder: str, system: SystemInfo) -> str:
    names = [g.name.upper() for g in system.gpus]
    if encoder == "nvenc":
        return "P5: Slow (Good Quality)" if any("RTX" in n for n in names) else "P4: Medium"
    if encoder == "amf":
        return "Quality" if any(re.search(r"RX\s?[5-9]\d{3}", n) for n in names) else "Balanced"
    raise ValueError(f"no hardware preset for {encoder}")


def required_upload_mbps(video_kbps: int) -> float:
    return round((video_kbps + AUDIO_KBPS) / UPLOAD_USAGE / 1000, 1)


def _tier_index(label: str) -> int:
    return next(i for i, t in enumerate(TIERS) if t.label == label)


def recommend(platform_key: str, system: SystemInfo, upload_mbps: float, ping_ms: Optional[float] = None) -> Recommendation:
    if platform_key not in PLATFORMS:
        raise ValueError(f"unknown platform: {platform_key}")
    if upload_mbps <= 0:
        raise ValueError("upload speed must be greater than zero")

    platform = PLATFORMS[platform_key]
    advice: List[Advice] = []

    video_budget = int(upload_mbps * 1000 * UPLOAD_USAGE) - AUDIO_KBPS
    video_cap = max(min(video_budget, platform.max_bitrate_kbps), 0)

    cls = cpu_class(system.physical_cores, system.logical_cores)
    encoder = pick_encoder(system)
    if encoder == "x264":
        hw_cap_label, preset = X264_PROFILE[cls]
    else:
        hw_cap_label, preset = HW_ENCODER_CAP[cls], hardware_preset(encoder, system)

    platform_tiers = [i for i, t in enumerate(TIERS) if t.height <= platform.max_height]
    hw_tiers = [i for i in platform_tiers if i <= _tier_index(hw_cap_label)]
    affordable = [i for i in hw_tiers if TIERS[i].min_kbps <= video_cap]
    tier_index = affordable[-1] if affordable else 0
    tier = TIERS[tier_index]

    video_kbps = max(min(video_cap, tier.max_useful_kbps) // 100 * 100, MIN_VIDEO_KBPS)

    if not affordable:
        advice.append(Advice(
            "critical", "upload_too_low",
            f"Your upload speed ({upload_mbps:.1f} Mbps) is too low for a stable stream. "
            f"At least {required_upload_mbps(TIERS[0].min_kbps)} Mbps is needed even for 480p30.",
        ))
    elif upload_mbps < 5:
        advice.append(Advice(
            "warning", "upload_low",
            f"Your upload speed is low ({upload_mbps:.1f} Mbps). Avoid other uploads while streaming, "
            "and use a wired connection if you can.",
        ))

    if affordable and tier_index < hw_tiers[-1]:
        next_tier = TIERS[tier_index + 1]
        advice.append(Advice(
            "info", "upload_limited",
            f"Your hardware can handle more. About {required_upload_mbps(next_tier.min_kbps)} Mbps upload "
            f"would unlock {next_tier.label}.",
        ))
    elif hw_tiers[-1] < platform_tiers[-1] and TIERS[hw_tiers[-1] + 1].min_kbps <= video_cap:
        advice.append(Advice(
            "info", "hardware_limited",
            f"Your connection could carry more, but {tier.label} is the safe limit for your hardware.",
        ))

    if video_kbps == platform.max_bitrate_kbps and video_budget > platform.max_bitrate_kbps:
        advice.append(Advice(
            "info", "platform_cap",
            f"Bitrate is capped at {platform.max_bitrate_kbps:,} Kbps, the limit for {platform.name}.",
        ))

    if encoder == "x264":
        advice.append(Advice(
            "warning", "no_hw_encoder",
            "No hardware encoder (NVENC/AMF) was found. x264 encodes on the CPU and can lower in-game FPS.",
        ))
        if system.has_qsv:
            advice.append(Advice(
                "info", "qsv_available",
                "An Intel GPU was found. If x264 is too heavy, try the QuickSync H.264 encoder in OBS.",
            ))
        if cls == "low":
            advice.append(Advice(
                "warning", "weak_cpu_x264",
                "Your CPU has few cores for x264. If OBS shows 'Encoding overloaded', drop to 30 FPS or a lower resolution.",
            ))

    if 0 < system.ram_gb < 8:
        advice.append(Advice(
            "warning", "low_ram",
            f"Only {system.ram_gb} GB of RAM. Close browsers and other background apps while streaming.",
        ))

    if ping_ms is not None and ping_ms > 100:
        advice.append(Advice(
            "warning", "high_ping",
            f"High ping to the test server ({round(ping_ms)} ms). If your stream stutters, pick the ingest server closest to you in OBS.",
        ))

    advice.sort(key=lambda a: LEVEL_ORDER[a.level])

    return Recommendation(
        platform=platform,
        tier=tier,
        encoder=encoder,
        encoder_name=ENCODER_NAMES[encoder],
        preset=preset,
        video_kbps=video_kbps,
        audio_kbps=AUDIO_KBPS,
        keyframe_s=KEYFRAME_SECONDS,
        rate_control="CBR",
        profile="high",
        cpu_class=cls,
        advice=advice,
    )
