# PiCam_BoxDetector

I built this Raspberry Pi presence detector with a live MJPEG stream. Next I added debounced state changes and CSV logging so I can measure real “in/out” events. This README is **image-first** so a reviewer can scan the flow quickly.

---

## 1) Landing / Demo
![Landing view](docs/images/01-landing.jpg)

*Browser page on `http://<pi-ip>:8000` with links to the live stream (`/video`) and a still snapshot (`/snapshot`).*

---

## 2) System Architecture
![Architecture](docs/images/02-architecture.png)

*Camera → OpenCV presence → Debounce & CSV → Flask MJPEG → Browser.*

---

## 3) Stream UI (Detail)
![Stream UI](docs/images/03-stream-ui.jpg)

*Clean 720p preview served as HTTP MJPEG.*

---

## 4) Detection Sequence (Insert your 3 frames)
<!-- Replace the placeholders below with your actual images -->
![No subject](docs/images/04-detection-seq-1.jpg)
![Subject enters](docs/images/04-detection-seq-2.jpg)
![Stable Present](docs/images/04-detection-seq-3.jpg)

*Debounce prevents flicker during transitions.*

---

## 5) ROI / Overlay (Optional)
![ROI overlay](docs/images/05-roi-overlay.jpg)

*Focus detection to a region of interest for stability.*

---

## 6) Metrics – CSV Transitions
![CSV transitions](docs/images/06-metrics-csv.png)

*I append a row whenever debounced presence flips (epoch, present).*

---

## 7) Metrics – Timeline
![Presence chart](docs/images/07-metrics-chart.png)

*Step plot of presence vs time built from the CSV.*

---

## 8) Hardware – Assembly
![Top view](docs/images/08-hardware-top.jpg)
![Placement](docs/images/09-hardware-side.jpg)

*Raspberry Pi + IMX219 camera and typical placement.*

---

## 9) Ops Proof
![systemd status](docs/images/10-systemd-status.png)
![Reachable](docs/images/11-browser-reachable.png)

*Auto-start on boot (systemd) and reachable on LAN.*

---

## 10) Tuning & Edge Conditions
![Low threshold (noisy)](docs/images/12-threshold-low.jpg)
![Higher threshold (stable)](docs/images/13-threshold-high.jpg)
![Lighting montage](docs/images/14-edge-lighting-montage.jpg)

*Threshold and lighting examples.*

---

## Quickstart
```bash
sudo apt update && sudo apt install -y python3-pip python3-opencv libatlas-base-dev
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/box_stream.py
# visit http://<pi-ip>:8000
```

## Notes
- I keep dependencies in a **venv** so system Python stays clean.
- Logging: `detections.csv` appends on state flips only (compact, auditable).
- Service: use `systemd/box-stream.service` for boot start.

## License
MIT
