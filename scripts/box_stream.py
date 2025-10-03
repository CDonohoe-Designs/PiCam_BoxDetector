# touched: snapshot-endpoint test 
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
__version__ = "0.2.0"
__license__ = "MIT"
__date__    = "2025-10-03"

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
config = picam.create_video_configuration(main={"size": (1280, 720)}, buffer_count=4)  # try (960,540) if needed
picam.configure(config)
picam.start()
time.sleep(0.5)
log.info("Picamera2 started with %s", config)

# --------------------------- App -------------------------------
app = Flask(__name__)

def find_boxes(frame_bgr: np.ndarray) -> tuple[np.ndarray, int]:
    """
    Detect rectangular 'boxes' and draw rectangles with a label.
    Returns (annotated_image, detection_count).
    """
    img = frame_bgr.copy()
    h, w = img.shape[:2]

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    edges = cv2.Canny(gray, 50, 150)
    edges = cv2.dilate(edges, None, iterations=1)

    cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    min_area = (w * h) * 0.002
    max_area = (w * h) * 0.80

    detections = 0
    for c in cnts:
        area = cv2.contourArea(c)
        if area < min_area or area > max_area:
            continue

        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)

        if len(approx) == 4 and cv2.isContourConvex(approx):
            x, y, bw, bh = cv2.boundingRect(approx)
            if bh == 0:
                continue
            aspect = bw / float(bh)
            rect_area = bw * bh
            rectangularity = area / rect_area if rect_area else 0
            if 0.3 < aspect < 3.5 and rectangularity > 0.60:
                detections += 1
                cv2.rectangle(img, (x, y), (x + bw, y + bh), (0, 255, 0), 2)
                cv2.putText(img, "BOX", (x, y - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    return img, detections

def mjpeg_generator():
    """Capture frames, run detection, and yield an MJPEG stream."""
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), 80]  # lower for speed
    fps_t0 = time.time()
    frames = 0
    while True:
        frame_rgb = picam.capture_array()
        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

        boxed, count = find_boxes(frame_bgr)

        # overlays
        frames += 1
        if frames % 15 == 0:
            now = time.time()
            fps = 15.0 / max(now - fps_t0, 1e-6)
            fps_t0 = now
            cv2.putText(boxed, f"FPS ~ {fps:.1f}", (10, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        cv2.putText(boxed, f"Boxes: {count}", (10, 48),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        ok, jpg = cv2.imencode(".jpg", boxed, encode_params)
        if not ok:
            log.warning("JPEG encode failed; skipping frame")
            continue

        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n")

@app.route("/")
def index():
    return ("<h2>Pi Box Detector</h2>"
            "<p>Stream: <a href='/video'>/video</a></p>"
            "<p>Snapshot: <a href='/snapshot'>/snapshot</a></p>")

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

