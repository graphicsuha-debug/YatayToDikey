"""Integration checks: run with python -m unittest backend.test_app -v."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app import Crop, ExportRequest, create_app, pixel_crop


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and ffprobe are required")
class VideoIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_dir = tempfile.TemporaryDirectory(prefix="dikey-source-")
        cls.source = Path(cls.source_dir.name) / "broadcast.mp4"
        command = [shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=640x360:r=24:d=3", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3", "-vf", "drawbox=x=16:y=216:w=176:h=128:color=red:t=fill", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(cls.source)]
        subprocess.run(command, check=True, capture_output=True, timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.source_dir.cleanup()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="dikey-test-")
        self.application = create_app(Path(self.directory.name))
        self.service = self.application.state.service
        self.client = TestClient(self.application)
        self.client.__enter__()
        source = self.service.uploads / "source.mp4"
        shutil.copy2(self.source, source)
        self.video = self.service.register(source, "Yayın kaydı.mp4", "source", demo=True)

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.directory.cleanup()

    def settings(self, **overrides):
        payload = {"videoId": "source", "camera": {"x": 0.025, "y": 0.6, "width": 0.275, "height": 0.3555}, "split": 0.32, "fit": "cover", "focus": 0.75, "start": 0.4, "end": 1.6, "resolution": 720, "fps": 30, "muted": False}
        payload.update(overrides)
        return payload

    def wait_done(self, job_id, timeout=45):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.client.get(f"/api/exports/{job_id}").json()
            if job["status"] in ("completed", "failed", "cancelled"):
                self.assertEqual(job["status"], "completed", self.service.jobs[job_id].get("_details", job))
                return job
            time.sleep(0.05)
        self.fail("Export exceeded timeout")

    def probe(self, path):
        result = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def pixel(self, path, x, y):
        result = subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-i", str(path), "-frames:v", "1", "-vf", f"format=rgb24,crop=1:1:{x}:{y}", "-f", "rawvideo", "pipe:1"], capture_output=True, check=True)
        return tuple(result.stdout[:3])

    def test_real_export_preserves_audio_duration_and_layout(self):
        response = self.client.post("/api/exports", json=self.settings())
        self.assertEqual(response.status_code, 200, response.text)
        job = self.wait_done(response.json()["id"])
        self.assertEqual(job["progress"], 100)
        output = Path(self.service.jobs[job["id"]]["_path"])
        metadata = self.probe(output)
        video = next(stream for stream in metadata["streams"] if stream["codec_type"] == "video")
        self.assertEqual((video["width"], video["height"]), (720, 1280))
        self.assertEqual(video["codec_name"], "h264")
        self.assertEqual(video["r_frame_rate"], "30/1")
        self.assertTrue(any(stream["codec_type"] == "audio" for stream in metadata["streams"]))
        self.assertAlmostEqual(float(metadata["format"]["duration"]), 1.2, delta=0.1)
        red = self.pixel(output, 360, 160)
        blue = self.pixel(output, 360, 900)
        self.assertGreater(red[0], 200, red)
        self.assertLess(red[2], 50, red)
        self.assertGreater(blue[2], 200, blue)
        self.assertLess(blue[0], 50, blue)
        download = self.client.get(job["url"])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(len(download.content), output.stat().st_size)
        self.assertIn("attachment", download.headers["content-disposition"])
        self.assertFalse(any(key.startswith("_") for key in job))

    def test_contain_1080_muted_and_60fps(self):
        response = self.client.post("/api/exports", json=self.settings(fit="contain", resolution=1080, fps=60, muted=True, end=1.0))
        job = self.wait_done(response.json()["id"])
        output = Path(self.service.jobs[job["id"]]["_path"])
        metadata = self.probe(output)
        video = next(stream for stream in metadata["streams"] if stream["codec_type"] == "video")
        self.assertEqual((video["width"], video["height"]), (1080, 1920))
        self.assertEqual(video["r_frame_rate"], "60/1")
        self.assertFalse(any(stream["codec_type"] == "audio" for stream in metadata["streams"]))
        # Contain preserves the full landscape frame with the product's dark fill.
        self.assertTrue(all(channel < 30 for channel in self.pixel(output, 540, 700)))

    def test_stream_ranges_and_poster(self):
        result = self.client.get(self.video["url"], headers={"Range": "bytes=0-99"})
        self.assertEqual(result.status_code, 206)
        self.assertEqual(result.content, self.source.read_bytes()[:100])
        self.assertEqual(result.headers["content-length"], "100")
        suffix = self.client.get(self.video["url"], headers={"Range": "bytes=-10"})
        self.assertEqual(suffix.content, self.source.read_bytes()[-10:])
        self.assertEqual(self.client.get(self.video["url"], headers={"Range": "bytes=999999999-"}).status_code, 416)
        self.assertEqual(self.client.get(self.video["url"], headers={"Range": "bytes=1-2,4-5"}).status_code, 416)
        self.assertEqual(self.client.get(self.video["poster"]).headers["content-type"], "image/jpeg")

    def test_upload_detection_and_invalid_files(self):
        with self.source.open("rb") as source:
            result = self.client.post("/api/videos", files={"file": ("broadcast.mp4", source, "video/mp4")})
        self.assertEqual(result.status_code, 200, result.text)
        video = result.json()
        self.assertEqual((video["width"], video["height"]), (640, 360))
        self.assertEqual(video["detection"]["mode"], "suggested")
        self.assertNotIn("_path", video)
        self.assertEqual(self.client.post("/api/videos", files={"file": ("bad.mp4", b"invalid", "video/mp4")}).status_code, 422)
        self.assertEqual(self.client.post("/api/videos", files={"file": ("script.txt", b"hello", "text/plain")}).status_code, 422)
        self.assertEqual(self.client.post("/api/videos", files={"file": ("empty.mp4", b"", "video/mp4")}).status_code, 422)

    def test_input_validation_and_local_origin(self):
        invalid = [self.settings(end=99), self.settings(start=2, end=1), self.settings(resolution=480), self.settings(camera={"x": 0.9, "y": 0, "width": 0.2, "height": 0.2}), self.settings(split=0.9), self.settings(focus=-1)]
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post("/api/exports", json=payload).status_code, 422)
        response = self.client.post("/api/exports", json=self.settings(), headers={"Origin": "https://example.com"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get("/api/health", headers={"Host": "evil.example"}).status_code, 403)
        self.assertEqual(self.client.get("/api/does-not-exist").status_code, 404)
        self.assertEqual(self.client.get("/api/exports/no-such-job").status_code, 404)

    def test_queued_cancel_does_not_create_output(self):
        gate = threading.Event()
        self.service.executor.submit(gate.wait, 10)
        try:
            job = self.client.post("/api/exports", json=self.settings()).json()
            self.assertEqual(job["status"], "queued")
            cancelled = self.client.post(f"/api/exports/{job['id']}/cancel").json()
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertEqual(self.client.get(f"/api/exports/{job['id']}/download").status_code, 409)
        finally:
            gate.set()
        self.service.executor.submit(lambda: None).result(timeout=10)
        self.assertFalse(Path(self.service.jobs[job["id"]]["_path"]).exists())

    def test_processing_cancel_terminates_ffmpeg_and_removes_partial_file(self):
        job = self.client.post("/api/exports", json=self.settings(start=0, end=3, resolution=1080, fps=60)).json()
        deadline = time.monotonic() + 10
        while not self.service.jobs[job["id"]]["_process"] and time.monotonic() < deadline:
            time.sleep(0.01)
        process = self.service.jobs[job["id"]]["_process"]
        self.assertIsNotNone(process)
        self.client.post(f"/api/exports/{job['id']}/cancel")
        self.service.executor.submit(lambda: None).result(timeout=10)
        self.assertIsNotNone(process.poll())
        self.assertEqual(self.service.get_job(job["id"])["status"], "cancelled")
        self.assertFalse(Path(self.service.jobs[job["id"]]["_path"]).exists())

    def test_encoder_failure_surfaces_error_without_partial_download(self):
        Path(self.service.videos["source"]["_path"]).write_bytes(b"corrupted source")
        job = self.client.post("/api/exports", json=self.settings()).json()
        self.service.executor.submit(lambda: None).result(timeout=15)
        failed = self.client.get(f"/api/exports/{job['id']}").json()
        self.assertEqual(failed["status"], "failed")
        self.assertTrue(failed["error"])
        self.assertNotIn("_details", failed)
        self.assertFalse(Path(self.service.jobs[job["id"]]["_path"]).exists())

    def test_even_crop_stays_inside_odd_dimensions(self):
        crop = Crop(x=0.9, y=0.8, width=0.1, height=0.2)
        x, y, width, height = pixel_crop(crop, 641, 361)
        self.assertTrue(all(value % 2 == 0 for value in (x, y, width, height)))
        self.assertLessEqual(x + width, 641)
        self.assertLessEqual(y + height, 361)
        with self.assertRaises(ValidationError):
            Crop(x=0.5, y=0.5, width=0.6, height=0.6)

    def test_completed_export_survives_restart_and_downloads_identically(self):
        job = self.client.post("/api/exports", json=self.settings(end=1.0)).json()
        job = self.wait_done(job["id"])
        original = self.client.get(job["url"]).content
        # Late cancellation cannot change a completed output or its metadata.
        self.assertEqual(self.client.post(f"/api/exports/{job['id']}/cancel").json()["status"], "completed")
        self.service.shutdown()
        metadata_path = self.service.exports / f"{job['id']}.json"
        saved = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["artifact"], f"{job['id']}.mp4")
        self.assertNotIn("_path", saved)
        restarted = create_app(Path(self.directory.name))
        with TestClient(restarted) as client:
            exports = client.get("/api/exports").json()
            self.assertEqual(len(exports), 1)
            self.assertEqual(exports[0]["status"], "completed")
            self.assertEqual(exports[0]["progress"], 100)
            self.assertEqual(exports[0]["filename"], job["filename"])
            download = client.get(exports[0]["url"])
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download.content, original)

    def test_restart_recovers_interrupted_jobs_and_rejects_unsafe_artifacts(self):
        exports = self.service.exports
        outside = Path(self.directory.name) / "outside.mp4"
        outside.write_bytes(b"must not be touched")
        for digit, status in (("1", "queued"), ("2", "processing"), ("3", "completed"), ("4", "cancelled")):
            job_id = digit * 32
            saved = {"id": job_id, "status": status, "progress": 30, "filename": "video_dikey.mp4", "videoName": "video.mp4", "createdAt": "2026-10-25T06:00:00+00:00", "artifact": f"{job_id}.mp4"}
            (exports / f"{job_id}.json").write_text(json.dumps(saved), encoding="utf-8")
            if status != "completed":
                (exports / saved["artifact"]).write_bytes(b"partial output")
        malicious_id = "a" * 32
        malicious = {**saved, "id": malicious_id, "status": "completed", "artifact": "../outside.mp4", "_path": str(outside)}
        (exports / f"{malicious_id}.json").write_text(json.dumps(malicious), encoding="utf-8")
        (exports / "invalid.json").write_text("{broken json", encoding="utf-8")
        restarted = create_app(Path(self.directory.name))
        with TestClient(restarted) as client:
            jobs = {item["id"]: item for item in client.get("/api/exports").json()}
            self.assertEqual(len(jobs), 4)
            for digit in ("1", "2"):
                self.assertEqual(jobs[digit * 32]["status"], "failed")
                self.assertIn("yarım kaldı", jobs[digit * 32]["error"])
                self.assertNotIn("url", jobs[digit * 32])
                self.assertFalse((exports / f"{digit * 32}.mp4").exists())
            self.assertEqual(jobs["3" * 32]["status"], "failed")
            self.assertIn("bulunamadı", jobs["3" * 32]["error"])
            self.assertEqual(jobs["4" * 32]["status"], "cancelled")
            self.assertFalse((exports / f"{'4' * 32}.mp4").exists())
            self.assertEqual(client.get(f"/api/exports/{malicious_id}/download").status_code, 404)
        self.assertEqual(outside.read_bytes(), b"must not be touched")
        persisted = json.loads((exports / f"{'2' * 32}.json").read_text(encoding="utf-8"))
        self.assertEqual(persisted["status"], "failed")

    def test_unwritable_job_metadata_rejects_export_before_encoding(self):
        with patch.object(self.service, "persist_job", return_value=False):
            response = self.client.post("/api/exports", json=self.settings())
        self.assertEqual(response.status_code, 507)
        self.assertEqual(self.service.jobs, {})


if __name__ == "__main__":
    unittest.main()
