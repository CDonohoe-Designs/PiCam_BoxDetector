#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PiCam-BoxDetector — Flask MJPEG stream with simple contour-based box detection.

# Author: Caoilte Donohoe
# Project: PiCam-BoxDetector
# Created: 2025-10-03
# Python: 3.9+ on Raspberry Pi OS

Hardware: Raspberry Pi 3B, PiCam v2.1 (IMX219)
Stack: Python 3, Picamera2/libcamera, OpenCV, Flask

Usage:
    python3 stream.py
    # then open http://<PI-IP>:8000/  (find IP with `hostname -I`)

Endpoints:
    GET /        - index with link
    GET /video   - MJPEG stream
    GET /healthz - health probe (200 OK)

Notes:
    - Recommend running inside venv: source ~/venvs/picam/bin/activate
    - If headless, camera is fine without X; Picamera2 returns RGB arrays.
"""

import signal
import sys
import time
from typing import Generator, Optional

import cv2
import numpy as np
from flask import Flask, Response
from picamera2 import Picamera2

# -------- Camera setup --------
picam: Optional[Picamera2] = Picamera2()
# 720p is a good balance for Pi 3
config = picam.create_video_configuration(main={"size": (1280, 720)}, buffer_count=4)
picam.configure(config)
picam.start()
time.sleep(0.5)  # small warm-up

# -------- Flask app --------
app = Flask(__name__)

def find_boxes(frame_bgr: np.ndarray) -> np.ndarray:
    """Return a frame with detected rectangular 'boxes' outlined."""
    img = frame_bgr.copy()
    h, w = img.shape[:2]

    # Preprocess
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    # Edges
    edges = cv2.Canny(gray, 50, 150)
    edges = cv2.dilate(edges, None, iterations=1)

    # Contours
    cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Filters
    min_area = (w * h) * 0.002   # ignore tiny blobs
    max_area = (w * h) * 0.8     # ignore near-full-frame blobs

    for c in cnts:
        area = cv2.contourArea(c)
        if area < min_area or area > max_area:
            continue

        # Polygonal approximation
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)

        # 4-vertex convex shapes → candidate boxes
        if len(approx) == 4 and cv2.isContourConvex(approx):
            x, y, bw, bh = cv2.boundingRect(approx)

            # Aspect/rectangularity checks
            aspect = bw / float(bh) if bh > 0 else 0
            if 0.3 < aspect < 3.5:
                rect_area = bw * bh
                if rect_area > 0 and (area / rect_area) > 0.6:
                    cv2.rectangle(img, (x, y), (x + bw, y + bh), (0, 255, 0), 2)
                    cv2.putText(img, "BOX", (x, y - 6),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    return img

def mjpeg_generator() -> Generator[bytes, None, None]:
    """Yield MJPEG frames with drawn boxes."""
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), 80]  # tradeoff for Pi 3
    while True:
        frame = picam.capture_array()  # RGB
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        boxed = find_boxes(frame_bgr)

        ok, jpg = cv2.imencode(".jpg", boxed, encode_params)
        if not ok:
            continue

        frame_bytes = jpg.tobytes()
        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n")

@app.route("/")
def index():
    return ("<h2>Pi Box Detector</h2>"
            "<p>Stream: <a href='/video'>/video</a></p>")

@app.route("/video")
def video():
    return Response(mjpeg_generator(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/healthz")
def healthz():
    return "ok", 200

def _cleanup(*_args):
    """Gracefully stop camera on SIGINT/SIGTERM."""
    global picam
    try:
        if picam:
            picam.stop()
    except Exception:
        pass
    sys.exit(0)

if __name__ == "__main__":
    # Graceful shutdown on Ctrl+C / systemd stop
    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    # Bind to all interfaces on port 8000 (threaded for MJPEG)
    app.run(host="0.0.0.0", port=8000, threaded=True, debug=False)
