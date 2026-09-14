# customtkinter ships without type hints for most of its api
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
from __future__ import annotations

from tkinter import Misc
from typing import Dict, Literal, Tuple

import customtkinter as ctk

APP_NAME = "Stream Optimizer"
APP_VERSION = "1.1.0"

COLORS: Dict[str, str] = {
    "bg": "#0e1016",
    "sidebar": "#141722",
    "card": "#1a1e2a",
    "tile": "#222736",
    "border": "#2a3043",
    "text": "#e7e9f0",
    "muted": "#8a90a6",
    "accent": "#7c5cff",
    "accent_hover": "#6947e6",
    "secondary": "#262c3d",
    "secondary_hover": "#30374b",
}

# background, foreground
TONES: Dict[str, Tuple[str, str]] = {
    "neutral": ("#262b3a", "#9aa1b5"),
    "busy": ("#2a2350", "#a993ff"),
    "ok": ("#12352a", "#3ecf8e"),
    "info": ("#15263d", "#5aa9ff"),
    "warning": ("#3a2e12", "#f5b942"),
    "critical": ("#3d1a20", "#ff5c6c"),
}

PLATFORM_COLORS: Dict[str, str] = {"twitch": "#9146ff", "kick": "#53fc18", "youtube": "#ff3040", "other": COLORS["accent"]}

LATENCY_TONES: Dict[str, str] = {"good": "ok", "fair": "warning", "poor": "critical"}

Weight = Literal["normal", "bold"]


def font(size: int, weight: Weight = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(size=size, weight=weight)


def wrap_width(widget: Misc, pixels: int) -> int:
    # event sizes are real pixels but ctk scales wraplength again on hidpi screens
    return int(pixels / ctk.ScalingTracker.get_widget_scaling(widget))
