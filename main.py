from __future__ import annotations

import queue
import threading
from typing import Dict, List, Optional, Tuple

import customtkinter as ctk

from modules.recommender import PLATFORMS, Recommendation, recommend
from modules.speed_test import SpeedTestError, SpeedTestResult, run_speed_test
from modules.system_info import SystemInfo, scan_system


APP_NAME = "Stream Optimizer"
APP_VERSION = "1.0.0"

COLORS = {
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
TONES = {
    "neutral": ("#262b3a", "#9aa1b5"),
    "busy": ("#2a2350", "#a993ff"),
    "ok": ("#12352a", "#3ecf8e"),
    "info": ("#15263d", "#5aa9ff"),
    "warning": ("#3a2e12", "#f5b942"),
    "critical": ("#3d1a20", "#ff5c6c"),
}

PLATFORM_COLORS = {"twitch": "#9146ff", "kick": "#53fc18", "youtube": "#ff3040", "other": COLORS["accent"]}

STAGES = {
    "connecting": ("Connecting to speedtest.net", 0.00, 0.05),
    "server": ("Finding the closest server", 0.05, 0.15),
    "download": ("Measuring download", 0.15, 0.55),
    "upload": ("Measuring upload", 0.55, 1.00),
    "done": ("Finishing", 1.00, 1.00),
}


def font(size: int, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(size=size, weight=weight)


class Pill(ctk.CTkLabel):
    def __init__(self, master, text: str = "", tone: str = "neutral"):
        super().__init__(master, text=text, height=24, corner_radius=12, padx=10, font=font(12, "bold"))
        self.set(text, tone)

    def set(self, text: str, tone: str) -> None:
        bg, fg = TONES[tone]
        self.configure(text=text, fg_color=bg, text_color=fg)


class Card(ctk.CTkFrame):
    def __init__(self, master, title: str):
        super().__init__(master, fg_color=COLORS["card"], corner_radius=14, border_width=1, border_color=COLORS["border"])
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.header = ctk.CTkFrame(self, fg_color="transparent")
        self.header.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 10))
        self.header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.header, text=title, font=font(16, "bold"), text_color=COLORS["text"]).grid(row=0, column=0, sticky="w")

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 16))


class Tile(ctk.CTkFrame):
    def __init__(self, master, caption: str):
        super().__init__(master, fg_color=COLORS["tile"], corner_radius=10)
        ctk.CTkLabel(self, text=caption.upper(), font=font(11, "bold"), text_color=COLORS["muted"], anchor="w").pack(fill="x", padx=14, pady=(10, 0))
        self.value = ctk.CTkLabel(self, text="-", font=font(17, "bold"), text_color=COLORS["text"], anchor="w", justify="left", wraplength=150)
        self.value.pack(fill="x", padx=14, pady=(0, 10))
        self.bind("<Configure>", lambda e: self.value.configure(wraplength=max(e.width - 32, 80)))


class StreamOptimizerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1220x880")
        self.minsize(1080, 820)
        self.configure(fg_color=COLORS["bg"])

        self.system: Optional[SystemInfo] = None
        self.speed: Optional[SpeedTestResult] = None
        self.recommendation: Optional[Recommendation] = None
        self.events: "queue.Queue[Tuple[str, object]]" = queue.Queue()
        self.busy = set()
        self.note_labels: List[ctk.CTkLabel] = []

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()
        self._on_platform_change(self.platform_menu.get())

        self.protocol("WM_DELETE_WINDOW", self._close)
        self._poll_id = self.after(80, self._poll_events)

    def _build_sidebar(self) -> None:
        bar = ctk.CTkFrame(self, width=330, corner_radius=0, fg_color=COLORS["sidebar"])
        bar.grid(row=0, column=0, sticky="nsw")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(0, weight=1)
        bar.grid_rowconfigure(20, weight=1)

        ctk.CTkLabel(bar, text=APP_NAME, font=font(24, "bold"), text_color=COLORS["text"], anchor="w").grid(row=0, column=0, sticky="ew", padx=24, pady=(28, 0))
        ctk.CTkLabel(bar, text="OBS settings matched to your PC and your connection.", font=font(13), text_color=COLORS["muted"],
                     anchor="w", justify="left", wraplength=280).grid(row=1, column=0, sticky="ew", padx=24, pady=(4, 24))

        self._section(bar, 2, "Platform")
        platform_row = ctk.CTkFrame(bar, fg_color="transparent")
        platform_row.grid(row=3, column=0, sticky="ew", padx=24)
        platform_row.grid_columnconfigure(1, weight=1)
        self.platform_dot = ctk.CTkFrame(platform_row, width=12, height=12, corner_radius=6, fg_color=COLORS["accent"])
        self.platform_dot.grid(row=0, column=0, padx=(0, 10))
        self.platform_menu = ctk.CTkOptionMenu(
            platform_row, values=[p.name for p in PLATFORMS.values()], command=self._on_platform_change,
            height=38, corner_radius=10, font=font(14, "bold"), dropdown_font=font(14),
            fg_color=COLORS["secondary"], button_color=COLORS["secondary_hover"], button_hover_color=COLORS["border"],
        )
        self.platform_menu.grid(row=0, column=1, sticky="ew")
        self.platform_hint = ctk.CTkLabel(bar, text="", font=font(12), text_color=COLORS["muted"], anchor="w")
        self.platform_hint.grid(row=4, column=0, sticky="ew", padx=24, pady=(6, 22))

        self._section(bar, 5, "Steps")
        self.scan_button = self._button(bar, 6, "1   Scan Hardware", self._start_scan, primary=False)
        self.speed_button = self._button(bar, 7, "2   Run Speed Test", self._start_speed_test, primary=False)
        self.generate_button = self._button(bar, 8, "3   Generate Recommended Settings", self._generate, primary=True)

        self._section(bar, 9, "Manual upload (optional)", top=22)
        self.manual_entry = ctk.CTkEntry(bar, height=38, corner_radius=10, placeholder_text="Upload in Mbps, e.g. 12.5",
                                         fg_color=COLORS["secondary"], border_color=COLORS["border"], font=font(14))
        self.manual_entry.grid(row=10, column=0, sticky="ew", padx=24)
        self.manual_entry.bind("<Return>", lambda _e: self._generate())
        ctk.CTkLabel(bar, text="If filled, this value is used instead of the speed test result. Handy when the test fails.",
                     font=font(12), text_color=COLORS["muted"], anchor="w", justify="left", wraplength=280).grid(row=11, column=0, sticky="ew", padx=24, pady=(6, 0))

        ctk.CTkLabel(bar, text=f"v{APP_VERSION}", font=font(12), text_color=COLORS["muted"], anchor="w").grid(row=21, column=0, sticky="ew", padx=24, pady=18)

    def _section(self, master, row: int, text: str, top: int = 0) -> None:
        ctk.CTkLabel(master, text=text.upper(), font=font(11, "bold"), text_color=COLORS["muted"], anchor="w").grid(row=row, column=0, sticky="ew", padx=24, pady=(top, 6))

    def _button(self, master, row: int, text: str, command, primary: bool) -> ctk.CTkButton:
        button = ctk.CTkButton(
            master, text=text, command=command, height=42, corner_radius=10, anchor="w", font=font(14, "bold"),
            fg_color=COLORS["accent"] if primary else COLORS["secondary"],
            hover_color=COLORS["accent_hover"] if primary else COLORS["secondary_hover"],
            text_color=COLORS["text"],
        )
        button.grid(row=row, column=0, sticky="ew", padx=24, pady=4)
        return button

    def _build_main(self) -> None:
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=22, pady=22)
        main.grid_columnconfigure((0, 1), weight=1, uniform="top")
        main.grid_rowconfigure(2, weight=1)

        self._build_hardware_card(main)
        self._build_network_card(main)
        self._build_settings_card(main)
        self._build_notes_card(main)

        self.status = ctk.CTkLabel(main, text="Start by scanning your hardware.", font=font(12), text_color=COLORS["muted"], anchor="w")
        self.status.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))

    def _build_hardware_card(self, master) -> None:
        card = Card(master, "Hardware")
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 16))
        self.hw_pill = Pill(card.header, "Not scanned")
        self.hw_pill.grid(row=0, column=1)

        body = card.body
        body.grid_columnconfigure(1, weight=1)
        self.hw_values: Dict[str, ctk.CTkLabel] = {}
        for row, key in enumerate(("CPU", "Cores", "RAM", "GPU")):
            ctk.CTkLabel(body, text=key, font=font(13), text_color=COLORS["muted"], anchor="nw", width=64).grid(row=row, column=0, sticky="nw", pady=3)
            value = ctk.CTkLabel(body, text="-", font=font(13, "bold"), text_color=COLORS["text"], anchor="w", justify="left", wraplength=300)
            value.grid(row=row, column=1, sticky="w", pady=3)
            self.hw_values[key] = value

        ctk.CTkLabel(body, text="Encoders", font=font(13), text_color=COLORS["muted"], anchor="w", width=64).grid(row=4, column=0, sticky="w", pady=(8, 0))
        pills = ctk.CTkFrame(body, fg_color="transparent")
        pills.grid(row=4, column=1, sticky="w", pady=(8, 0))
        self.encoder_pills = {}
        for column, name in enumerate(("NVENC", "AMF", "QSV")):
            pill = Pill(pills, name)
            pill.grid(row=0, column=column, padx=(0, 6))
            self.encoder_pills[name] = pill

        self.hw_error = ctk.CTkLabel(body, text="", font=font(12), text_color=TONES["warning"][1], anchor="w", justify="left", wraplength=360)
        self.hw_error.grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def _build_network_card(self, master) -> None:
        card = Card(master, "Connection")
        card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 16))
        self.net_pill = Pill(card.header, "Not tested")
        self.net_pill.grid(row=0, column=1)

        body = card.body
        body.grid_columnconfigure((0, 1, 2), weight=1, uniform="metrics")
        self.metrics: Dict[str, ctk.CTkLabel] = {}
        for column, (key, unit) in enumerate((("Download", "Mbps"), ("Upload", "Mbps"), ("Ping", "ms"))):
            box = ctk.CTkFrame(body, fg_color=COLORS["tile"], corner_radius=10)
            box.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 4, 0 if column == 2 else 4))
            ctk.CTkLabel(box, text=key.upper(), font=font(11, "bold"), text_color=COLORS["muted"], anchor="w").pack(fill="x", padx=12, pady=(10, 0))
            value = ctk.CTkLabel(box, text="-", font=font(24, "bold"), text_color=COLORS["text"], anchor="w")
            value.pack(fill="x", padx=12)
            ctk.CTkLabel(box, text=unit, font=font(11), text_color=COLORS["muted"], anchor="w").pack(fill="x", padx=12, pady=(0, 10))
            self.metrics[key] = value

        self.progress = ctk.CTkProgressBar(body, height=8, corner_radius=4, progress_color=COLORS["accent"], fg_color=COLORS["tile"])
        self.progress.set(0)
        self.progress.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(14, 6))
        self.net_stage = ctk.CTkLabel(body, text="Run the speed test to measure your real upload speed.", font=font(12),
                                      text_color=COLORS["muted"], anchor="w", justify="left", wraplength=380)
        self.net_stage.grid(row=2, column=0, columnspan=3, sticky="w")
        self.net_server = ctk.CTkLabel(body, text="", font=font(12), text_color=COLORS["muted"], anchor="w", justify="left", wraplength=380)
        self.net_server.grid(row=3, column=0, columnspan=3, sticky="w")

    def _build_settings_card(self, master) -> None:
        card = Card(master, "Recommended OBS Settings")
        card.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(0, 16))
        self.settings_pill = Pill(card.header, "Waiting")
        self.settings_pill.grid(row=0, column=1, padx=(0, 8))
        self.copy_button = ctk.CTkButton(card.header, text="Copy", width=80, height=28, corner_radius=8, font=font(13, "bold"),
                                         fg_color=COLORS["secondary"], hover_color=COLORS["secondary_hover"], command=self._copy, state="disabled")
        self.copy_button.grid(row=0, column=2)

        body = card.body
        body.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="tiles")
        captions = ("Resolution", "FPS", "Video Bitrate", "Keyframe Interval", "Encoder", "Preset", "Rate Control", "Audio Bitrate")
        self.tiles: Dict[str, Tile] = {}
        for index, caption in enumerate(captions):
            tile = Tile(body, caption)
            tile.grid(row=index // 4, column=index % 4, sticky="nsew", padx=4, pady=4)
            self.tiles[caption] = tile

        ctk.CTkLabel(body, text="In OBS: Settings > Output (Output Mode: Advanced) > Streaming for the encoder, Settings > Video for resolution and FPS.",
                     font=font(12), text_color=COLORS["muted"], anchor="w").grid(row=2, column=0, columnspan=4, sticky="ew", padx=4, pady=(6, 0))

    def _build_notes_card(self, master) -> None:
        card = Card(master, "Notes")
        card.grid(row=2, column=0, columnspan=2, sticky="nsew")
        self.notes = ctk.CTkScrollableFrame(card.body, fg_color="transparent", height=150)
        self.notes.pack(fill="both", expand=True)
        self.notes.grid_columnconfigure(0, weight=1)
        self.notes.bind("<Configure>", self._rewrap_notes)
        self._render_notes([("info", "Scan your hardware and run a speed test, then generate your settings.")])

    def _post(self, kind: str, payload: object = None) -> None:
        # worker threads never touch widgets, they only push events here
        self.events.put((kind, payload))

    def _poll_events(self) -> None:
        handlers = {
            "scan_done": self._on_scan_done,
            "scan_failed": self._on_scan_failed,
            "speed_progress": self._on_speed_progress,
            "speed_done": self._on_speed_done,
            "speed_failed": self._on_speed_failed,
        }
        try:
            while True:
                kind, payload = self.events.get_nowait()
                handlers[kind](payload)
        except queue.Empty:
            pass
        self._poll_id = self.after(80, self._poll_events)

    def _close(self) -> None:
        self.after_cancel(self._poll_id)
        self.destroy()

    def _set_status(self, text: str, tone: str = "neutral") -> None:
        self.status.configure(text=text, text_color=COLORS["muted"] if tone == "neutral" else TONES[tone][1])

    def _platform_key(self) -> str:
        name = self.platform_menu.get()
        return next(key for key, p in PLATFORMS.items() if p.name == name)

    def _on_platform_change(self, _name: str) -> None:
        key = self._platform_key()
        platform = PLATFORMS[key]
        self.platform_dot.configure(fg_color=PLATFORM_COLORS[key])
        self.platform_hint.configure(text=f"Bitrate cap {platform.max_bitrate_kbps:,} Kbps  ·  up to {platform.max_height}p")
        if self.recommendation is not None:
            self._generate()

    def _start_scan(self) -> None:
        if "scan" in self.busy:
            return
        self.busy.add("scan")
        self.scan_button.configure(state="disabled", text="1   Scanning...")
        self.hw_pill.set("Scanning", "busy")
        self._set_status("Reading CPU, RAM and GPU information...")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self) -> None:
        try:
            self._post("scan_done", scan_system())
        except Exception as exc:
            self._post("scan_failed", str(exc) or exc.__class__.__name__)

    def _on_scan_done(self, system: SystemInfo) -> None:
        self.busy.discard("scan")
        self.system = system
        self.scan_button.configure(state="normal", text="1   Scan Hardware")

        self.hw_values["CPU"].configure(text=system.cpu_name)
        self.hw_values["Cores"].configure(text=f"{system.physical_cores} cores / {system.logical_cores} threads")
        self.hw_values["RAM"].configure(text=f"{system.ram_gb:g} GB" if system.ram_gb else "Unknown")
        gpu_lines = [f"{g.name} ({g.vram_mb / 1024:.0f} GB)" if g.vram_mb else g.name for g in system.gpus]
        self.hw_values["GPU"].configure(text="\n".join(gpu_lines) or "Not detected")

        for name, available in (("NVENC", system.has_nvenc), ("AMF", system.has_amf), ("QSV", system.has_qsv)):
            self.encoder_pills[name].set(f"{name} {'✓' if available else '✗'}", "ok" if available else "neutral")

        self.hw_error.configure(text="\n".join(system.errors))
        self.hw_pill.set("Done" if not system.errors else "Partial", "ok" if not system.errors else "warning")
        self._set_status("Hardware scan finished." if not system.errors else "Hardware scan finished with some gaps, see the Hardware card.",
                         "neutral" if not system.errors else "warning")
        if self.recommendation is not None:
            self._generate()

    def _on_scan_failed(self, message: str) -> None:
        self.busy.discard("scan")
        self.scan_button.configure(state="normal", text="1   Scan Hardware")
        self.hw_pill.set("Failed", "critical")
        self.hw_error.configure(text=f"Hardware scan failed: {message}")
        self._set_status("Hardware scan failed. Try again, or restart the app.", "critical")

    def _start_speed_test(self) -> None:
        if "speed" in self.busy:
            return
        self.busy.add("speed")
        self.speed_button.configure(state="disabled", text="2   Testing...")
        self.net_pill.set("Testing", "busy")
        self.progress.set(0)
        for label in self.metrics.values():
            label.configure(text="-")
        self.net_stage.configure(text="Starting...", text_color=COLORS["muted"])
        self.net_server.configure(text="")
        self._set_status("Speed test running, this usually takes 20-40 seconds.")
        threading.Thread(target=self._speed_worker, daemon=True).start()

    def _speed_worker(self) -> None:
        try:
            result = run_speed_test(lambda stage, fraction, measured: self._post("speed_progress", (stage, fraction, measured)))
            self._post("speed_done", result)
        except SpeedTestError as exc:
            self._post("speed_failed", exc.message)
        except Exception as exc:
            self._post("speed_failed", f"Unexpected error during the speed test: {exc}")

    def _on_speed_progress(self, payload) -> None:
        stage, fraction, measured = payload
        text, start, end = STAGES.get(stage, (stage, 0.0, 0.0))
        self.progress.set(start + (end - start) * fraction)
        suffix = f"  {int(fraction * 100)}%" if stage in ("download", "upload") else ""
        self.net_stage.configure(text=f"{text}...{suffix}")
        self._show_metrics(measured.get("download_mbps"), measured.get("upload_mbps"), measured.get("ping_ms"))

    def _show_metrics(self, download: Optional[float], upload: Optional[float], ping: Optional[float]) -> None:
        for key, value, fmt in (("Download", download, "{:.1f}"), ("Upload", upload, "{:.1f}"), ("Ping", ping, "{:.0f}")):
            if value is not None:
                self.metrics[key].configure(text=fmt.format(value))

    def _on_speed_done(self, result: SpeedTestResult) -> None:
        self.busy.discard("speed")
        self.speed = result
        self.speed_button.configure(state="normal", text="2   Run Speed Test")
        self.progress.set(1)
        self._show_metrics(result.download_mbps, result.upload_mbps, result.ping_ms)
        self.net_pill.set("Done", "ok")
        self.net_stage.configure(text="Speed test finished.", text_color=COLORS["muted"])
        self.net_server.configure(text=f"Server: {result.server}")
        self._set_status("Speed test finished.")
        if self.recommendation is not None:
            self._generate()

    def _on_speed_failed(self, message: str) -> None:
        self.busy.discard("speed")
        self.speed_button.configure(state="normal", text="2   Run Speed Test")
        self.progress.set(0)
        self.net_pill.set("Failed", "critical")
        self.net_stage.configure(text=message, text_color=TONES["critical"][1])
        self.net_server.configure(text="You can type your upload speed into the manual field in the sidebar instead.")
        self._set_status("Speed test failed.", "critical")

    def _upload_source(self) -> Tuple[Optional[float], Optional[float], str]:
        raw = self.manual_entry.get().strip().replace(",", ".")
        ping = self.speed.ping_ms if self.speed else None
        if raw:
            try:
                value = float(raw)
            except ValueError:
                return None, None, "Manual upload must be a number, like 12.5."
            if value <= 0:
                return None, None, "Manual upload must be greater than 0."
            return value, ping, "manual entry"
        if self.speed is not None:
            return self.speed.upload_mbps, ping, "speed test"
        return None, None, "Run the speed test or type your upload speed into the manual field."

    def _generate(self) -> None:
        if self.system is None:
            self._set_status("Scan your hardware first.", "warning")
            return
        upload, ping, source = self._upload_source()
        if upload is None:
            self._set_status(source, "warning")
            return

        try:
            rec = recommend(self._platform_key(), self.system, upload, ping)
        except ValueError as exc:
            self._set_status(f"Could not build a recommendation: {exc}", "critical")
            return

        self.recommendation = rec
        values = {
            "Resolution": f"{rec.tier.width}x{rec.tier.height}",
            "FPS": str(rec.tier.fps),
            "Video Bitrate": f"{rec.video_kbps:,} Kbps",
            "Keyframe Interval": f"{rec.keyframe_s} s",
            "Encoder": rec.encoder_name,
            "Preset": rec.preset,
            "Rate Control": rec.rate_control,
            "Audio Bitrate": f"{rec.audio_kbps} Kbps",
        }
        for caption, text in values.items():
            self.tiles[caption].value.configure(text=text)

        worst = rec.advice[0].level if rec.advice else "ok"
        self.settings_pill.set(f"{rec.platform.name} · {rec.tier.label}", worst if worst in ("critical", "warning") else "ok")
        self.copy_button.configure(state="normal")
        self._render_notes([(a.level, a.message) for a in rec.advice] or [("ok", "No issues found. These settings should run smoothly.")])
        self._set_status(f"Settings generated for {rec.platform.name} using {upload:g} Mbps upload from {source}.")

    def _render_notes(self, notes: List[Tuple[str, str]]) -> None:
        for child in self.notes.winfo_children():
            child.destroy()
        self.note_labels = []
        tags = {"critical": "CRITICAL", "warning": "WARNING", "info": "TIP", "ok": "OK"}
        for row, (level, message) in enumerate(notes):
            bg, fg = TONES[level]
            item = ctk.CTkFrame(self.notes, fg_color=COLORS["tile"], corner_radius=8)
            item.grid(row=row, column=0, sticky="ew", pady=3)
            item.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(item, text=tags[level], width=78, height=22, corner_radius=11, fg_color=bg, text_color=fg,
                         font=font(11, "bold")).grid(row=0, column=0, padx=(10, 12), pady=10, sticky="n")
            label = ctk.CTkLabel(item, text=message, font=font(13), text_color=COLORS["text"], anchor="w", justify="left",
                                 wraplength=max(self.notes.winfo_width() - 140, 400))
            label.grid(row=0, column=1, sticky="w", padx=(0, 12), pady=8)
            self.note_labels.append(label)

    def _rewrap_notes(self, event) -> None:
        for label in self.note_labels:
            label.configure(wraplength=max(event.width - 140, 300))

    def _copy(self) -> None:
        if self.recommendation is None:
            return
        self.clipboard_clear()
        self.clipboard_append(self.recommendation.as_text())
        self._set_status("Settings copied to clipboard.", "ok")


def main() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = StreamOptimizerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
