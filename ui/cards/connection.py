# customtkinter ships without type hints for most of its api
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
from __future__ import annotations

from tkinter import Misc
from typing import Dict, Optional, Tuple

import customtkinter as ctk

from modules.ingest import IngestReport, latency_rating
from modules.platforms import Platform
from modules.speed_test import SpeedTestResult
from ui.theme import COLORS, LATENCY_TONES, TONES
from ui.widgets import Card, Metric, Pill, fit_wraplength, text_label

# label, overall progress at stage start, overall progress at stage end
STAGES: Dict[str, Tuple[str, float, float]] = {
    "connecting": ("Connecting to speedtest.net", 0.00, 0.05),
    "server": ("Finding the closest server", 0.05, 0.15),
    "download": ("Measuring download", 0.15, 0.55),
    "upload": ("Measuring upload", 0.55, 1.00),
    "done": ("Finishing", 1.00, 1.00),
}

RATING_LABELS = {"good": "Good", "fair": "Fair", "poor": "High latency"}


class IngestBox(ctk.CTkFrame):
    def __init__(self, master: Misc) -> None:
        super().__init__(master, fg_color=COLORS["tile"], corner_radius=10)
        self.grid_columnconfigure(0, weight=1)
        self._caption = text_label(self, size=11, weight="bold", color="muted")
        self._caption.grid(row=0, column=0, sticky="w", padx=12, pady=(8, 0))
        self._rating = Pill(self)
        self._rating.grid(row=0, column=1, sticky="e", padx=12, pady=(8, 0))
        self._value = text_label(self, "-", 15, "bold")
        self._value.grid(row=1, column=0, columnspan=2, sticky="w", padx=12)
        self._detail = text_label(self, size=12, color="muted")
        self._detail.grid(row=2, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 8))
        fit_wraplength(self, [self._value, self._detail], padding=28, minimum=120)

    def show_idle(self, platform: Platform) -> None:
        self._show(platform, "-", "Checked when you run the speed test or generate settings.")

    def show_checking(self, platform: Platform) -> None:
        self._show(platform, "Checking...", f"Measuring latency to {platform.name} ingest servers.")

    def show_error(self, platform: Platform, message: str) -> None:
        self._show(platform, "Unavailable", message, value_color=TONES["warning"][1])

    def show_report(self, platform: Platform, report: IngestReport) -> None:
        best = report.recommended
        if best is None or best.latency_ms is None:
            if report.servers:
                self._show(platform, "No server answered", report.note, value_color=TONES["warning"][1])
            else:
                self._show(platform, "Set by your platform", report.note)
            return
        self._show(platform, f"{best.name}  ·  {best.latency_ms:.0f} ms", f"{best.url}\n{report.note}", rating=latency_rating(best.latency_ms))

    def _show(self, platform: Platform, value: str, detail: str, value_color: str = COLORS["text"], rating: Optional[str] = None) -> None:
        self._caption.configure(text=f"{platform.name} ingest server".upper())
        self._value.configure(text=value, text_color=value_color)
        self._detail.configure(text=detail)
        if rating is None:
            self._rating.grid_remove()
        else:
            self._rating.set(RATING_LABELS[rating], LATENCY_TONES[rating])
            self._rating.grid()


class ConnectionCard(Card):
    def __init__(self, master: Misc) -> None:
        super().__init__(master, "Connection")
        self._pill = Pill(self.header, "Not tested")
        self._pill.grid(row=0, column=1)

        body = self.body
        body.grid_columnconfigure((0, 1, 2), weight=1, uniform="metrics")
        self._metrics: Dict[str, Metric] = {}
        for column, (key, unit) in enumerate((("Download", "Mbps"), ("Upload", "Mbps"), ("Ping", "ms"))):
            metric = Metric(body, key, unit)
            metric.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 4, 0 if column == 2 else 4))
            self._metrics[key] = metric

        self._progress = ctk.CTkProgressBar(body, height=8, corner_radius=4, progress_color=COLORS["accent"], fg_color=COLORS["tile"])
        self._progress.set(0)
        self._progress.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(14, 6))
        self._stage = text_label(body, "Run the speed test to measure your real upload speed.", 12, color="muted")
        self._stage.grid(row=2, column=0, columnspan=3, sticky="w")
        self._server = text_label(body, size=12, color="muted")
        self._server.grid(row=3, column=0, columnspan=3, sticky="w")
        fit_wraplength(body, [self._stage, self._server], padding=0, minimum=200)

        self.ingest = IngestBox(body)
        self.ingest.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 0))

    def show_testing(self) -> None:
        self._pill.set("Testing", "busy")
        self._progress.set(0)
        for metric in self._metrics.values():
            metric.set("-")
        self._stage.configure(text="Starting...", text_color=COLORS["muted"])
        self._server.configure(text="")

    def show_progress(self, stage: str, fraction: float, measured: Dict[str, float]) -> None:
        text, start, end = STAGES.get(stage, (stage, 0.0, 0.0))
        self._progress.set(start + (end - start) * fraction)
        suffix = f"  {int(fraction * 100)}%" if stage in ("download", "upload") else ""
        self._stage.configure(text=f"{text}...{suffix}")
        self._show_metrics(measured.get("download_mbps"), measured.get("upload_mbps"), measured.get("ping_ms"))

    def show_result(self, result: SpeedTestResult) -> None:
        self._pill.set("Done", "ok")
        self._progress.set(1)
        self._show_metrics(result.download_mbps, result.upload_mbps, result.ping_ms)
        self._stage.configure(text="Speed test finished.", text_color=COLORS["muted"])
        self._server.configure(text=f"Server: {result.server}")

    def show_error(self, message: str) -> None:
        self._pill.set("Failed", "critical")
        self._progress.set(0)
        self._stage.configure(text=message, text_color=TONES["critical"][1])
        self._server.configure(text="You can type your upload speed into the manual field in the sidebar instead.")

    def _show_metrics(self, download: Optional[float], upload: Optional[float], ping: Optional[float]) -> None:
        for key, value, fmt in (("Download", download, "{:.1f}"), ("Upload", upload, "{:.1f}"), ("Ping", ping, "{:.0f}")):
            if value is not None:
                self._metrics[key].set(fmt.format(value))
