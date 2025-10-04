PiCam Box Detector

I built a lightweight, real-time box detector on a Raspberry Pi using Picamera2 + OpenCV + Flask. It streams an MJPEG feed, draws a green box around parcels/cardboard boxes, and exposes a couple of handy endpoints for snapshots, health, and config. I tuned it to be demo-ready (stable detection, warm-up, and auto-start on boot).

Hardware: Raspberry Pi 3 Model B + Pi Camera v2.1
OS: Raspberry Pi OS (Bookworm)
Language: Python 3

What I built

I stream live video at /video with a small HUD (version, FPS, IP/port, endpoints).

I added a raw camera stream at /video_raw for quick diagnosis (no detection path).

I save before/after snapshot pairs to samples/ via /snapshot.

I expose /health and /config for quick checks during a demo.

I made the detector robust:

When I detect, I use CLAHE → adaptive threshold → contours → convex quad or rotated rectangle.

I added warm-up (ignore the first ~1s) and hysteresis (hits/misses) to kill flicker.

I guard against “full-frame” blobs so startup noise doesn’t show as a box.

I run it as a systemd service so it auto-starts on boot and restarts on failure.

Quick start (on the Pi)
sudo apt update
sudo apt install -y python3-picamera2 python3-opencv python3-flask

cd ~
git clone https://github.com/CDonohoe-Designs/PiCam_BoxDetector.git
cd PiCam_BoxDetector
python3 scripts/box_stream.py


Then I open these in a browser:

http://<pi-ip>:8000/video (detection + HUD)

http://<pi-ip>:8000/video_raw (raw camera only)

http://<pi-ip>:8000/snapshot (saves two JPGs to samples/)

http://<pi-ip>:8000/health

http://<pi-ip>:8000/config

If I see “Device or resource busy”, I make sure the systemd service isn’t running while I run the script manually.

How I run it on boot (systemd)

I created this service (adjust user/path if needed):

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

# Optional env overrides (see “Config via env”)
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


My day-to-day workflow:

# deploy updates
cd ~/PiCam_BoxDetector && git pull
sudo systemctl restart box-detector

# watch logs
journalctl -u box-detector -f


I never run python3 scripts/box_stream.py while the service is active—the camera can only be opened by one process.

Endpoints I expose
Route	What I use it for
/video	Main MJPEG stream with HUD + debounced detection
/video_raw	Raw stream to prove camera/Flask path is healthy
/snapshot	Saves *_original.jpg and *_detected.jpg to samples/
/health	Quick JSON “ok” with version/uptime
/config	Current IP, port, resolution, JPEG quality, uptime
Config via environment variables

I read these (with safe defaults) so I can tune without editing code:

BOX_PORT (default 8000)

BOX_RES_W, BOX_RES_H (e.g., 960x540 runs nicely on a Pi 3)

BOX_JPEG_QUALITY (default 70)

BOX_WEBHOOK_URL (optional; if I decide to POST events later)

I can set them at runtime in systemd and restart:

sudo systemctl set-environment BOX_RES_W=960 BOX_RES_H=540 BOX_JPEG_QUALITY=70
sudo systemctl restart box-detector


To persist, I edit the Environment= lines in the unit and daemon-reload + restart.

How it works (short version)

I capture frames with Picamera2 at the configured resolution.

I boost contrast on luminance (LAB + CLAHE), then I apply adaptive threshold (inverse).

I clean the mask (median + close), then I find external contours.

For each contour I try a convex quad first; if that fails I fit a rotated rectangle (minAreaRect).

I filter candidates by area, aspect, and rectangularity, and I draw the best match.

I apply warm-up (ignore first ~30 frames) and hysteresis (X hits to turn ON, Y misses to turn OFF) so “Boxes: 1” is stable.

I render a small HUD (version, FPS, endpoints) on the stream.

Tuning notes

I keep a little border between the box and the frame edges (contours are more stable).

I avoid glare; even lighting works best.

For smoothness on a Pi 3, I like 960x540 and JPEG quality ~70.

Demo playbook I use

http://<pi-ip>:8000/health → I show the JSON is ok.

http://<pi-ip>:8000/config → I point out resolution/JPEG/uptime.

http://<pi-ip>:8000/video_raw → I prove the camera path is good.

http://<pi-ip>:8000/video → I show the HUD and a stable “Boxes: 1”.

I hit /snapshot once and show the two saved JPGs in samples/.

I explain warm-up + hysteresis and how I’d extend this (below).

My quick recovery command (if anything looks off):

sudo systemctl restart box-detector && sleep 2 && curl -s http://127.0.0.1:8000/health

Repo structure
PiCam_BoxDetector/
├─ scripts/
│  ├─ box_stream.py        # Flask app, detection, endpoints, HUD
│  └─ demo_reset.sh        # (optional) one-liner demo helper
├─ samples/                # snapshot images land here
├─ requirements.txt
└─ README.md
