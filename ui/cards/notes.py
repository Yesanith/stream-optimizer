# customtkinter ships without type hints for most of its api
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
from __future__ import annotations

from tkinter import Misc
from typing import List, Sequence, Tuple

import customtkinter as ctk

from ui.theme import COLORS, TONES, font, wrap_width
from ui.widgets import Card, fit_wraplength, text_label

# level, message
Note = Tuple[str, str]

TAGS = {"critical": "CRITICAL", "warning": "WARNING", "info": "TIP", "ok": "OK"}
TAG_SPACE = 140


class NotesCard(Card):
    def __init__(self, master: Misc) -> None:
        super().__init__(master, "Notes")
        self._list = ctk.CTkScrollableFrame(self.body, fg_color="transparent", height=150)
        self._list.pack(fill="both", expand=True)
        self._list.grid_columnconfigure(0, weight=1)
        self._labels: List[ctk.CTkLabel] = []
        fit_wraplength(self._list, self._labels, padding=TAG_SPACE, minimum=300)
        self.show([("info", "Scan your hardware and run a speed test, then generate your settings.")])

    def show(self, notes: Sequence[Note]) -> None:
        for child in self._list.winfo_children():
            child.destroy()
        self._labels.clear()
        wrap = wrap_width(self, max(self._list.winfo_width() - TAG_SPACE, 400))
        for row, (level, message) in enumerate(notes):
            bg, fg = TONES[level]
            item = ctk.CTkFrame(self._list, fg_color=COLORS["tile"], corner_radius=8)
            item.grid(row=row, column=0, sticky="ew", pady=3)
            item.grid_columnconfigure(1, weight=1)
            tag = ctk.CTkLabel(item, text=TAGS[level], width=78, height=22, corner_radius=11, fg_color=bg, text_color=fg, font=font(11, "bold"))
            tag.grid(row=0, column=0, padx=(10, 12), pady=10, sticky="n")
            label = text_label(item, message, wrap=wrap)
            label.grid(row=0, column=1, sticky="w", padx=(0, 12), pady=8)
            self._labels.append(label)
