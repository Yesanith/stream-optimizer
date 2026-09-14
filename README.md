# Stream Optimizer

A desktop tool for streamers. It measures your real upload speed and scans your hardware (CPU, RAM, GPU), then recommends OBS settings for the platform you stream on: resolution, FPS, bitrate, encoder, preset and keyframe interval.

Built with Python and [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter).

## Features

- **Platform presets** for Twitch, Kick, YouTube and a generic "Other" option, each with its own bitrate ceiling.
- **Hardware scan**: CPU model, core and thread count, RAM, GPU model, and whether a hardware encoder is available (NVIDIA NVENC, AMD AMF, Intel QuickSync).
- **Real speed test** against speedtest.net servers (download, upload, ping) with live readings. The UI stays responsive while it runs. See [How the speed test works](#how-the-speed-test-works).
- **Recommended OBS settings** built from your platform, hardware and upload speed, plus warnings when something will hold your stream back.
- **Recommended ingest server** for the selected platform. Twitch servers are ranked by measured latency, YouTube shows its primary ingest, and Kick shows how its automatic route compares with your nearest region. Each result gets a latency rating: Good up to 100 ms, Fair up to 200 ms, High latency above that.
- **Manual upload input** for when the speed test cannot reach a server, or when you already know your upload speed.
- **OBS profile export** saves the recommended settings as an OBS profile you can load with Profile > Import (OBS 31 or newer).
- **Copy to clipboard** so you can keep the settings next to OBS.

## How the speed test works

The test lives in `modules/speed_test.py` and talks to speedtest.net servers with the same TCP protocol the official Speedtest apps use (`PING`, `DOWNLOAD`, `UPLOAD` on the server's test port).

1. The nearest servers come from the same list the speedtest.net website uses. If that list is unavailable, speedtest-cli's server list is used instead.
2. Every server is pinged five times, and the test runs against the one with the lowest median ping.
3. Download and upload each run for 8 seconds over 4 parallel connections. The first 2 seconds are ignored, because TCP is still speeding up and socket buffers are still filling.
4. If a connection drops, the test is repeated on the next server instead of reporting a speed that is too low.
5. A result under 5 Mbps is measured again on a second server, and the higher reading is used. A single overloaded server should not push you down to 480p.
6. If the speed moves around a lot during the test, the result is flagged so you know to run it again.

speedtest-cli's own measurement is not used for download and upload. Many Ookla servers answer its legacy `upload.php` request with a redirect that it silently counts as a failed upload, which can show an upload speed close to zero.

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

**Ingest server.** After the speed test, or when you generate settings, the tool measures the TCP handshake time to the platform's ingest servers. No stream key is needed. Each server is probed several times and the fastest handshake counts, because network congestion can only add delay. The three fastest servers get a second, longer round so close calls don't flip between runs. Servers within 8 ms of each other count as equally fast. The check never runs during the speed test, because a busy line would inflate every latency.

| Platform | What is checked | Recommendation |
|----------|-----------------|----------------|
| Twitch   | Every server from Twitch's public ingest list (`ingest.twitch.tv/ingests`) on port 1935 | The server with the lowest latency |
| YouTube  | Primary and backup RTMPS ingest | Primary, backup only if the primary does not answer |
| Kick     | Kick's Stream URL, plus the regional Amazon IVS ingests Kick is built on | Kick has no server list, so the tool shows how much slower its automatic route is than your nearest region |
| Other    | Nothing | Use the URL your platform gives you |

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

### Exporting an OBS profile

Instead of typing the values into OBS by hand, click **Export OBS Profile** and pick a folder. The tool creates a folder such as `Stream Optimizer Twitch 1080p60` containing two files:

| File | What it sets |
|------|--------------|
| `basic.ini` | Advanced output mode, encoder, 160 Kbps AAC audio, 48 kHz stereo, canvas and output resolution, FPS |
| `streamEncoder.json` | CBR, video bitrate, 2 second keyframe interval, preset and profile |

Then, in OBS 31 or newer, choose **Profile > Import**, select that folder, and switch to the new profile.

- The canvas (base) resolution matches your monitor, trimmed to 16:9, so your scenes keep their layout. The output resolution is the recommended one, scaled with Lanczos. A canvas smaller than the recommendation is never upscaled.
- "Enforce streaming service encoder settings" is turned off. Otherwise OBS can clamp the bitrate to its own defaults for the service.
- The profile has no stream key or server. Add them in **Settings > Stream** after importing.
- An existing folder is never overwritten. A second export gets a numbered name.
- OBS versions older than 31 use a different ID for the NVIDIA encoder, so they will not pick up the encoder from this profile.

## Project structure

The code is split into `modules/`, which has no GUI imports and can be used on its own, and `ui/`, which only renders and wires things together.

```
stream-optimizer/
├── main.py                  # entry point, starts the GUI
├── modules/                 # core logic
│   ├── platforms.py         # platform list with bitrate caps and max resolution
│   ├── recommender.py       # platform + hardware + upload speed -> OBS settings
│   ├── system_info.py       # CPU / RAM / GPU detection and hardware encoder support
│   ├── speed_test.py        # speedtest-cli wrapper, picks the closest server by latency
│   ├── ingest.py            # platform ingest server lookup and latency rating
│   ├── obs_profile.py       # writes the recommendation as an importable OBS profile
│   ├── net.py               # shared helpers: JSON fetch, TCP latency, parallel probes
│   └── errors.py            # base error with a user facing message
├── ui/                      # CustomTkinter GUI
│   ├── app.py               # main window, app state and the flow between steps
│   ├── sidebar.py           # platform picker, step buttons, manual upload
│   ├── cards/               # hardware, connection, settings and notes cards
│   ├── widgets.py           # shared widgets: Card, Tile, Metric, Pill
│   ├── tasks.py             # runs blocking work on threads, returns results on the Tk thread
│   ├── theme.py             # colors and fonts
│   └── window.py            # Windows fix for black boxes while resizing
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
