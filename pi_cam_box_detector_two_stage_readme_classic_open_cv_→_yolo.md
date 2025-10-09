# PiCam Box Detector – Two‑Stage README (Classic OpenCV → YOLO)

> **What this is**: A two‑stage, drop‑in web service that runs on a Raspberry Pi and detects parcel‑like boxes in a camera stream. Stage 1 is a lightweight **Classic OpenCV** pipeline. Stage 2 swaps in a trained **YOLO** model while keeping the same HTTP endpoints and UX. I built the OpenCV version first, proved the end‑to‑end flow, and then upgraded to YOLO for robustness.

---

## TL;DR

- **Classic OpenCV** has a landing page at `http://<pi-ip>:8000/`. The current YOLO script exposes endpoints directly; add an optional `/` route if you want a landing page (snippet below).
- **Endpoints** (shared across Classic + YOLO; note `/` is Classic-only unless you add it):
  - `/video` – MJPEG with detections & HUD
  - `/video_raw` – MJPEG without detections (fast debug)
  - `/snapshot` – saves before/after image pair to `samples/`
  - `/health` – simple JSON health
  - `/config` – current runtime config JSON
- Systemd units make the service auto‑start.
- Switch engines with a single config flag (`backend: classic|yolo`).

---

## Hardware & OS

- **Raspberry Pi**: 3 Model B
- **Camera**: Raspberry Pi Camera v2.1 (IMX219)
- **OS**: Raspberry Pi OS (Bookworm)
- **Lang**: Python 3

> Tip: A Pi 3B can run the Classic pipeline at comfortable FPS. YOLO runs too if the model is small and input is down‑scaled; expect lower FPS unless you optimize/export.

---

## Project Structure (suggested)

```
PiCam_BoxDetector/
├─ scripts/
│  ├─ box_stream.py            # Classic OpenCV server
│  ├─ box_stream_yolo.py       # YOLO server (same endpoints)
│  └─ utils.py
├─ models/
│  └─ box320/
│     └─ last.pt               # Trained YOLO weights (3.7 MB)
├─ samples/                    # Snapshots from /snapshot
├─ configs/
│  └─ config.yaml              # Shared runtime config
├─ detections.csv              # Presence transitions log
├─ systemd/
│  ├─ box_stream.service
│  └─ box_stream_yolo.service
└─ README.md
```

---

## Shared Runtime Config (`configs/config.yaml`)

```yaml
# Select the detection backend
backend: classic   # classic | yolo

# Camera & streaming
resolution: [1280, 720]
mjpeg_quality: 85
port: 8000

# Debounce / hysteresis for a stable "Boxes: 1" HUD
warmup_seconds: 1.0
present_hits: 5        # consecutive positives to switch ON
absent_hits: 5         # consecutive negatives to switch OFF

# Classic parameters
classic:
  clahe_clip: 2.0
  thresh_block: 21
  thresh_C: 5
  min_area_px: 10000
  aspect_tolerance: 0.6

# YOLO parameters
yolo:
  weights: models/box320/last.pt
  img_size: 320
  conf: 0.6
  iou: 0.5
  class_names: ["box"]
```

---

# Stage 1 — Classic OpenCV (what I built first)

### What I built
I implemented a fast, dependency‑light detector using Picamera2 + OpenCV + Flask. The server streams an MJPEG feed with a compact HUD (version, FPS, IP/port, endpoints) and draws a green rectangle when it finds a box‑like quad. It also exposes `/video_raw`, `/snapshot`, `/health`, and `/config`. To avoid flicker I added warm‑up (ignore ~1 s) and a hysteresis counter, so the **“Boxes: 1”** label is rock‑solid.

### Detection pipeline (high‑level)
1. **Pre‑process**: Convert to LAB, apply **CLAHE** to L‑channel for even lighting.
2. **Adaptive threshold** → **contours**.
3. Keep contours that look like **convex quads/rotated rects** with sane aspect and area.
4. Run the **debounce**: toggle presence only after N consecutive hits/misses.

### Quick start (Classic)
```bash
# 0) (Optional) create a venv – keeps the Pi clean
python3 -m venv .venv && source .venv/bin/activate

# 1) Install deps
sudo apt update
sudo apt install -y python3-opencv python3-picamera2
pip install flask numpy

# 2) Run the server
python3 scripts/box_stream.py
# Open http://<pi-ip>:8000/video  (or just http://<pi-ip>:8000/)
```

### Auto‑start with systemd
`systemd/box_stream.service`
```ini
[Unit]
Description=PiCam Box Detector (Classic OpenCV)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/pi/PiCam_BoxDetector
ExecStart=/usr/bin/python3 scripts/box_stream.py
Restart=always

[Install]
WantedBy=multi-user.target
```
```bash
sudo cp systemd/box_stream.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now box_stream
```

### Endpoints

| Path | Classic OpenCV | YOLO | What it does |
|------|-----------------|------|--------------|
| `/` | ✅ Landing page with links and HUD | ⛔ Not present by default (add optional route below) | Index page |
| `/video` | ✅ | ✅ | MJPEG stream + detections + HUD |
| `/video_raw` | ✅ | ✅ | MJPEG stream without detection overlay |
| `/snapshot` | ✅ | ✅ | Saves `samples/<ts>_raw.jpg` and `<ts>_det.jpg` |
| `/health` | ✅ | ✅ | Returns `{status: "ok", fps: <float>, ...}` |
| `/config` | ✅ | ✅ | Returns current runtime configuration JSON |

#### Optional landing page for YOLO
Add this minimal route to `box_stream_yolo.py` to mirror the Classic landing page:
```python
@app.route("/")
def index():
    return """
    <h1>PiCam Box Detector (YOLO)</h1>
    <ul>
      <li><a href=\"/video\">/video</a></li>
      <li><a href=\"/video_raw\">/video_raw</a></li>
      <li><a href=\"/snapshot\">/snapshot</a></li>
      <li><a href=\"/health\">/health</a></li>
      <li><a href=\"/config\">/config</a></li>
    </ul>
    """
```
> If your endpoint function names differ, keep the hrefs as literal paths (as above) and it will still work.

### Logging presence transitions
I log ON/OFF state changes to `detections.csv` (UNIX timestamp, 0/1). This gives me a simple metric timeline without a database.

---

# Stage 2 — YOLO Upgrade (what I added next)

### Why I upgraded
Classic heuristics are fast and explainable but can struggle with odd lighting, textures, or perspective. YOLO improves **recall/precision** and handles more variation. I kept the **same endpoint paths** for `/video`, `/video_raw`, `/snapshot`, `/health`, and `/config`. The YOLO script initially omitted the `/` landing page; you can add it with the optional route below.

### My training results (snapshot)
- `runs/train/box320/weights/last.pt`, **3.7 MB**
- Trained **120 epochs** (completed in ~0.314 hours on my host)
- Input size **320×320** for speed on Pi 3B

> These numbers come from my Ultralytics training logs. I deploy the resulting `last.pt` to the Pi under `models/box320/last.pt`.

### Quick start (YOLO)
```bash
# 1) Extra deps for YOLO backend
pip install ultralytics "torch==2.*" torchvision --extra-index-url https://download.pytorch.org/whl/cpu

# 2) Put your weights on the Pi
mkdir -p models/box320 && cp <your-trained>/last.pt models/box320/

# 3) Run the YOLO server (same endpoints)
python3 scripts/box_stream_yolo.py

# 4) Or switch via config
yq -yi '.backend = "yolo"' configs/config.yaml  # optional convenience
```

### Auto‑start with systemd
`systemd/box_stream_yolo.service`
```ini
[Unit]
Description=PiCam Box Detector (YOLO)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/pi/PiCam_BoxDetector
ExecStart=/usr/bin/python3 scripts/box_stream_yolo.py
Restart=always

[Install]
WantedBy=multi-user.target
```

### Performance notes & options
- **Image size**: 320 keeps CPU load survivable on a Pi 3B. 416/480 may be OK with lower FPS.
- **Export**: For extra speed, export to **ONNX** and run via OpenCV DNN or **TensorRT**/**Tengine** on supported boards.
  ```bash
  yolo export model=models/box320/last.pt format=onnx imgsz=320
  ```
- **Confidence/IoU**: Tune `yolo.conf` and `yolo.iou` in `config.yaml` to balance misses vs false alarms.

### Training recipe (on a PC)
```bash
pip install ultralytics
# dataset yaml should define train/val paths and class name: [box]
yolo detect train data=box.yaml model=yolov8n.pt imgsz=320 epochs=120 batch=16 name=box320
# best.pt / last.pt will appear in runs/train/box320/weights
```

---

## Advances from Classic → YOLO (what improved)

| Area | Classic OpenCV | YOLO |
|---|---|---|
| **Robustness** | Sensitive to lighting and texture changes | Learns features; better across backgrounds/angles |
| **False Positives** | Needs tight tuning; may mis‑detect | Lower with trained data |
| **Latency/FPS** | Higher FPS on Pi 3B | Heavier; may need 320 input or export |
| **Explainability** | Transparent steps | Black‑box but measurable |
| **Extendability** | Hard to add new shapes | Retrain with new labels |

I chose YOLO once the UI/ops were proven and I had a labelled dataset.

---

## Troubleshooting

- **Port already in use (8000)**
  ```bash
  sudo ss -lptn 'sport = :8000'
  # or, if lsof installed: sudo lsof -i :8000
  sudo fuser -k 8000/tcp
  ```
- **Typo**: it’s `/dev/null` (not `/dev/nul`).
- **Camera not found**
  ```bash
  rpicam-hello --list-cameras
  # IMX219 should appear; reboot if not
  ```
- **Service logs**
  ```bash
  journalctl -u box_stream -f
  journalctl -u box_stream_yolo -f
  ```

---

## Security & Ops
- This is a LAN demo server. For exposure beyond LAN, put it behind a reverse proxy with auth.
- Limit Pi user perms and keep packages updated.

---

## License
MIT (or your preferred license). Add a `LICENSE` file at repo root.

---

## Roadmap
- [ ] Export YOLO to ONNX and benchmark vs PyTorch on Pi 3B
- [ ] Add `/metrics` (Prometheus) and a simple front‑end chart
- [ ] Optional MQTT publish on presence transitions
- [ ] Autolabel helper for building the dataset from Classic detections

---

## Credits
- **Picamera2**, **OpenCV**, **Flask**, **Ultralytics YOLO**.

---

### One‑liner Summary (for the repo top)
> I built a Raspberry Pi box detector with a clean web HUD. Stage 1 uses Classic OpenCV (fast). Stage 2 swaps in YOLO (robust) – same endpoints, drop‑in upgrade. I trained a small 320×320 model (`last.pt`, 3.7 MB, 120 epochs) and deployed it via systemd on the Pi.

