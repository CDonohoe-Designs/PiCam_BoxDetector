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

from collections import deque
LATCH_FRAMES = 10  # ~1/3–1/2 s at ~20–30 FPS

print("BOX_DETECTOR MODE: threshold+largest-blob v0.3")

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

#---------------------------Add----------------------------------
try:
    picam.set_controls({"Sharpness": 1.5, "Contrast": 1.0})
except Exception:
    pass
time.sleep(0.3)
log.info("Picamera2 started with %s", config)

# --------------------------- App -------------------------------
app = Flask(__name__)

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
    Capture frames, run detection, and yield an MJPEG stream.
    Adds:
      - detection latch to avoid 1->0 flicker
      - smoothed FPS overlay
      - Boxes: <0/1> overlay using the latched state
    """
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), 70]  # 70 is faster on Pi 3
    latched = 0

    # simple rolling FPS over the last N frame intervals
    fps_intervals = deque(maxlen=15)
    last_t = time.time()

    while True:
        # Grab frame and convert to BGR for OpenCV
        frame_rgb = picam.capture_array()
        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

        # Run your detector (must return (annotated_img, count))
        boxed, count = find_boxes(frame_bgr)

        # ---- Latch logic: keep showing "present" briefly after a hit ----
        if count > 0:
            latched = LATCH_FRAMES
        else:
            latched = max(latched - 1, 0)
        display_count = 1 if latched > 0 else 0

        # ---- Overlays: FPS (smoothed) + Boxes ----
        now = time.time()
        fps_intervals.append(now - last_t)
        last_t = now
        if len(fps_intervals) >= 5:  # wait a few frames before showing
            fps = len(fps_intervals) / sum(fps_intervals)
            cv2.putText(boxed, f"FPS ~ {fps:.1f}", (10, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        cv2.putText(boxed, f"Boxes: {display_count}", (10, 48),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        # ---- Encode & yield MJPEG chunk ----
        ok, jpg = cv2.imencode(".jpg", boxed, encode_params)
        if not ok:
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

