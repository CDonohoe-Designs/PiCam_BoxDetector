#!/usr/bin/env python3
from picamera2 import Picamera2
from flask import Flask, Response
import cv2, time

app = Flask(__name__)
picam = Picamera2()
picam.configure(picam.create_video_configuration(main={"size": (640, 480)}))
picam.start()

def gen():
    while True:
        frame = picam.capture_array()
        ok, jpg = cv2.imencode(".jpg", frame)
        if not ok:
            continue
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" +
               jpg.tobytes() + b"\r\n")
        time.sleep(0.03)

@app.get("/")
def index():
    return '<html><body><h3>Pi Cam Preview</h3><img src="/stream"/></body></html>'

@app.get("/stream")
def stream():
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, threaded=True)
