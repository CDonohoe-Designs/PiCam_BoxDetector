#!/usr/bin/env python3
from picamera2 import Picamera2
from datetime import datetime
from pathlib import Path

outdir = Path(__file__).resolve().parent.parent / "captures"
outdir.mkdir(parents=True, exist_ok=True)
fname = outdir / (datetime.now().strftime("%Y%m%d_%H%M%S") + ".jpg")

picam = Picamera2()
picam.configure(picam.create_still_configuration(main={"size": (3280, 2464)}))
picam.start()
picam.capture_file(str(fname))
picam.stop()
print(f"Saved {fname}")
