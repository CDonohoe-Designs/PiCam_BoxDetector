# PiCam_BoxDetector

I built a lightweight, real-time **box/presence detector** on a Raspberry Pi 3 + Pi Cam v2.1 using **Picamera2 + OpenCV + Flask**. Next I added **debounced state logging** to `detections.csv`, so I can measure real “in/out” events and tune thresholds under different lighting.

---

## Demo (landing)
![Landing](docs/images/01-landing.jpg)
*Browser landing page at `http://<pi-ip>:8000` with links to the stream and a still snapshot.*

---

## System Architecture
![Architecture](docs/images/02-architecture.png)
*Camera → Picamera2 → OpenCV Presence → Debounce & CSV → Flask HTTP → Browser.*

> If your diagram edges look cropped in Word/Docs, use the compact versions and save as `docs/images/02-architecture.png`:
> - `System_Architecture_Padded.png` (safe margins)
> - `System_Architecture_2Row.png` (larger text / two lines)

---

## Stream UI (detail)
![Stream UI](docs/images/03-stream-ui.jpg)
*A clean 720p MJPEG stream served by Flask. Optional “PRESENT: YES/NO” overlay.*

---

## Detection sequence (debounce proof)
| No subject | Subject enters | Stable PRESENT |
|---|---|---|
| ![No subject](docs/images/04-detection-seq-1.jpg) | ![Enter](docs/images/04-detection-seq-2.jpg) | ![Stable](docs/images/04-detection-seq-3.jpg) |

*Debounce eliminates flicker during transitions.*

---

## ROI / Overlay (optional)
![ROI](docs/images/05-roi-overlay.jpg)
*I can focus detection to a region-of-interest for stability.*

---

## Metrics – raw CSV transitions
![CSV](docs/images/06-metrics-csv.png)
*Each row is a **debounced** flip: `timestamp,present` (1=present, 0=absent).*

## Metrics – timeline chart
![Chart](docs/images/07-metrics-chart.png)
*A simple step plot from the CSV shows presence episodes over time.*

---

## Hardware
![Top](docs/images/08-hardware-top.jpg)
![Placement](docs/images/09-hardware-side.jpg)
*Pi 3 Model B + IMX219 camera; typical bench/installation geometry.*

---

## Ops proof
![systemd](docs/images/10-systemd-status.png)
![Reachable](docs/images/11-browser-reachable.png)
*Boot-stable via `systemd` and reachable on the LAN.*

---

## Tuning & edge conditions
![Low threshold](docs/images/12-threshold-low.jpg)
![Higher threshold](docs/images/13-threshold-high.jpg)
![Lighting montage](docs/images/14-edge-lighting-montage.jpg)

*Threshold and lighting stress tests.*

---

## Quickstart (Raspberry Pi OS – Bookworm)
```bash
# deps
sudo apt update && sudo apt install -y python3-pip python3-opencv libatlas-base-dev

# clone
git clone https://github.com/<your-username>/PiCam_BoxDetector.git
cd PiCam_BoxDetector

# venv (keeps system Python clean)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# run
python3 scripts/box_stream.py
# now open: http://<pi-ip>:8000
```

### Endpoints
| Path | Purpose |
|---|---|
| `/` | Landing page (links) |
| `/video` | Live MJPEG stream |
| `/snapshot` | Single JPEG frame |
| `/health` | Basic service health (200 OK) |

---

## Configuration
You can tune these in code or via env/arguments (depending on your script):
- **PORT**: `8000` (default)
- **THRESH**: motion/brightness delta (e.g., `25`)
- **DEBOUNCE_MS**: minimum hold time for stable flips (e.g., `300` ms)
- **ROI**: optional rectangle for focus (x1,y1,x2,y2)

---

## Debounced CSV logging
I append one row to `detections.csv` **only when** the debounced state flips. This keeps logs compact and auditable.

```python
# metrics.py (separate module)
import csv, time, threading
from pathlib import Path

class Debouncer:
    def __init__(self, min_ms=300, initial=False):
        self.min_s = min_ms/1000.0; self._stable = bool(initial)
        self._pending = None; self._since = None

    def update(self, raw, t_mon=None):
        t = time.monotonic() if t_mon is None else t_mon
        raw = bool(raw)
        if raw == self._stable:
            self._pending = None; self._since = None; return self._stable, False
        if self._pending is None:
            self._pending = raw; self._since = t;   return self._stable, False
        if raw != self._pending:
            self._pending = None; self._since = None; return self._stable, False
        if (t - self._since) >= self.min_s:
            self._stable = self._pending; self._pending = None; self._since = None
            return self._stable, True
        return self._stable, False

class TransitionLogger:
    def __init__(self, csv_path: Path, add_header=True):
        self.path = Path(csv_path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if add_header and not self.path.exists():
            with self.path.open("w", newline="") as f:
                csv.writer(f).writerow(["timestamp","present"])

    def log(self, present: bool, ts=None):
        ts = int(time.time() if ts is None else ts)
        with self._lock:
            with self.path.open("a", newline="") as f:
                csv.writer(f).writerow([ts, int(bool(present))])
```

Wire-up inside `scripts/box_stream.py`:
```python
from pathlib import Path
from metrics import Debouncer, TransitionLogger

LOG_PATH = Path(__file__).resolve().parent.parent / "detections.csv"
debounce = Debouncer(min_ms=300)
tlog = TransitionLogger(LOG_PATH)

# after computing raw_present from OpenCV:
stable_present, changed = debounce.update(raw_present)
if changed:
    tlog.log(stable_present)
```

---

## Run on boot (`systemd`)
Create `systemd/box-stream.service`:
```ini
[Unit]
Description=PiCam Box Detector
After=network-online.target

[Service]
WorkingDirectory=/home/pi/PiCam_BoxDetector
ExecStart=/home/pi/PiCam_BoxDetector/.venv/bin/python3 scripts/box_stream.py
Restart=on-failure
User=pi
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Install + enable:
```bash
sudo cp systemd/box-stream.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now box-stream
sudo systemctl status box-stream --no-pager
```

---

## Project layout
```
PiCam_BoxDetector/
├─ docs/images/           # screenshots & diagrams used in this README
├─ scripts/
│  └─ box_stream.py       # camera + OpenCV + Flask stream
├─ metrics.py             # debounce + CSV transition logger
├─ requirements.txt
├─ detections.csv         # created on first run (append-only)
└─ systemd/box-stream.service
```

---

## Troubleshooting
- **Port already in use (8000):** `sudo fuser -v 8000/tcp` then `sudo fuser -k 8000/tcp`  
- **Device busy:** make sure the `systemd` service isn’t running while you start the script manually.  
- **No image:** check the camera ribbon cable and `rpicam-hello` test.

---

## Roadmap
- `/metrics` JSON endpoint + tiny dashboard
- Background model reset for lighting shifts
- Optional YOLOv8 path once OpenCV baseline is stable

---

## License
MIT
