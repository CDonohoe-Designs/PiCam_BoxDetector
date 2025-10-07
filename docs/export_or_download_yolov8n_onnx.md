
# Get a YOLOv8 ONNX model onto the Pi

## Fastest path (export on your laptop, then copy to Pi)
1. On your laptop (not the Pi), install Ultralytics:
   ```bash
   pip install ultralytics==8.2.0 onnx onnxsim
   ```
2. Export a tiny model to ONNX (no training):
   ```bash
   yolo export model=yolov8n.pt format=onnx opset=12 dynamic=False simplify=True
   # This creates `yolov8n.onnx` in the same folder.
   ```
3. (Optional) Fine-tune on your "box" images (recommended for accuracy). After training, export your best weights:
   ```bash
   yolo train data=your_data.yaml model=yolov8n.pt imgsz=640 epochs=50
   yolo export model=runs/detect/train/weights/best.pt format=onnx opset=12 dynamic=False simplify=True
   # rename the exported file to yolov8n_boxes.onnx
   ```
4. Copy the ONNX file(s) to your Pi:
   ```bash
   scp yolov8n.onnx pi@<pi-ip>:/home/pi/PiCam_BoxDetector/models/
   # and/or your custom:
   scp yolov8n_boxes.onnx pi@<pi-ip>:/home/pi/PiCam_BoxDetector/models/
   ```

## Alternative (download prebuilt ONNX on the Pi)
Ultralytics hosts ready-to-use ONNX weights. Example:
```bash
cd ~/PiCam_BoxDetector/models
curl -L -o yolov8n.onnx https://github.com/ultralytics/assets/releases/download/v8.1.0/yolov8n.onnx
```
> If the URL ever changes, export on your laptop using the steps above.

---

## Performance tips for Raspberry Pi 3
- Use 640x480 capture (`CAP_SIZE`) and `INFER_SIZE=640`
- Increase `FRAME_SKIP` (e.g., 2–4) to reduce CPU load
- Prefer a custom model trained on **only boxes**; it’s smaller & more confident
- Keep overlays and JPEG quality modest (e.g., `JPEG_QUALITY=75–85`)
- If you need higher FPS, run YOLO on a laptop/mini-PC and have the Pi call a REST API
