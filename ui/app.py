# customtkinter ships without type hints for most of its api
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Dict, List, Optional, Tuple

import customtkinter as ctk

from modules.ingest import IngestReport, check_ingest
from modules.network_check import PreflightResult, run_preflight
from modules.obs_profile import ProfileError, write_profile
from modules.platforms import PLATFORMS
from modules.recommender import Recommendation, recommend
from modules.speed_test import SpeedTestResult, run_speed_test
from modules.system_info import SystemInfo, scan_system
from ui.cards import ConnectionCard, HardwareCard, Note, NotesCard, SettingsCard
from ui.sidebar import Sidebar
from ui.tasks import TaskRunner
from ui.theme import APP_NAME, COLORS, TONES
from ui.widgets import fit_wraplength, text_label
from ui.window import paint_window_background

UNCHECKED_WARNING = "The connection check before this test failed and the test was run anyway, so treat the result with caution."


class StreamOptimizerApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1220x940")
        self.minsize(1080, 880)
        self.configure(fg_color=COLORS["bg"])

        self.system: Optional[SystemInfo] = None
        self.speed: Optional[SpeedTestResult] = None
        self.recommendation: Optional[Recommendation] = None
        self.recommendation_source = ""
        # why the last connection check or speed test failed, shown at the top of the notes
        self.connection_problem: Optional[str] = None
        # per platform key, cleared whenever a new speed test starts
        self.ingest: Dict[str, IngestReport] = {}
        self.ingest_errors: Dict[str, str] = {}
        # bumped when a speed test starts, so a latency check that overlapped it can't leave inflated numbers behind
        self._ingest_round = 0
        self.tasks = TaskRunner(self)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.sidebar = Sidebar(self, on_platform_change=self._on_platform_change, on_scan=self.scan_hardware,
                               on_speed_test=self.run_speed_test, on_generate=self.generate)
        self.sidebar.grid(row=0, column=0, sticky="nsw")

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=0, column=1, sticky="nsew", padx=22, pady=22)
        content.grid_columnconfigure((0, 1), weight=1, uniform="top")
        content.grid_rowconfigure(2, weight=1)

        self.hardware = HardwareCard(content)
        self.hardware.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 16))
        self.connection = ConnectionCard(content)
        self.connection.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 16))
        self.settings = SettingsCard(content, on_copy=self.copy_settings, on_export=self.export_profile)
        self.settings.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(0, 16))
        self.notes = NotesCard(content)
        self.notes.grid(row=2, column=0, columnspan=2, sticky="nsew")
        self.status = text_label(content, "Start by scanning your hardware.", 12, color="muted")
        self.status.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        fit_wraplength(content, [self.status], padding=0)

        self._render_ingest()
        paint_window_background(self, COLORS["bg"])
        self.protocol("WM_DELETE_WINDOW", self.close)

    def close(self) -> None:
        self.tasks.stop()
        self.destroy()

    def set_status(self, text: str, tone: str = "neutral") -> None:
        self.status.configure(text=text, text_color=COLORS["muted"] if tone == "neutral" else TONES[tone][1])

    def scan_hardware(self) -> None:
        if not self.tasks.run("scan", scan_system, self._on_scan_done, self._on_scan_failed):
            return
        self.sidebar.set_scanning(True)
        self.hardware.show_scanning()
        self.set_status("Reading CPU, RAM and GPU information...")

    def run_speed_test(self) -> None:
        if self._line_busy():
            return
        self.tasks.run("preflight", run_preflight, self._on_preflight_done, self._on_preflight_crashed)
        self._begin_connection_test()
        self.connection.show_progress("preflight", 0.0, {})
        self.set_status("Checking your connection before the speed test...")

    def generate(self) -> None:
        if self.system is None:
            self.set_status("Scan your hardware first.", "warning")
            return
        try:
            upload, source = self._upload_source()
        except ValueError as exc:
            self.set_status(str(exc), "warning")
            return

        ping = self.speed.ping_ms if self.speed else None
        try:
            rec = recommend(self.sidebar.platform_key, self.system, upload, ping)
        except ValueError as exc:
            self.set_status(f"Could not build a recommendation: {exc}", "critical")
            return

        self.recommendation = rec
        self.recommendation_source = source
        self.settings.show(rec)
        self._render_notes()
        self.set_status(f"Settings generated for {rec.platform.name} using {upload:g} Mbps upload from {source}.")
        self._check_ingest(rec.platform.key)

    def copy_settings(self) -> None:
        if self.recommendation is None:
            return
        text = self.recommendation.as_text()
        report = self.ingest.get(self.recommendation.platform.key)
        if report is not None and report.recommended is not None:
            text += f"\nServer: {report.recommended.name} ({report.recommended.url})"
        self.clipboard_clear()
        self.clipboard_append(text)
        self.set_status("Settings copied to clipboard.", "ok")

    def export_profile(self) -> None:
        if self.recommendation is None:
            return
        documents = Path.home() / "Documents"
        parent = filedialog.askdirectory(parent=self, title="Choose where to save the OBS profile", mustexist=True,
                                         initialdir=str(documents if documents.is_dir() else Path.home()))
        if not parent:
            return
        try:
            folder = write_profile(self.recommendation, Path(parent), (self.winfo_screenwidth(), self.winfo_screenheight()))
        except ProfileError as exc:
            self.set_status(exc.message, "critical")
            return
        self.set_status(f"Saved profile \"{folder.name}\". In OBS 31 or newer use Profile > Import on that folder, then add your stream key in Settings > Stream.", "ok")

    def _refresh_recommendation(self) -> None:
        if self.recommendation is not None:
            self.generate()

    def _render_notes(self) -> None:
        notes: List[Note] = []
        if self.connection_problem:
            notes.append(("critical", self.connection_problem))
        rec = self.recommendation
        if self.speed is not None and (rec is None or self.recommendation_source == "speed test"):
            notes += [("warning", w) for w in self.speed.warnings]
        if rec is not None:
            notes += [(a.level, a.message) for a in rec.advice]
            self.notes.show(notes or [("ok", "No issues found. These settings should run smoothly.")])
        elif notes:
            self.notes.show(notes)
        else:
            self.notes.show_intro()

    def _on_platform_change(self, key: str) -> None:
        self._render_ingest()
        if self.speed is not None:
            self._check_ingest(key)
        self._refresh_recommendation()

    def _on_scan_done(self, system: SystemInfo) -> None:
        self.system = system
        self.sidebar.set_scanning(False)
        self.hardware.show_system(system)
        if system.errors:
            self.set_status("Hardware scan finished with some gaps, see the Hardware card.", "warning")
        else:
            self.set_status("Hardware scan finished.")
        self._refresh_recommendation()

    def _on_scan_failed(self, message: str) -> None:
        self.sidebar.set_scanning(False)
        self.hardware.show_error(message)
        self.set_status("Hardware scan failed. Try again, or restart the app.", "critical")

    def _line_busy(self) -> bool:
        return self.tasks.is_running("preflight") or self.tasks.is_running("speed")

    def _begin_connection_test(self) -> None:
        self.connection_problem = None
        self.sidebar.set_testing(True)
        self.connection.show_testing()
        self.ingest.clear()
        self.ingest_errors.clear()
        self._ingest_round += 1
        self._render_ingest()
        self._render_notes()

    def _on_preflight_done(self, result: PreflightResult) -> None:
        if result.ok:
            self._start_speed_test(result.warnings)
            return

        self.sidebar.set_testing(False)
        self.connection.show_error("Connection check failed, the speed test did not run. See the notes below for what to check.", pill="No connection")
        self._render_ingest()
        self.connection_problem = result.message
        self._render_notes()
        self.set_status("Connection check failed, the speed test did not run.", "critical")
        # the check can be wrong, for example on a network that only lets the real test traffic through, so the user gets the last word
        if messagebox.askyesno("Connection check failed", f"{result.message}\n\nRun the speed test anyway?", icon="warning", parent=self):
            self._begin_connection_test()
            self._start_speed_test([UNCHECKED_WARNING])

    def _on_preflight_crashed(self, message: str) -> None:
        # the check is only advisory, a bug in it must not keep the real test from running
        self._start_speed_test([])

    def _start_speed_test(self, warnings: List[str]) -> None:
        def work() -> SpeedTestResult:
            result = run_speed_test(self._report_speed)
            return replace(result, warnings=warnings + result.warnings)

        self.tasks.run("speed", work, self._on_speed_done, self._on_speed_failed)
        self._render_ingest()
        self.set_status("Speed test running, this takes about 20 seconds.")

    def _report_speed(self, stage: str, fraction: float, measured: Dict[str, float]) -> None:
        # runs on the speed test threads, hop back to the tk thread before touching widgets
        self.tasks.post(lambda: self.connection.show_progress(stage, fraction, measured))

    def _on_speed_done(self, result: SpeedTestResult) -> None:
        self.speed = result
        self.sidebar.set_testing(False)
        self.connection.show_result(result)
        self.set_status("Speed test finished." if not result.warnings else "Speed test finished with warnings, see the notes.",
                        "neutral" if not result.warnings else "warning")
        self._render_notes()
        self._check_ingest(self.sidebar.platform_key)
        self._refresh_recommendation()

    def _on_speed_failed(self, message: str) -> None:
        self.sidebar.set_testing(False)
        self.connection.show_error("Speed test failed. See the notes below for what to check.")
        self.connection_problem = message
        self._render_notes()
        self.set_status("Speed test failed.", "critical")
        self._check_ingest(self.sidebar.platform_key)

    def _check_ingest(self, key: str) -> None:
        # a line saturated by the speed test inflates every latency and can pick the wrong server
        if key in self.ingest or self._line_busy():
            self._render_ingest()
            return

        round_started = self._ingest_round

        def work() -> IngestReport:
            return check_ingest(key)

        def done(report: IngestReport) -> None:
            if round_started != self._ingest_round:
                # measured while a speed test loaded the line, measure again once it is idle
                self._check_ingest(key)
                return
            self.ingest[key] = report
            self._render_ingest()

        def failed(message: str) -> None:
            if round_started != self._ingest_round:
                self._check_ingest(key)
                return
            self.ingest_errors[key] = message
            self._render_ingest()

        if self.tasks.run(f"ingest:{key}", work, done, failed):
            self.ingest_errors.pop(key, None)
            self._render_ingest()

    def _render_ingest(self) -> None:
        key = self.sidebar.platform_key
        platform = PLATFORMS[key]
        box = self.connection.ingest
        if self.tasks.is_running(f"ingest:{key}"):
            box.show_checking(platform)
        elif key in self.ingest_errors:
            box.show_error(platform, self.ingest_errors[key])
        elif key in self.ingest:
            box.show_report(platform, self.ingest[key])
        elif self._line_busy():
            box.show_waiting(platform)
        else:
            box.show_idle(platform)

    def _upload_source(self) -> Tuple[float, str]:
        raw = self.sidebar.manual_upload.replace(",", ".")
        if raw:
            try:
                value = float(raw)
            except ValueError:
                raise ValueError("Manual upload must be a number, like 12.5.") from None
            if not math.isfinite(value):
                raise ValueError("Manual upload must be a number, like 12.5.")
            if value <= 0:
                raise ValueError("Manual upload must be greater than 0.")
            return value, "manual entry"
        if self.speed is not None:
            return self.speed.upload_mbps, "speed test"
        raise ValueError("Run the speed test or type your upload speed into the manual field.")


def run() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    StreamOptimizerApp().mainloop()
