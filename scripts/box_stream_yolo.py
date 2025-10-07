#!/usr/bin/env python3

"""
PiCam Box Detector — YOLO Edition (CPU / ONNXRuntime)
-----------------------------------------------------
Drop-in replacement for your existing Flask app that adds YOLOv8 (ONNX) inference.

Key endpoints (same as before):
  /video        → MJPEG with detection overlays
  /video_raw    → MJPEG without detection
  /snapshot     → Save before/after images to samples/
  /health       → "ok"
  /config       → JSON of current settings

Notes:
- Designed for Raspberry Pi 3 Model B + Pi Camera v2.1 (Picamera2)
- Runs ONNXRuntime (CPU) with a tiny YOLOv8 model. Expect low FPS on Pi 3; use FRAME_SKIP to keep UI smooth.
- Best path: export a custom-trained tiny model (see export_or_download_yolov8n_onnx.md) and copy it to models/yolov8n_boxes.onnx
- Falls back to COCO yolov8n.onnx if you haven't trained yet.
- We treat “box present” as "any detection meeting area/aspect thresholds". Tune in CONFIG below.

Author: You :)
"""
import os, time, threading, queue, json, pathlib, math, csv, io
from datetime import datetime

import numpy as np
import cv2
from flask import Flask, Response, jsonify, send_file
from picamera2 import Picamera2
import onnxruntime as ort

# -----------------------------
# CONFIG (tweak for performance)
# -----------------------------
CONFIG = {
    "MODEL_PATHS": [
        "models/yolov8n_boxes.onnx",   # your fine-tuned model (preferred)
        "models/yolov8n.onnx"          # generic COCO model (fallback)
    ],
    "INFER_SIZE": 640,          # YOLO input size
    "CONF_THRESH": 0.35,        # objectness * class_conf threshold
    "IOU_THRESH": 0.45,         # NMS IoU
    "ALLOWED_CLASSES": None,    # e.g., [0, 39, 40] if you trained custom classes; None = allow all
    "MIN_REL_AREA": 0.02,       # detection must cover ≥2% of frame
    "ASPECT_RANGE": (0.5, 2.0), # w/h must be within this range to look "box-like"
    "FRAME_SKIP": 2,            # run inference every N frames (2 = every 3rd frame shown is inferred)
    "WARMUP_SEC": 1.0,          # ignore detections for first N seconds
    "DEBOUNCE_UP": 3,           # require +N consecutive hits to go present=True
    "DEBOUNCE_DOWN": 6,         # require +N consecutive misses to go present=False
    "JPEG_QUALITY": 80,         # stream quality
    "CAP_SIZE": (640, 480),     # camera capture resolution
    "DRAW_SCORE": True,         # draw per-box score
    "HUD": True,                # draw HUD text
    "VERSION": "YOLO-ONNX v1.0",
}

BASE_DIR = pathlib.Path(__file__).resolve().parent
SAMPLES_DIR = BASE_DIR.parent / "samples"
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
MODELS_DIR = BASE_DIR.parent / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

LOG_PATH = BASE_DIR.parent / "detections.csv"

# -----------------
# Utils: Letterbox
# -----------------
def letterbox(im, new_size=640, color=(114,114,114)):
    h, w = im.shape[:2]
    scale = min(new_size / h, new_size / w)
    nh, nw = int(round(h * scale)), int(round(w * scale))
    resized = cv2.resize(im, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((new_size, new_size, 3), color, dtype=np.uint8)
    top = (new_size - nh) // 2
    left = (new_size - nw) // 2
    canvas[top:top+nh, left:left+nw] = resized
    return canvas, scale, left, top

# -----------------
# Utils: NMS
# -----------------
def nms(boxes, scores, iou_thresh=0.45):
    if len(boxes) == 0:
        return []
    boxes = boxes.astype(np.float32)
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1 + 1)
        h = np.maximum(0.0, yy2 - yy1 + 1)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-7)
        inds = np.where(iou <= iou_thresh)[0]
        order = order[inds + 1]
    return keep

# ---------------------------
# YOLOv8 ONNX Inference class
# ---------------------------
class YOLOv8ONNX:
    def __init__(self, model_paths):
        model = None
        for mp in model_paths:
            mp = (BASE_DIR.parent / mp).resolve()
            if mp.exists():
                model = mp
                break
        if model is None:
            raise FileNotFoundError(
                f"Could not find an ONNX model. Looked for: {model_paths}. "
                "See export_or_download_yolov8n_onnx.md for instructions."
            )
        self.model_path = str(model)
        providers = ['CPUExecutionProvider']
        self.session = ort.InferenceSession(self.model_path, providers=providers)
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name

    def infer(self, bgr, conf_thresh=0.3, iou_thresh=0.45, allowed_classes=None):
        # Preprocess
        img, scale, dx, dy = letterbox(bgr, CONFIG["INFER_SIZE"])
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        x = rgb.transpose(2,0,1).astype(np.float32) / 255.0
        x = np.expand_dims(x, 0)

        # Inference
        out = self.session.run([self.output_name], {self.input_name: x})[0]

        # Postprocess: support (1, N, 84) or (1, 84, N)
        if out.ndim == 3:
            if out.shape[1] == 84:  # (1,84,N)
                out = np.squeeze(out, 0).T
            else:                   # (1,N,84)
                out = np.squeeze(out, 0)
        else:
            out = np.squeeze(out, 0)

        # out: (N, 84) → [x,y,w,h, conf, 80 class probs] (COCO) or your custom classes
        boxes_xywh = out[:, :4]
        obj_conf = out[:, 4]
        cls_probs = out[:, 5:]
        cls_ids = np.argmax(cls_probs, axis=1)
        cls_conf = cls_probs[np.arange(cls_probs.shape[0]), cls_ids]
        scores = obj_conf * cls_conf

        # Filter by class (optional) and conf
        keep = scores >= conf_thresh
        if allowed_classes is not None:
            keep = np.logical_and(keep, np.isin(cls_ids, allowed_classes))
        boxes_xywh = boxes_xywh[keep]
        scores = scores[keep]
        cls_ids = cls_ids[keep]

        # Convert xywh (center) → xyxy on letterboxed image
        if boxes_xywh.size == 0:
            return []

        cx, cy, w, h = boxes_xywh.T
        x1 = cx - w/2
        y1 = cy - h/2
        x2 = cx + w/2
        y2 = cy + h/2
        boxes_xyxy = np.stack([x1, y1, x2, y2], axis=1)

        # Undo letterbox to original bgr size
        H, W = bgr.shape[:2]
        # map from 640 canvas back to original
        boxes_xyxy[:, [0,2]] -= dx
        boxes_xyxy[:, [1,3]] -= dy
        boxes_xyxy /= (CONFIG["INFER_SIZE"] / max(H, W))  # inverse of scale for largest dimension
        # Clamp
        boxes_xyxy[:, 0::2] = boxes_xyxy[:, 0::2].clip(0, W-1)
        boxes_xyxy[:, 1::2] = boxes_xyxy[:, 1::2].clip(0, H-1)

        # NMS
        keep_idx = nms(boxes_xyxy, scores, iou_thresh=iou_thresh)
        boxes_xyxy = boxes_xyxy[keep_idx]
        scores = scores[keep_idx]
        cls_ids = cls_ids[keep_idx]

        detections = []
        for (x1,y1,x2,y2), sc, cid in zip(boxes_xyxy, scores, cls_ids):
            detections.append({
                "xyxy": [float(x1), float(y1), float(x2), float(y2)],
                "score": float(sc),
                "class_id": int(cid),
            })
        return detections

# ---------------------------------------------------
# Detection worker thread (decouples cam & inference)
# ---------------------------------------------------
class DetectorThread(threading.Thread):
    def __init__(self, yolo, cap_size):
        super().__init__(daemon=True)
        self.yolo = yolo
        self.q = queue.Queue(maxsize=1)
        self.last_result = []
        self.frame_count = 0
        self.running = True
        self.cap_size = cap_size

    def run(self):
        while self.running:
            try:
                bgr = self.q.get(timeout=0.1)
            except queue.Empty:
                continue
            self.frame_count += 1
            if self.frame_count % (CONFIG["FRAME_SKIP"] + 1) != 0:
                # Skip inference to keep UI smooth
                self.last_result = self.last_result  # no change
                continue
            dets = self.yolo.infer(
                bgr,
                conf_thresh=CONFIG["CONF_THRESH"],
                iou_thresh=CONFIG["IOU_THRESH"],
                allowed_classes=CONFIG["ALLOWED_CLASSES"],
            )
            self.last_result = dets

    def submit(self, bgr):
        if not self.q.full():
            self.q.put_nowait(bgr)

    def get(self):
        return self.last_result

# ----------------------
# Flask + Camera set-up
# ----------------------
app = Flask(__name__)

picam = Picamera2()
picam.configure(picam.create_video_configuration(main={"size": tuple(CONFIG["CAP_SIZE"])}))
picam.start()

# Model
YOLO = YOLOv8ONNX(CONFIG["MODEL_PATHS"])
det_thread = DetectorThread(YOLO, CONFIG["CAP_SIZE"])
det_thread.start()

# Debounce state
hits = 0
misses = 0
present = False
last_present = False
t0 = time.time()

def annotate_and_decide(bgr, dets):
    global hits, misses, present
    H, W = bgr.shape[:2]
    min_area = CONFIG["MIN_REL_AREA"] * (W * H)
    ar_lo, ar_hi = CONFIG["ASPECT_RANGE"]

    # Filter to "box-like" detections by area & aspect ratio
    box_count = 0
    for d in dets:
        x1,y1,x2,y2 = d["xyxy"]
        w = x2 - x1
        h = y2 - y1
        area = w * h
        if area < min_area:
            continue
        ar = (w / h) if h > 1e-6 else 999.0
        if ar < ar_lo or ar > ar_hi:
            continue
        box_count += 1
        # Draw
        cv2.rectangle(bgr, (int(x1), int(y1)), (int(x2), int(y2)), (0,255,0), 2)
        if CONFIG["DRAW_SCORE"]:
            txt = f"{d['score']:.2f}"
            cv2.putText(bgr, txt, (int(x1), int(y1)-6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 1, cv2.LINE_AA)

    # Warm-up window
    if (time.time() - t0) < CONFIG["WARMUP_SEC"]:
        return bgr, 0, False

    # Debounce
    if box_count > 0:
        hits += 1
        misses = 0
    else:
        misses += 1
        hits = 0

    if not present and hits >= CONFIG["DEBOUNCE_UP"]:
        present = True
    if present and misses >= CONFIG["DEBOUNCE_DOWN"]:
        present = False

    return bgr, box_count, present

def draw_hud(bgr, fps, box_count, present):
    if not CONFIG["HUD"]:
        return bgr
    H, W = bgr.shape[:2]
    hud = [
        f"{CONFIG['VERSION']}",
        f"Res: {W}x{H}  In:{CONFIG['INFER_SIZE']}  Skip:{CONFIG['FRAME_SKIP']}  Q:{CONFIG['JPEG_QUALITY']}",
        f"Thresh: conf {CONFIG['CONF_THRESH']}  iou {CONFIG['IOU_THRESH']}",
        f"Boxes: {box_count}   Present: {int(present)}",
        f"Time: {datetime.now().strftime('%H:%M:%S')}",
    ]
    y = 18
    for line in hud:
        cv2.putText(bgr, line, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,0), 3, cv2.LINE_AA)
        cv2.putText(bgr, line, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1, cv2.LINE_AA)
        y += 18
    return bgr

def mjpeg_generator(annotated=True):
    global last_present
    fps_win = []
    prev = time.time()
    while True:
        frame = picam.capture_array()  # BGR
        det_thread.submit(frame)

        dets = det_thread.get() if annotated else []
        out = frame.copy()

        if annotated:
            out, box_count, now_present = annotate_and_decide(out, dets)
            if now_present != last_present:
                ts = int(time.time())
                try:
                    with open(LOG_PATH, "a", newline="") as f:
                        csv.writer(f).writerow([ts, int(now_present)])
                except Exception:
                    pass
                last_present = now_present
        else:
            box_count = 0
            now_present = False

        # FPS calc (cheap moving avg)
        now = time.time()
        fps = 1.0 / max(now - prev, 1e-6)
        prev = now
        fps_win.append(fps)
        if len(fps_win) > 30:
            fps_win.pop(0)
        fps_smoothed = sum(fps_win) / max(len(fps_win), 1)

        # HUD
        out = draw_hud(out, fps_smoothed, box_count, now_present)

        # Encode JPEG
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), CONFIG["JPEG_QUALITY"]]
        ok, jpg = cv2.imencode(".jpg", out, encode_params)
        if not ok:
            continue
        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n")

@app.route("/video")
def video():
    return Response(mjpeg_generator(annotated=True),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/video_raw")
def video_raw():
    return Response(mjpeg_generator(annotated=False),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/snapshot")
def snapshot():
    frame = picam.capture_array()
    annotated = frame.copy()
    dets = det_thread.get()
    annotated, box_count, now_present = annotate_and_decide(annotated, dets)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = SAMPLES_DIR / f"raw_{ts}.jpg"
    ann_path = SAMPLES_DIR / f"ann_{ts}.jpg"
    cv2.imwrite(str(raw_path), frame)
    cv2.imwrite(str(ann_path), annotated)
    # Zip both into a buffer to return
    import zipfile
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(str(raw_path), arcname=raw_path.name)
        zf.write(str(ann_path), arcname=ann_path.name)
    zbuf.seek(0)
    return send_file(zbuf, mimetype="application/zip",
                     as_attachment=True, download_name=f"snapshot_{ts}.zip")

@app.route("/health")
def health():
    return "ok"

@app.route("/config")
def cfg():
    info = dict(CONFIG)
    info["model_loaded"] = YOLO.model_path
    return jsonify(info)

def main():
    # Prefer 0.0.0.0:8000 so you can view from your laptop/phone
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    app.run(host=host, port=port, threaded=True)

if __name__ == "__main__":
    main()
