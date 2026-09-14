# customtkinter ships without type hints for most of its api
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
from __future__ import annotations

from tkinter import Event, Misc
from typing import Any, Sequence

import customtkinter as ctk

from ui.theme import COLORS, TONES, Weight, font, wrap_width


def text_label(master: Misc, text: str = "", size: int = 13, weight: Weight = "normal", color: str = "text", wrap: int = 0, **options: Any) -> ctk.CTkLabel:
    # color is a theme key or a hex value
    return ctk.CTkLabel(master, text=text, font=font(size, weight), text_color=COLORS.get(color, color),
                        anchor=options.pop("anchor", "w"), justify="left", wraplength=wrap, **options)


def fit_wraplength(container: Misc, labels: Sequence[ctk.CTkLabel], padding: int, minimum: int = 80) -> None:
    # a fixed wraplength either overflows narrow boxes or wastes space in wide ones,
    # labels is read on every resize so callers may keep adding to the same list
    def update(event: Event[Misc]) -> None:
        width = wrap_width(container, max(event.width - padding, minimum))
        for label in labels:
            label.configure(wraplength=width)

    container.bind("<Configure>", update, add="+")


class Pill(ctk.CTkLabel):
    def __init__(self, master: Misc, text: str = "", tone: str = "neutral") -> None:
        super().__init__(master, text=text, height=24, corner_radius=12, padx=10, font=font(12, "bold"))
        self.set(text, tone)

    def set(self, text: str, tone: str) -> None:
        bg, fg = TONES[tone]
        self.configure(text=text, fg_color=bg, text_color=fg)


class Card(ctk.CTkFrame):
    def __init__(self, master: Misc, title: str) -> None:
        super().__init__(master, fg_color=COLORS["card"], corner_radius=14, border_width=1, border_color=COLORS["border"])
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.header = ctk.CTkFrame(self, fg_color="transparent")
        self.header.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 10))
        self.header.grid_columnconfigure(0, weight=1)
        text_label(self.header, title, 16, "bold").grid(row=0, column=0, sticky="w")

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 16))


class Tile(ctk.CTkFrame):
    def __init__(self, master: Misc, caption: str) -> None:
        super().__init__(master, fg_color=COLORS["tile"], corner_radius=10)
        text_label(self, caption.upper(), 11, "bold", "muted").pack(fill="x", padx=14, pady=(10, 0))
        self._value = text_label(self, "-", 17, "bold")
        self._value.pack(fill="x", padx=14, pady=(0, 10))
        fit_wraplength(self, [self._value], padding=32)

    def set(self, text: str) -> None:
        self._value.configure(text=text)


class Metric(ctk.CTkFrame):
    def __init__(self, master: Misc, caption: str, unit: str) -> None:
        super().__init__(master, fg_color=COLORS["tile"], corner_radius=10)
        text_label(self, caption.upper(), 11, "bold", "muted").pack(fill="x", padx=12, pady=(10, 0))
        self._value = text_label(self, "-", 24, "bold")
        self._value.pack(fill="x", padx=12)
        text_label(self, unit, 11, color="muted").pack(fill="x", padx=12, pady=(0, 10))

    def set(self, text: str) -> None:
        self._value.configure(text=text)
