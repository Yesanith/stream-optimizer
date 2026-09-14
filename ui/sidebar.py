# customtkinter ships without type hints for most of its api
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
from __future__ import annotations

from tkinter import Event, Misc
from typing import Callable

import customtkinter as ctk

from modules.platforms import PLATFORMS, platform_by_name
from ui.theme import APP_NAME, APP_VERSION, COLORS, PLATFORM_COLORS, font
from ui.widgets import text_label

SCAN_TEXT = "1   Scan Hardware"
SCANNING_TEXT = "1   Scanning..."
SPEED_TEXT = "2   Run Speed Test"
TESTING_TEXT = "2   Testing..."
GENERATE_TEXT = "3   Generate Recommended Settings"


class Sidebar(ctk.CTkFrame):
    def __init__(self, master: Misc, on_platform_change: Callable[[str], None], on_scan: Callable[[], None],
                 on_speed_test: Callable[[], None], on_generate: Callable[[], None]) -> None:
        super().__init__(master, width=330, corner_radius=0, fg_color=COLORS["sidebar"])
        self._on_platform_change = on_platform_change
        self._on_generate = on_generate
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(20, weight=1)

        text_label(self, APP_NAME, 24, "bold").grid(row=0, column=0, sticky="ew", padx=24, pady=(28, 0))
        text_label(self, "OBS settings matched to your PC and your connection.", color="muted", wrap=280).grid(
            row=1, column=0, sticky="ew", padx=24, pady=(4, 24))

        self._section(2, "Platform")
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=3, column=0, sticky="ew", padx=24)
        row.grid_columnconfigure(1, weight=1)
        self._dot = ctk.CTkFrame(row, width=12, height=12, corner_radius=6, fg_color=COLORS["accent"])
        self._dot.grid(row=0, column=0, padx=(0, 10))
        self._menu = ctk.CTkOptionMenu(
            row, values=[p.name for p in PLATFORMS.values()], command=self._platform_selected,
            height=38, corner_radius=10, font=font(14, "bold"), dropdown_font=font(14),
            fg_color=COLORS["secondary"], button_color=COLORS["secondary_hover"], button_hover_color=COLORS["border"],
        )
        self._menu.grid(row=0, column=1, sticky="ew")
        self._hint = text_label(self, size=12, color="muted")
        self._hint.grid(row=4, column=0, sticky="ew", padx=24, pady=(6, 22))

        self._section(5, "Steps")
        self._scan = self._button(6, SCAN_TEXT, on_scan, primary=False)
        self._speed = self._button(7, SPEED_TEXT, on_speed_test, primary=False)
        self._button(8, GENERATE_TEXT, on_generate, primary=True)

        self._section(9, "Manual upload (optional)", top=22)
        self._manual = ctk.CTkEntry(self, height=38, corner_radius=10, placeholder_text="Upload in Mbps, e.g. 12.5",
                                    fg_color=COLORS["secondary"], border_color=COLORS["border"], font=font(14))
        self._manual.grid(row=10, column=0, sticky="ew", padx=24)
        self._manual.bind("<Return>", self._manual_submitted)
        text_label(self, "If filled, this value is used instead of the speed test result. Handy when the test fails.",
                   size=12, color="muted", wrap=280).grid(row=11, column=0, sticky="ew", padx=24, pady=(6, 0))

        text_label(self, f"v{APP_VERSION}", size=12, color="muted").grid(row=21, column=0, sticky="ew", padx=24, pady=18)
        self._show_platform(self.platform_key)

    @property
    def platform_key(self) -> str:
        return platform_by_name(str(self._menu.get())).key

    @property
    def manual_upload(self) -> str:
        return str(self._manual.get()).strip()

    def set_scanning(self, busy: bool) -> None:
        self._scan.configure(state="disabled" if busy else "normal", text=SCANNING_TEXT if busy else SCAN_TEXT)

    def set_testing(self, busy: bool) -> None:
        self._speed.configure(state="disabled" if busy else "normal", text=TESTING_TEXT if busy else SPEED_TEXT)

    def _section(self, row: int, text: str, top: int = 0) -> None:
        text_label(self, text.upper(), 11, "bold", "muted").grid(row=row, column=0, sticky="ew", padx=24, pady=(top, 6))

    def _button(self, row: int, text: str, command: Callable[[], None], primary: bool) -> ctk.CTkButton:
        button = ctk.CTkButton(
            self, text=text, command=command, height=42, corner_radius=10, anchor="w", font=font(14, "bold"),
            fg_color=COLORS["accent"] if primary else COLORS["secondary"],
            hover_color=COLORS["accent_hover"] if primary else COLORS["secondary_hover"],
            text_color=COLORS["text"],
        )
        button.grid(row=row, column=0, sticky="ew", padx=24, pady=4)
        return button

    def _show_platform(self, key: str) -> None:
        platform = PLATFORMS[key]
        self._dot.configure(fg_color=PLATFORM_COLORS[key])
        self._hint.configure(text=f"Bitrate cap {platform.max_bitrate_kbps:,} Kbps  ·  up to {platform.max_height}p")

    def _platform_selected(self, name: str) -> None:
        key = platform_by_name(name).key
        self._show_platform(key)
        self._on_platform_change(key)

    def _manual_submitted(self, _event: Event[Misc]) -> None:
        self._on_generate()
