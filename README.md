# PiCam Box Detector

I built a lightweight, real-time **box detector** on a Raspberry Pi using **Picamera2 + OpenCV + Flask**. It streams an MJPEG feed, draws a green rectangle around boxes (e.g., parcels), and exposes endpoints for snapshots, health, and config. It’s tuned for demos with a short warm-up and **debounced detections** so the “Boxes: 1” indicator is rock-solid.

- **Hardware:** Raspberry Pi 3 Model B + Pi Camera v2.1  
- **OS:** Raspberry Pi OS (Bookworm)  
- **Language:** Python 3

> Images live in `docs/images/`. Filenames below must match exactly (case-sensitive).

---

## What I built

- Live video at **`/video`** with a small HUD (version, FPS, IP/port, endpoints).  
- **`/video_raw`** to bypass detection for fast debugging.  
- **`/snapshot`** to save before/after pairs to `samples/`.  
- **`/health`** and **`/config`** for quick checks during demos.  
- Robust detection:
  - LAB + CLAHE → adaptive threshold → contours → convex quad / rotated rect.  
  - Warm-up (ignore first ~1s) + hysteresis (hits/misses) to prevent flicker.  
  - Full-frame guard so startup noise doesn’t count as a detection.
- Runs as a **systemd** service (auto-start on boot, restart on failure).

---

## Figure 1 — Landing

![Figure 1 — Landing](docs/images/01-landing.jpg "Landing page at http://<pi-ip>:8000")  
*Browser landing page at `http://<pi-ip>:8000` with links to `/video` and `/snapshot`.*

---

## Figure 2 — System Architecture

![Figure 2 — System Architecture](docs/images/02-architecture.png "Camera → Picamera2 → OpenCV → Debounce/Hysteresis → Flask → Browser")  
*Camera → Picamera2 → OpenCV (boxes) → Debounce/Hysteresis → Flask HTTP → Browser.*

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

![Figure 10 — systemd status](docs/images/10-systemd-status.png "box-detector active (running)")  
*Service enabled and running on boot.*

---

## Figure 11 — Ops Proof: Reachability

![Figure 11 — Reachability](docs/images/11-browser-reachable.png "curl/http check")  
*HTTP endpoint reachable on the LAN.*

---

## Quickstart

```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-opencv python3-flask

cd ~
git clone https://github.com/CDonohoe-Designs/PiCam_BoxDetector.git
cd PiCam_BoxDetector
python3 scripts/box_stream.py

