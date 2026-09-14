from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple, Union

from modules.errors import OptimizerError
from modules.recommender import Recommendation

# encoder ids as obs 31 and newer register them, older builds named the nvenc encoder differently
ENCODER_IDS: Dict[str, str] = {"nvenc": "obs_nvenc_h264_tex", "amf": "h264_texture_amf", "x264": "obs_x264"}
AUDIO_SAMPLE_RATE = 48000

Size = Tuple[int, int]
Setting = Union[str, int]

_UNSAFE_NAME = re.compile(r'[<>:"/\\|?*]')


class ProfileError(OptimizerError):
    pass


def profile_name(rec: Recommendation) -> str:
    return f"Stream Optimizer {rec.platform.name} {rec.tier.label}"


def _even(value: float) -> int:
    return max(int(round(value / 2)) * 2, 2)


def video_sizes(rec: Recommendation, screen: Size) -> Tuple[Size, Size]:
    # the canvas follows the monitor so existing scenes keep their layout, cut to 16:9 because platforms expect it
    width, height = screen
    if width <= 0 or height <= 0:
        width, height = rec.tier.width, rec.tier.height
    if width * 9 > height * 16:
        width = _even(height * 16 / 9)
    elif width * 9 < height * 16:
        height = _even(width * 9 / 16)
    # a canvas smaller than the recommendation is never upscaled, that only costs bitrate
    output = (rec.tier.width, rec.tier.height) if height >= rec.tier.height else (width, height)
    return (width, height), output


def encoder_settings(rec: Recommendation) -> Dict[str, Setting]:
    settings: Dict[str, Setting] = {
        "rate_control": rec.rate_control,
        "bitrate": rec.video_kbps,
        "keyint_sec": rec.keyframe_s,
        "preset": rec.preset_id,
        "profile": rec.profile,
    }
    if rec.encoder == "nvenc":
        # obs's own nvenc defaults, written out so the profile doesn't depend on whatever the user changed before
        settings.update({"tune": "hq", "multipass": "qres"})
    return settings


def basic_ini(rec: Recommendation, name: str, screen: Size) -> str:
    (base_width, base_height), (out_width, out_height) = video_sizes(rec, screen)
    scaled = (base_width, base_height) != (out_width, out_height)
    sections: List[Tuple[str, List[Tuple[str, Setting]]]] = [
        ("General", [("Name", name)]),
        ("Output", [("Mode", "Advanced")]),
        ("AdvOut", [
            ("Encoder", ENCODER_IDS[rec.encoder]),
            ("TrackIndex", 1),
            ("AudioEncoder", "ffmpeg_aac"),
            ("Track1Bitrate", rec.audio_kbps),
            ("UseRescale", "false"),
            # when on, obs clamps the encoder to the service's own limits and can undo the recommended bitrate
            ("ApplyServiceSettings", "false"),
        ]),
        ("Video", [
            ("BaseCX", base_width),
            ("BaseCY", base_height),
            ("OutputCX", out_width),
            ("OutputCY", out_height),
            ("FPSType", 0),
            ("FPSCommon", rec.tier.fps),
            # lanczos keeps text readable when a bigger canvas is scaled down
            ("ScaleType", "lanczos" if scaled else "bicubic"),
        ]),
        ("Audio", [("SampleRate", AUDIO_SAMPLE_RATE), ("ChannelSetup", "Stereo")]),
    ]
    lines: List[str] = []
    for section, values in sections:
        lines.append(f"[{section}]")
        lines.extend(f"{key}={value}" for key, value in values)
        lines.append("")
    return "\n".join(lines)


def write_profile(rec: Recommendation, parent: Path, screen: Size) -> Path:
    name = _UNSAFE_NAME.sub("", profile_name(rec)).strip()
    folder = parent / name
    number = 2
    # never write into an existing folder, it may be an earlier export the user already tweaked
    while folder.exists():
        folder = parent / f"{name} ({number})"
        number += 1
    try:
        folder.mkdir(parents=True)
        # obs saves its ini files as utf-8 with a bom, bytes keep the line endings exactly as written
        (folder / "basic.ini").write_bytes(basic_ini(rec, folder.name, screen).encode("utf-8-sig"))
        (folder / "streamEncoder.json").write_bytes(json.dumps(encoder_settings(rec)).encode("utf-8"))
    except OSError as exc:
        raise ProfileError(f"Could not save the profile in {parent}. Pick a folder you can write to.", str(exc))
    return folder
