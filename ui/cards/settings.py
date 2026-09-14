# customtkinter ships without type hints for most of its api
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
from __future__ import annotations

from tkinter import Misc
from typing import Callable, Dict

import customtkinter as ctk

from modules.recommender import Recommendation
from ui.theme import COLORS, font
from ui.widgets import Card, Pill, Tile, text_label

CAPTIONS = ("Resolution", "FPS", "Video Bitrate", "Keyframe Interval", "Encoder", "Preset", "Rate Control", "Audio Bitrate")
OBS_HINT = "In OBS: Settings > Output (Output Mode: Advanced) > Streaming for the encoder, Settings > Video for resolution and FPS."


def display_values(rec: Recommendation) -> Dict[str, str]:
    return {
        "Resolution": f"{rec.tier.width}x{rec.tier.height}",
        "FPS": str(rec.tier.fps),
        "Video Bitrate": f"{rec.video_kbps:,} Kbps",
        "Keyframe Interval": f"{rec.keyframe_s} s",
        "Encoder": rec.encoder_name,
        "Preset": rec.preset,
        "Rate Control": rec.rate_control,
        "Audio Bitrate": f"{rec.audio_kbps} Kbps",
    }


class SettingsCard(Card):
    def __init__(self, master: Misc, on_copy: Callable[[], None]) -> None:
        super().__init__(master, "Recommended OBS Settings")
        self._pill = Pill(self.header, "Waiting")
        self._pill.grid(row=0, column=1, padx=(0, 8))
        self._copy = ctk.CTkButton(self.header, text="Copy", width=80, height=28, corner_radius=8, font=font(13, "bold"),
                                   fg_color=COLORS["secondary"], hover_color=COLORS["secondary_hover"], command=on_copy, state="disabled")
        self._copy.grid(row=0, column=2)

        body = self.body
        body.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="tiles")
        self._tiles: Dict[str, Tile] = {}
        for index, caption in enumerate(CAPTIONS):
            tile = Tile(body, caption)
            tile.grid(row=index // 4, column=index % 4, sticky="nsew", padx=4, pady=4)
            self._tiles[caption] = tile
        text_label(body, OBS_HINT, 12, color="muted").grid(row=2, column=0, columnspan=4, sticky="ew", padx=4, pady=(6, 0))

    def show(self, rec: Recommendation) -> None:
        for caption, text in display_values(rec).items():
            self._tiles[caption].set(text)
        worst = rec.advice[0].level if rec.advice else "ok"
        self._pill.set(f"{rec.platform.name} · {rec.tier.label}", worst if worst in ("critical", "warning") else "ok")
        self._copy.configure(state="normal")
