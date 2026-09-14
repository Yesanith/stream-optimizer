# Stream Optimizer

A desktop tool for streamers. It measures your real upload speed and scans your hardware (CPU, RAM, GPU), then recommends OBS settings for the platform you stream on: resolution, FPS, bitrate, encoder, preset and keyframe interval.

Built with Python and [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter).

## Features

- **Platform presets** for Twitch, Kick, YouTube and a generic "Other" option, each with its own bitrate ceiling.
- **Hardware scan**: CPU model, core and thread count, RAM, GPU model, and whether a hardware encoder is available (NVIDIA NVENC, AMD AMF, Intel QuickSync).
- **Real speed test** using speedtest.net servers (download, upload, ping) with live progress. The UI stays responsive while it runs.
- **Recommended OBS settings** built from your platform, hardware and upload speed, plus warnings when something will hold your stream back.
- **Manual upload input** for when the speed test cannot reach a server, or when you already know your upload speed.
- **Copy to clipboard** so you can keep the settings next to OBS.

## How the recommendations work

The logic lives in `modules/recommender.py` and does not depend on the GUI, so you can import it and call `recommend()` directly.

**Bitrate.** About 70% of your measured upload is used for the stream. The audio bitrate (160 Kbps) comes out of that budget, and the video bitrate never exceeds the platform limit:

| Platform | Video bitrate cap | Max resolution |
|----------|-------------------|----------------|
| Twitch   | 8,000 Kbps        | 1080p          |
| Kick     | 12,000 Kbps       | 1080p          |
| YouTube  | 51,000 Kbps       | 1440p          |
| Other    | 8,000 Kbps        | 1080p          |

**Resolution and FPS.** The tool picks the highest tier that your upload speed, your hardware and the platform all allow:

| Tier    | Minimum video bitrate |
|---------|-----------------------|
| 480p30  | 1,000 Kbps            |
| 720p30  | 2,500 Kbps            |
| 720p60  | 3,500 Kbps            |
| 1080p30 | 4,500 Kbps            |
| 1080p60 | 6,000 Kbps            |
| 1440p60 | 9,000 Kbps (YouTube only) |

Each tier also has a sensible upper bitrate. For example, 720p30 is not given 8,000 Kbps just because your connection could carry it.

**Encoder.** NVENC is used when available, then AMF, and x264 is the fallback. The x264 preset and the maximum tier depend on your CPU:

| CPU class | Cores / threads         | x264 ceiling | x264 preset | Hardware encoder ceiling |
|-----------|-------------------------|--------------|-------------|--------------------------|
| low       | 4 threads or fewer      | 720p30       | superfast   | 720p60                   |
| mid       | fewer than 6 cores      | 720p60       | veryfast    | 1080p60                  |
| high      | 6-7 cores               | 1080p30      | veryfast    | 1080p60                  |
| very high | 8-11 cores              | 1080p60      | veryfast    | 1440p60                  |
| ultra     | 12 cores or more        | 1080p60      | faster      | 1440p60                  |

NVENC uses `P5: Slow (Good Quality)` on RTX cards and `P4: Medium` on older ones. AMF uses `Quality` on RX 5000 and newer, and `Balanced` otherwise. Every recommendation uses CBR rate control, the High profile, and a 2 second keyframe interval.

**Warnings** cover low or unusable upload speed, no hardware encoder, a weak CPU on x264, low RAM, high ping, and whether your upload, your hardware or the platform cap is what limits the result.

These are starting points, not guarantees. Games and scenes vary a lot, so watch the OBS stats dock for dropped frames or "Encoding overloaded" messages and adjust from there.

## Requirements

- Python 3.9 or newer
- Windows, Linux or macOS. Hardware encoder detection is most complete on Windows.
- An NVIDIA driver with `nvidia-smi` for NVIDIA GPU details

## Installation

```bash
git clone https://github.com/Yesanith/stream-optimizer.git
cd stream-optimizer
python -m venv .venv
```

Activate the virtual environment:

```bash
# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

On Linux you may also need Tk, for example `sudo apt install python3-tk`.

## Usage

```bash
python main.py
```

1. Pick your platform from the dropdown.
2. Click **Scan Hardware**.
3. Click **Run Speed Test** and wait 20 to 40 seconds. If it fails, type your upload speed in Mbps into the manual field instead.
4. Click **Generate Recommended Settings**.
5. Apply the values in OBS: **Settings > Output** (Output Mode: Advanced) **> Streaming** for the encoder and bitrate, and **Settings > Video** for resolution and FPS.

Changing the platform after generating updates the settings right away.

## Project structure

```
stream-optimizer/
├── main.py                  # CustomTkinter GUI, runs scans and tests on background threads
├── modules/
│   ├── __init__.py
│   ├── recommender.py       # platform + hardware + upload speed -> OBS settings, no GUI imports
│   ├── system_info.py       # CPU / RAM / GPU detection and hardware encoder support
│   └── speed_test.py        # speedtest-cli wrapper with progress callbacks and readable errors
├── requirements.txt
├── README.md
├── LICENSE
└── .gitignore
```

## Troubleshooting

- **The speed test fails.** speedtest.net is sometimes blocked by firewalls, VPNs or school and office networks. Try again, turn off the VPN, or use the manual upload field.
- **No GPU is detected.** For NVIDIA, make sure the driver is installed and `nvidia-smi` runs in a terminal. On Windows, AMD and Intel GPUs are read through WMI. The tool still works and falls back to x264.
- **`ModuleNotFoundError: No module named 'distutils'`.** GPUtil needs `distutils`, which Python 3.12 removed. `requirements.txt` installs `setuptools`, which provides it. If the problem remains, the app still detects NVIDIA GPUs through `nvidia-smi`.

## Contributing

Issues and pull requests are welcome. If you think a tier, preset or platform limit is off, open an issue and explain why.

## License

[MIT](LICENSE)
