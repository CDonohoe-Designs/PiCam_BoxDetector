# PiCam Box Detector

I built a lightweight, real-time **box detector** on a Raspberry Pi using **Picamera2 + OpenCV + Flask**. It streams an MJPEG feed, draws a green rectangle around boxes (e.g., parcels), and exposes endpoints for snapshots, health, and config. I tuned it for demos with a short warm-up and debounced detections so the “Boxes: 1” indicator is rock-solid.

**Hardware:** Raspberry Pi 3 Model B + Pi Camera v2.1  
**OS:** Raspberry Pi OS (Bookworm)  
**Language:** Python 3


## Repo structure

---

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

## Quick start (on the Pi)

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


> If you see “Device or resource busy”, make sure the systemd service isn’t running while you start the script manually.

---

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

> Note:  never run `python3 scripts/box_stream.py` while the service is active (the camera can only be opened by one process).

---

## Endpoints I expose

| Route        | What I use it for                                       |
|--------------|----------------------------------------------------------|
| `/video`     | Main MJPEG stream with HUD + debounced detection         |
| `/video_raw` | Raw stream (camera/Flask sanity check)                   |
| `/snapshot`  | Saves `*_original.jpg` and `*_detected.jpg` to `samples/`|
| `/health`    | JSON “ok” with version/uptime                            |

---

## Config via environment variables

Read these (with defaults) so u can tune without editing code:

- `BOX_PORT` (default `8000`)
- `BOX_RES_W`, `BOX_RES_H` (e.g., `960x540` runs nicely on a Pi 3)
- `BOX_JPEG_QUALITY` (default `70`)
- `BOX_WEBHOOK_URL` (optional; if u decide to POST events later)

Set at runtime:
```bash
sudo systemctl set-environment BOX_RES_W=960 BOX_RES_H=540 BOX_JPEG_QUALITY=70
sudo systemctl restart box-detector
```
To persist, u edit the `Environment=` lines in the unit, then `daemon-reload` + restart.

---

## How it works (short)

1. capture frames with Picamera2 at the configured resolution.  
2. boost luminance contrast (LAB + CLAHE), then apply **adaptive threshold (INV)**.  
3. clean the mask (median + close), then find **external contours**.  
4. try a convex **quad**; if that fails I use **minAreaRect** (rotated rect).  
5. filter by area/aspect/rectangularity and draw the best match.  
6. apply **warm-up** and **hysteresis** so “Boxes: 1” is stable.  
7. render a small HUD (version, FPS, endpoints) onto the stream.

---

## Tuning notes

- I keep a small **border** between the box and frame edges (contours are cleaner).
- I avoid glare; even lighting works best.
- For smoothness on a Pi 3, I like **960×540** with JPEG quality **~70**.

---

## Demo playbook I use

1. `http://<pi-ip>:8000/health` → JSON “ok”.  
2. `http://<pi-ip>:8000/video_raw` → camera path OK.  
4. `http://<pi-ip>:8000/video` → HUD + stable “Boxes: 1”.  
5. `/snapshot` → I show the two saved JPGs in `samples/`.

**My “reset if needed” one-liner:**
```bash
sudo systemctl restart box-detector && sleep 2 && curl -s http://127.0.0.1:8000/health
```

---

## Troubleshooting I ran into

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

---

## What I’ll add next

- I’ll log ON/OFF transitions to `detections.csv` and (optionally) POST to a webhook.  
- I’ll add an ROI to ignore frame borders or define a detection zone.  
- I’ll package a tiny UI for a prettier dashboard, and try a small YOLOv8n path.

---

## License

MIT (or my preferred license).
