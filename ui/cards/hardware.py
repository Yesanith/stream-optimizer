# customtkinter ships without type hints for most of its api
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
from __future__ import annotations

from tkinter import Misc
from typing import Dict

import customtkinter as ctk

from modules.system_info import SystemInfo
from ui.theme import TONES
from ui.widgets import Card, Pill, fit_wraplength, text_label

ROWS = ("CPU", "Cores", "RAM", "GPU")
ENCODERS = ("NVENC", "AMF", "QSV")


class HardwareCard(Card):
    def __init__(self, master: Misc) -> None:
        super().__init__(master, "Hardware")
        self._pill = Pill(self.header, "Not scanned")
        self._pill.grid(row=0, column=1)

        body = self.body
        body.grid_columnconfigure(1, weight=1)
        self._values: Dict[str, ctk.CTkLabel] = {}
        for row, key in enumerate(ROWS):
            text_label(body, key, color="muted", width=64, anchor="nw").grid(row=row, column=0, sticky="nw", pady=3)
            value = text_label(body, "-", weight="bold")
            value.grid(row=row, column=1, sticky="w", pady=3)
            self._values[key] = value

        text_label(body, "Encoders", color="muted", width=64).grid(row=4, column=0, sticky="w", pady=(8, 0))
        pills = ctk.CTkFrame(body, fg_color="transparent")
        pills.grid(row=4, column=1, sticky="w", pady=(8, 0))
        self._encoders: Dict[str, Pill] = {}
        for column, name in enumerate(ENCODERS):
            pill = Pill(pills, name)
            pill.grid(row=0, column=column, padx=(0, 6))
            self._encoders[name] = pill

        self._error = text_label(body, size=12, color=TONES["warning"][1])
        self._error.grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))

        fit_wraplength(body, list(self._values.values()), padding=80)
        fit_wraplength(body, [self._error], padding=0)

    def show_scanning(self) -> None:
        self._pill.set("Scanning", "busy")

    def show_system(self, system: SystemInfo) -> None:
        gpu_lines = [f"{g.name} ({g.vram_mb / 1024:.0f} GB)" if g.vram_mb else g.name for g in system.gpus]
        self._values["CPU"].configure(text=system.cpu_name)
        self._values["Cores"].configure(text=f"{system.physical_cores} cores / {system.logical_cores} threads")
        self._values["RAM"].configure(text=f"{system.ram_gb:g} GB" if system.ram_gb else "Unknown")
        self._values["GPU"].configure(text="\n".join(gpu_lines) or "Not detected")

        for name, available in (("NVENC", system.has_nvenc), ("AMF", system.has_amf), ("QSV", system.has_qsv)):
            self._encoders[name].set(f"{name} {'✓' if available else '✗'}", "ok" if available else "neutral")

        self._error.configure(text="\n".join(system.errors))
        self._pill.set("Partial", "warning") if system.errors else self._pill.set("Done", "ok")

    def show_error(self, message: str) -> None:
        self._pill.set("Failed", "critical")
        self._error.configure(text=f"Hardware scan failed: {message}")
