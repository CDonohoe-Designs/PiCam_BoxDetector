#!/usr/bin/env python3
import sys
from picamera2 import Picamera2
from datetime import datetime
from pathlib import Path

dur = int(sys.argv[1]) if len(sys.argv) > 1 else 5  # seconds
outdir = Path(__file__).resolve().parent.parent / "captures"
outdir.mkdir(parents=True, exist_ok=True)
mp4 = outdir / (datetime.now().strftime("%Y%m%d_%H%M%S") + ".mp4")

picam = Picamera2()
picam.configure(picam.create_video_configuration(main={"size": (1920, 1080)}))
picam.start_and_record_video(str(mp4), duration=dur)
picam.stop()
print(f"Saved {mp4}")
