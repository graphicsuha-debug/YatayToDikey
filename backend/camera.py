"""Short-lived face detection worker, isolated from the Windows web server."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def detect(ffmpeg: str, path: str, width: int, height: int, duration: float) -> dict | None:
    import cv2
    import numpy as np

    cv2.setNumThreads(1)
    # OpenCV's Windows file loader does not support every Unicode folder name.
    xml = Path(cv2.data.haarcascades, "haarcascade_frontalface_default.xml").read_text(encoding="utf-8")
    storage = cv2.FileStorage(xml, cv2.FILE_STORAGE_READ | cv2.FILE_STORAGE_MEMORY)
    cascade = cv2.CascadeClassifier()
    cascade.read(storage.getFirstTopLevelNode())
    storage.release()
    faces = []
    sample_width = min(960, width)
    sample_height = max(2, round(height * sample_width / width))
    for sample_index, ratio in enumerate((0.08, 0.3, 0.55, 0.8)):
        seek = min(max(duration * ratio, 0), max(0, duration - 0.1))
        try:
            frame = subprocess.run([ffmpeg, "-v", "error", "-protocol_whitelist", "file,pipe", "-ss", str(seek), "-i", path, "-frames:v", "1", "-vf", f"scale={sample_width}:{sample_height}", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"], stdin=subprocess.DEVNULL, capture_output=True, timeout=12, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            continue
        if frame.returncode or len(frame.stdout) != sample_width * sample_height:
            continue
        gray = np.frombuffer(frame.stdout, dtype=np.uint8).reshape(sample_height, sample_width)
        found = cascade.detectMultiScale(gray, scaleFactor=1.12, minNeighbors=5, minSize=(22, 22))
        for x, y, face_width, face_height in found:
            cx, cy = (x + face_width / 2) / sample_width, (y + face_height / 2) / sample_height
            if (cx < 0.32 or cx > 0.68) and (cy < 0.4 or cy > 0.6):
                faces.append((cx, cy, face_width / sample_width, face_height / sample_height, sample_index))
    if not faces:
        return None
    # Persistent corner faces are more likely to belong to a webcam than content.
    clusters = [[other for other in faces if abs(other[0] - face[0]) < 0.08 and abs(other[1] - face[1]) < 0.1] for face in faces]
    cluster = max(clusters, key=lambda group: len({face[4] for face in group}))
    if len({face[4] for face in cluster}) < 2:
        return None
    cx, cy, fw, fh = [float(np.median([face[index] for face in cluster])) for index in range(4)]
    crop_width = min(0.4, max(0.2, fw * 3.5))
    crop_height = min(0.48, max(0.23, fh * 2.5))
    return {"x": round(max(0, min(1 - crop_width, cx - crop_width / 2)), 5), "y": round(max(0, min(1 - crop_height, cy - crop_height * 0.4)), 5), "width": round(crop_width, 5), "height": round(crop_height, 5)}


if __name__ == "__main__":
    try:
        result = detect(sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), float(sys.argv[5]))
    except Exception:
        result = None
    print(json.dumps(result))
