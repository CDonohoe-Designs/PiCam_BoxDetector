#Touched: snapshot-endpoint test 2
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PiCam Box Detector — Raspberry Pi 3 Model B + PiCam v2.1
Streams MJPEG video with rectangular "box" detection (edges → contours → 4-vertex approx)
and provides a /snapshot endpoint to save before/after images to samples/.

Endpoints
---------
/          : index with links
/video     : MJPEG stream with detections + box count overlay
/snapshot  : capture one frame, save original & detected JPGs into samples/

Quick Start (on Raspberry Pi OS)
--------------------------------
sudo apt update && sudo apt -y upgrade
sudo apt -y install python3-picamera2 python3-opencv python3-flask libatlas-base-dev python3-numpy
python3 scripts/box_stream.py
# Open http://<pi-ip>:8000/video  or  /snapshot

Repo
----
https://github.com/CDonohoe-Designs/PiCam_BoxDetector

License
-------
MIT
"""

__author__  = "Caoilte Donohoe"
__version__ = "0.2.2"
__license__ = "MIT"
__date__    = "2025-10-04"

import os
import sys
import time
import signal
import logging
from datetime import datetime

import cv2
import numpy as np
from flask import Flask, Response
from picamera2 import Picamera2
from flask import jsonify
from collections import deque
START_TIME = time.time()

PORT         = int(os.getenv("BOX_PORT", "8000"))
JPEG_QUALITY = int(os.getenv("BOX_JPEG_QUALITY", "70"))
RES_W        = int(os.getenv("BOX_RES_W", "1280"))
RES_H        = int(os.getenv("BOX_RES_H", "720"))

# Debounce + warm-up (tweak if needed)
HIT_THRESHOLD  = 4      # hits in a row to turn ON
MISS_THRESHOLD = 10     # misses in a row to turn OFF
STARTUP_WARMUP_FRAMES = 30  # ignore first ~1 second
LATCH_FRAMES = 10  # ~1/3–1/2 s at ~20–30 FPS

print("BOX_DETECTOR MODE: threshold+largest-blob v0.3")

import socket
from datetime import datetime

def _get_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "0.0.0.0"
    finally:
        try: s.close()
        except Exception: pass
    return ip

HOST_IP = _get_ip()


# --------------------------- Logging ---------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("box_detector")

# --------------------------- Paths -----------------------------
# samples/ lives one level up from this script (repo root/samples)
SCRIPTDIR   = os.path.dirname(os.path.abspath(__file__))
SAMPLES_DIR = os.path.normpath(os.path.join(SCRIPTDIR, "..", "samples"))
os.makedirs(SAMPLES_DIR, exist_ok=True)

# --------------------------- Camera ----------------------------
picam = Picamera2()

# config = picam.create_video_configuration(main={"size": (1280, 720)}, buffer_count=4)  # try (960,540) if needed
config = picam.create_video_configuration(main={"size": (RES_W, RES_H)}, buffer_count=4)
picam.configure(config)
picam.start()
time.sleep(0.3)

#---------------------------Add----------------------------------
try:
    picam.set_controls({"Sharpness": 1.5, "Contrast": 1.0})
except Exception:
    pass

log.info("Picamera2 started with %s", config)

# --------------------------- App -------------------------------
app = Flask(__name__)

def draw_hud(img, fps: float | None, present: int, raw: int):
    """
    Overlay a small translucent panel with project info, FPS, and endpoints.
    """
    h, w = img.shape[:2]

    # translucent panel
    overlay = img.copy()
    panel_h = 92
    cv2.rectangle(overlay, (8, 8), (min(8 + int(w * 0.75), w - 8), 8 + panel_h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.35, img, 0.65, 0, img)

    # lines
    ts = datetime.now().strftime("%H:%M:%S")
    line1 = f"PiCam Box Detector v{__version__}  |  {RES_W}x{RES_H}  |  {ts}"
    if fps is not None:
        line2 = f"Boxes: {present}  (raw:{raw})  |  FPS: {fps:.1f}"
    else:
        line2 = f"Boxes: {present}  (raw:{raw})"
    line3 = f"http://{HOST_IP}:{PORT}/video   /snapshot   /health"

    cv2.putText(img, line1, (16, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2)
    cv2.putText(img, line2, (16, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2)
    cv2.putText(img, line3, (16, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (220, 220, 220), 1)

def find_boxes(frame_bgr: np.ndarray) -> tuple[np.ndarray, int]:
    """
    Robust box detector:
      1) LAB/CLAHE -> adaptive threshold (inverse)
      2) Pad the image so objects touching frame edges close properly
      3) Contours -> convex quad OR rotated rect
      4) Fallback: largest blob minAreaRect if all filters fail
    Returns (annotated_image, detection_count).
    """
    img = frame_bgr.copy()
    H, W = img.shape[:2]

    # --- Contrast boost on luminance ---
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    L, A, B = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    Lc = clahe.apply(L)

    # --- Adaptive threshold (invert: object -> white) ---
    thr = cv2.adaptiveThreshold(
        Lc, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        25, 7
    )
    thr = cv2.medianBlur(thr, 3)
    thr = cv2.morphologyEx(thr, cv2.MORPH_CLOSE, None, iterations=2)

    # --- Pad both mask and RGB so frame-touching boxes are closed ---
    PAD = 8
    thr_pad = cv2.copyMakeBorder(thr, PAD, PAD, PAD, PAD, cv2.BORDER_CONSTANT, value=0)
    img_pad = cv2.copyMakeBorder(img, PAD, PAD, PAD, PAD, cv2.BORDER_REPLICATE)

    # --- Contours on padded mask ---
    cnts, _ = cv2.findContours(thr_pad, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    min_area = (W * H) * 0.01    # start at 1% of frame
    max_area = (W * H) * 0.99

    detections = 0
    best = None  # keep track of the largest good candidate

    for c in cnts:
        area = cv2.contourArea(c)
        if area < min_area or area > max_area:
            continue

        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.015 * peri, True)

        # try convex quad
        if len(approx) == 4 and cv2.isContourConvex(approx):
            x, y, w, h = cv2.boundingRect(approx)
            if h == 0 or w == 0:
                continue
            aspect = max(w, h) / float(min(w, h))
            rectangularity = area / (w * h)
            if 0.2 < aspect < 6.0 and rectangularity > 0.50:
                # unpad draw coords
                x, y = x - PAD, y - PAD
                cv2.rectangle(img, (x, y), (x + w, y + h), (0, 255, 0), 2)
                detections += 1
                continue

        # rotated rectangle fallback for this contour
        (cx, cy), (rw, rh), angle = cv2.minAreaRect(c)
        if rw < 1 or rh < 1:
            continue
        r_area = rw * rh
        if r_area < min_area or r_area > max_area:
            continue
        aspect = max(rw, rh) / min(rw, rh)
        rectangularity = area / r_area
        if 0.2 < aspect < 6.0 and rectangularity > 0.45:
            if best is None or area > best[0]:
                best = (area, (cx, cy), (rw, rh), angle)

    # draw best rotated rectangle if no quads were drawn
    if detections == 0 and best is not None:
        _, (cx, cy), (rw, rh), angle = best
        box = cv2.boxPoints(((cx, cy), (rw, rh), angle))
        box = np.int32(box - [PAD, PAD])  # unpad
        cv2.drawContours(img, [box], 0, (0, 255, 0), 2)
        detections = 1

    return img, detections



def mjpeg_generator():
    """
    MJPEG stream with warm-up + hysteresis and robust exception handling.
    Any per-frame error is logged and the loop continues (no 500).
    """
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]

    present = False
    hits = 0
    misses = 0
    frame_i = 0

    fps_intervals = deque(maxlen=15)
    last_t = time.time()

    while True:
        try:
            # --- capture ---
            frame_rgb = picam.capture_array()
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

            # --- detect ---
            boxed, raw_count = find_boxes(frame_bgr)

            frame_i += 1

            # --- warm-up ignore ---
            if frame_i <= STARTUP_WARMUP_FRAMES:
                hits = 0
                misses = 0
                present = False
            else:
                # hysteresis
                if raw_count > 0:
                    hits += 1; misses = 0
                    if not present and hits >= HIT_THRESHOLD:
                        present = True
                else:
                    misses += 1; hits = 0
                    if present and misses >= MISS_THRESHOLD:
                        present = False

            # --- FPS smoothing ---
            now = time.time()
            fps_intervals.append(now - last_t)
            last_t = now
            fps = None
            if len(fps_intervals) >= 5:
                fps = len(fps_intervals) / max(sum(fps_intervals), 1e-6)

            # --- overlays (HUD if available, else minimal text) ---
            if 'draw_hud' in globals():
                try:
                    draw_hud(
                        boxed,
                        fps=fps,
                        present=(1 if present else 0),
                        raw=raw_count
                    )
                    if frame_i <= STARTUP_WARMUP_FRAMES:
                        cv2.putText(boxed, "Warming up...", (16, 108),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2)
                except Exception:
                    # Never let HUD errors kill the stream
                    pass
            else:
                if fps is not None:
                    cv2.putText(boxed, f"FPS ~ {fps:.1f}", (10, 24),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)
                cv2.putText(boxed, f"Boxes: {1 if present else 0}  (raw:{raw_count})",
                            (10, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)

            # --- encode & yield ---
            ok, jpg = cv2.imencode(".jpg", boxed, encode_params)
            if not ok:
                continue

            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n")

        except Exception as e:
            # Log and keep streaming rather than 500
            try:
                log.exception("mjpeg loop error")
            except Exception:
                print("mjpeg loop error:", e)
            time.sleep(0.02)
            continue


@app.route("/")
def index():
    return ("<h2>Tomra Demo by Caoilte Donohoe....Pi Box Detector</h2>"
            "<p>Stream: <a href='/video'>/video</a></p>"
            "<p>Snapshot: <a href='/snapshot'>/snapshot</a></p>")

@app.route("/health")
def health():
    return jsonify(status="ok", version=__version__), 200

@app.route("/video")
def video():
    return Response(mjpeg_generator(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/snapshot")
def snapshot():
    """Capture one frame, save original and detected images to samples/."""
    frame_rgb = picam.capture_array()
    frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

    boxed, count = find_boxes(frame_bgr)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"capture_{ts}"

    orig_path = os.path.join(SAMPLES_DIR, f"{base}_original.jpg")
    det_path  = os.path.join(SAMPLES_DIR, f"{base}_detected.jpg")

    cv2.imwrite(orig_path, frame_bgr)
    cv2.imwrite(det_path, boxed)

    log.info("Saved %s and %s (boxes=%d)", orig_path, det_path, count)
    return (f"<pre>Saved:\n  samples/{os.path.basename(orig_path)}\n"
            f"  samples/{os.path.basename(det_path)}\nboxes={count}</pre>"
            "<p><a href='/video'>Back to stream</a></p>")

@app.route("/config", methods=["GET"])
def config_view():
    return jsonify(
        status="ok",
        version=__version__,
        ip=HOST_IP,
        port=PORT,
        res=[RES_W, RES_H],
        jpeg_quality=JPEG_QUALITY,
        uptime_s=int(time.time() - START_TIME),
    ), 200

# ---------------------- Graceful Shutdown ----------------------
def _shutdown(*_):
    log.info("Shutting down...")
    try:
        picam.stop()
    except Exception as e:
        log.warning("Error stopping camera: %s", e)
    sys.exit(0)

signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)

# --------------------------- Main ------------------------------
if __name__ == "__main__":
    log.info("Starting Flask server on 0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, threaded=True)

