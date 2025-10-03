# # Sample Detections

Small curated examples from the **PiCam Box Detector**.  
Each pair shows the original frame and the annotated result with detected rectangular boxes.

> Keep images lightweight (≤ ~500 KB) so the repo stays snappy. Larger videos should live off-repo (Drive/YouTube) and be linked here.

---

## Gallery

### 1) Shoebox on table
<table>
<tr>
<td><strong>Original</strong></td>
<td><strong>Detected</strong></td>
</tr>
<tr>
<td><img src="./shoebox_original.jpg" alt="shoebox original" width="420"></td>
<td><img src="./shoebox_detected.jpg" alt="shoebox detected" width="420"></td>
</tr>
</table>

**Notes:** Good edges under indoor lighting. Contour approx picked up the box cleanly.

---

### 2) Parcel with label
<table>
<tr>
<td><strong>Original</strong></td>
<td><strong>Detected</strong></td>
</tr>
<tr>
<td><img src="./parcel_original.jpg" alt="parcel original" width="420"></td>
<td><img src="./parcel_detected.jpg" alt="parcel detected" width="420"></td>
</tr>
</table>

**Notes:** High-contrast label helps. If noise appears, try reducing Canny thresholds or adding more blur (5×5 → 7×7).

---

### 3) Multiple boxes (stacked)
<table>
<tr>
<td><strong>Original</strong></td>
<td><strong>Detected</strong></td>
</tr>
<tr>
<td><img src="./stack_original.jpg" alt="stack original" width="420"></td>
<td><img src="./stack_detected.jpg" alt="stack detected" width="420"></td>
</tr>
</table>

**Notes:** Multiple detections. Tune `min_area` / `max_area` to include smaller boxes without picking up noise.

---

## File Naming Convention

Use `<scene>_{original|detected}.jpg`:

- `shoebox_original.jpg` / `shoebox_detected.jpg`
- `parcel_original.jpg` / `parcel_detected.jpg`
- `stack_original.jpg` / `stack_detected.jpg`

This keeps pairs together in listings and makes diffs obvious.

## How These Were Generated

- Captured via PiCam v2.1 on Raspberry Pi 3 Model B.
- Processed by `scripts/box_stream.py` (OpenCV Canny → contours → 4-vertex approx).
- Drawn as green rectangles with “BOX” labels overlay.

## Recreate Locally

1. Run the stream on the Pi:  
   `python3 scripts/box_stream.py`
2. Open `http://<pi-ip>:8000/video`, grab frames (browser screenshot or right-click → save image).
3. Place pairs here following the naming convention.

## Troubleshooting Quick Tips

- Too many false boxes? Increase `min_area` and raise `Canny` thresholds.
- Missed boxes? Lower thresholds or reduce blur; ensure lighting is even.
- Performance on Pi 3 struggling? Drop resolution to `960×540` or `640×480`, JPEG quality ~70.
