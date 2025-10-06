# PiCam Box Detector

I built a lightweight, real-time **box detector** on a Raspberry Pi using **Picamera2 + OpenCV + Flask**. It streams an MJPEG feed, draws a green rectangle around boxes (e.g., parcels), and exposes endpoints for snapshots, health, and config. I tuned it for demos with a short warm-up and debounced detections so the “Boxes: 1” indicator is rock-solid.

**Hardware:** Raspberry Pi 3 Model B + Pi Camera v2.1  
**OS:** Raspberry Pi OS (Bookworm)  
**Language:** Python 3


## What I built

- I stream live video at **`/video`** with a small HUD (version, FPS, IP/port, endpoints).
- I added **`/video_raw`** to bypass detection for fast debugging.
- I save **before/after** snapshot pairs to `samples/` via **`/snapshot`**.
- I expose **`/health`** and **`/config`** for quick checks during a live demo.
- I made the detector robust:
  - LAB + CLAHE → adaptive threshold → contours → convex quad **or** rotated rectangle.
  - **Warm-up** (ignore first ~1s) + **hysteresis** (hits/misses) to prevent flicker.
  - A full-frame guard so startup noise doesn’t count as a detection.
- I run it as a **systemd** service so it auto-starts on boot and restarts on failure.

---
## Figure 1 — Landing

![Figure 1 — Landing](docs/images/01-landing.jpg "Landing page at http://<pi-ip>:8000")
*Browser landing page at `http://<pi-ip>:8000` with links to `/video` and `/snapshot`.*

---

## Figure 2 — System Architecture

![Figure 2 — System Architecture](docs/images/02-architecture.png "Camera → Picamera2 → OpenCV → Debounce/CSV → Flask → Browser")
*Camera → Picamera2 → OpenCV Presence → Debounce & CSV → Flask HTTP → Browser.*

---

## Figure 3 — Stream UI (Detail)

![Figure 3 — Stream UI](docs/images/03-stream-ui.jpg "Live MJPEG stream")
*A clean 720p MJPEG stream served by Flask.*

---

## Figure 4 — Detection Sequence (Debounce Proof)

| No subject | Subject enters | Stable PRESENT |
|---|---|---|
| ![No subject](docs/images/04-detection-seq-1.jpg "No subject") | ![Subject enters](docs/images/04-detection-seq-2.jpg "Subject enters") | ![Stable PRESENT](docs/images/04-detection-seq-3.jpg "Stable PRESENT") |

*Debounce eliminates flicker during transitions.*

---

## Figure 5 — ROI / Overlay (Optional)

![Figure 5 — ROI](docs/images/05-roi-overlay.jpg "ROI overlay on frame")
*Region-of-interest drawn to focus detection.*

---

## Figure 6 — Metrics: Raw CSV Transitions

![Figure 6 — CSV](docs/images/06-metrics-csv.png "detections.csv (timestamp,present)")
*Each row is a debounced flip: `timestamp,present` (1=present, 0=absent).*

---

## Figure 7 — Metrics: Timeline Chart

![Figure 7 — Timeline](docs/images/07-metrics-chart.png "Presence step chart")
*Presence episodes over time derived from the CSV.*

---

## Figure 8 — Hardware: Top View

![Figure 8 — Hardware Top](docs/images/08-hardware-top.jpg "Pi + camera assembly")
*Raspberry Pi + IMX219 camera assembly.*

---

## Figure 9 — Hardware: Placement / Angle

![Figure 9 — Placement](docs/images/09-hardware-side.jpg "Typical installation geometry")
*Camera aimed at the test scene (distance/angle visible).*

---

## Figure 10 — Ops Proof: systemd Status

![Figure 10 — systemd status](docs/images/10-systemd-status.png "box-stream active (running)")
*Service enabled and running on boot.*

---

## Figure 11 — Ops Proof: Reachability

![Figure 11 — Reachability](docs/images/11-browser-reachable.png "curl/http check")
*HTTP endpoint reachable on the LAN.*
```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-opencv python3-flask

cd ~
git clone https://github.com/CDonohoe-Designs/PiCam_BoxDetector.git
cd PiCam_BoxDetector
python3 scripts/box_stream.py
```

Then I open:

- `http://<pi-ip>:8000/video` (detection + HUD)  
- `http://<pi-ip>:8000/video_raw` (raw camera only)  
- `http://<pi-ip>:8000/snapshot` (saves two JPGs to `samples/`)  
- `http://<pi-ip>:8000/health`  


## How I run it on boot (systemd)

```bash
sudo tee /etc/systemd/system/box-detector.service >/dev/null << 'EOF'
[Unit]
Description=PiCam Box Detector (Flask stream)
After=network-online.target

[Service]
Type=simple
User=rpicd
WorkingDirectory=/home/rpicd/PiCam_BoxDetector
ExecStartPre=/bin/sleep 3
ExecStart=/usr/bin/python3 /home/rpicd/PiCam_BoxDetector/scripts/box_stream.py
Restart=on-failure
RestartSec=2

# Optional env overrides (see “Config via env” below)
Environment=PYTHONUNBUFFERED=1
Environment=BOX_PORT=8000
Environment=BOX_JPEG_QUALITY=70
Environment=BOX_RES_W=960
Environment=BOX_RES_H=540

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now box-detector
sudo systemctl status box-detector
```

**My workflow**
```bash
cd ~/PiCam_BoxDetector && git pull
sudo systemctl restart box-detector
journalctl -u box-detector -f
```


## Endpoints I expose

| Route        | What I use it for                                       |
|--------------|----------------------------------------------------------|
| `/video`     | Main MJPEG stream with HUD + debounced detection         |
| `/video_raw` | Raw stream (camera/Flask sanity check)                   |
| `/snapshot`  | Saves `*_original.jpg` and `*_detected.jpg` to `samples/`|
| `/health`    | JSON “ok” with version/uptime                            |
| `/config`    | IP, port, resolution, JPEG quality, uptime               |
=======
| `/snapshot`  | Saves `*_original.jpg` and `*_detected.jpg` to `samples/`|
| `/health`    | JSON “ok” with version/uptime                            |
>>>>>>> 422cfba7e6c05c49fcba939680557be06388ef6a

---

## Config via environment variables

- `BOX_PORT` (default `8000`)
- `BOX_RES_W`, `BOX_RES_H` (e.g., `960x540` runs nicely on a Pi 3)
- `BOX_JPEG_QUALITY` (default `70`)

Set at runtime:
```bash
sudo systemctl set-environment BOX_RES_W=960 BOX_RES_H=540 BOX_JPEG_QUALITY=70
sudo systemctl restart box-detector
```
---

## How it works (short)



## Tuning notes

- I keep a small **border** between the box and frame edges (contours are cleaner).
- I avoid glare; even lighting works best.
- For smoothness on a Pi 3, I like **960×540** with JPEG quality **~70**.

---


**My “reset if needed” one-liner:**
```bash
sudo systemctl restart box-detector && sleep 2 && curl -s http://127.0.0.1:8000/health
```

---


**“Device or resource busy”**  
I stop the service before running the script manually:
```bash
sudo systemctl stop box-detector
python3 scripts/box_stream.py
```

**500 on `/video`**  
I open `/video_raw` to isolate camera/Flask. If raw works, I tail logs:
```bash
journalctl -u box-detector -n 80 --no-pager -l
```
In code, I guard the generator so per-frame hiccups won’t kill the stream.

**Port already in use**  
```bash
sudo fuser -k 8000/tcp
sudo systemctl restart box-detector
```
