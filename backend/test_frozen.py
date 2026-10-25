"""Verify the built Windows service without Python or FFmpeg on the child PATH."""

import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest

import httpx


ROOT = Path(__file__).resolve().parent.parent
BACKEND = Path(os.environ.get("DIKEY_TEST_BACKEND", ROOT / "build/backend/dikey-backend/dikey-backend.exe"))
FFMPEG_DIR = Path(os.environ.get("DIKEY_TEST_FFMPEG", ROOT / "build/backend/ffmpeg"))


@unittest.skipUnless(BACKEND.is_file() and (FFMPEG_DIR / "ffmpeg.exe").is_file(), "Build the Windows backend first")
class FrozenBackendTests(unittest.TestCase):
    def test_offline_worker_export_restart_and_graceful_shutdown(self):
        with tempfile.TemporaryDirectory(prefix="Dikey-paket-") as directory:
            workspace = Path(directory)
            data_dir = workspace / "Kullanıcı verileri"
            source = workspace / "Yayın.mp4"
            ffmpeg = FFMPEG_DIR / "ffmpeg.exe"
            subprocess.run([str(ffmpeg), "-v", "error", "-y", "-f", "lavfi", "-i", "color=blue:s=640x360:r=24:d=12", "-f", "lavfi", "-i", "sine=frequency=440:duration=12", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source)], capture_output=True, check=True, timeout=20)
            environment = os.environ.copy()
            environment.update(PATH=str(Path(os.environ["SystemRoot"]) / "System32"), DIKEY_DATA_DIR=str(data_dir), DIKEY_ASSETS_DIR=str(ROOT), DIKEY_FFMPEG_DIR=str(FFMPEG_DIR), DIKEY_DESKTOP="1")
            environment.pop("PYTHONHOME", None)
            environment.pop("PYTHONPATH", None)
            worker = subprocess.run([str(BACKEND), "--detect-camera", str(ffmpeg), str(source), "640", "360", "12"], capture_output=True, text=True, env=environment, cwd=workspace, timeout=30)
            self.assertEqual(worker.returncode, 0, worker.stderr)
            self.assertIsNone(json.loads(worker.stdout))
            self.assertFalse(data_dir.exists(), "Camera worker must not initialize the server")
            # The bundled illustrated demo has a face recognized by the shipped
            # Haar model; this catches missing OpenCV DLLs/XML hidden by fallback.
            reference = subprocess.run([str(BACKEND), "--detect-camera", str(ffmpeg), str(ROOT / "public/demo.mp4"), "1280", "720", "12"], capture_output=True, text=True, env=environment, cwd=workspace, timeout=30)
            self.assertEqual(reference.returncode, 0, reference.stderr)
            detected = json.loads(reference.stdout)
            self.assertIsInstance(detected, dict, reference.stderr)
            self.assertLess(detected["x"], 0.15)
            self.assertGreater(detected["y"], 0.5)

            def launch():
                with socket.socket() as listener:
                    listener.bind(("127.0.0.1", 0))
                    port = listener.getsockname()[1]
                environment["DIKEY_PORT"] = str(port)
                log = (workspace / f"server-{port}.log").open("w", encoding="utf-8")
                process = subprocess.Popen([str(BACKEND)], stdin=subprocess.PIPE, stdout=log, stderr=log, text=True, env=environment, cwd=workspace, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30)
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    try:
                        if client.get("/api/health").json() == {"ok": True, "ffmpeg": True}:
                            return process, client, log
                    except httpx.HTTPError:
                        pass
                    if process.poll() is not None:
                        break
                    time.sleep(0.1)
                process.kill()
                process.wait()
                client.close()
                log.close()
                self.fail((workspace / f"server-{port}.log").read_text(encoding="utf-8"))

            def close(process, client, log, message="__DIKEY_SHUTDOWN__\n"):
                try:
                    process.communicate(message, timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    self.fail("Frozen service did not stop gracefully")
                finally:
                    client.close()
                    log.close()
                self.assertEqual(process.returncode, 0)

            process, client, log = launch()
            try:
                self.assertEqual(client.get("/").status_code, 200)
                with source.open("rb") as upload:
                    response = client.post("/api/videos", files={"file": ("Yayın.mp4", upload, "video/mp4")})
                self.assertEqual(response.status_code, 200, response.text)
                video = response.json()
                response = client.post("/api/exports", json={"videoId": video["id"], "camera": video["camera"], "start": 0, "end": 1, "resolution": 720})
                self.assertEqual(response.status_code, 200, response.text)
                job = response.json()
                deadline = time.monotonic() + 30
                while job["status"] in ("queued", "processing") and time.monotonic() < deadline:
                    time.sleep(0.1)
                    job = client.get(f"/api/exports/{job['id']}").json()
                self.assertEqual(job["status"], "completed", job)
                original = client.get(job["url"]).content
                self.assertGreater(len(original), 1000)
            finally:
                close(process, client, log)
            process, client, log = launch()
            try:
                restored = client.get("/api/exports").json()
                self.assertEqual(len(restored), 1)
                self.assertEqual(restored[0]["status"], "completed")
                self.assertEqual(client.get(restored[0]["url"]).content, original)
                running = client.post("/api/exports", json={"videoId": video["id"], "camera": video["camera"], "start": 0, "end": 12, "resolution": 1080, "fps": 60}).json()
                deadline = time.monotonic() + 5
                while running["status"] == "queued" and time.monotonic() < deadline:
                    time.sleep(0.02)
                    running = client.get(f"/api/exports/{running['id']}").json()
                self.assertEqual(running["status"], "processing")
            finally:
                # EOF also stops a running FFmpeg job if the Electron parent dies.
                close(process, client, log, message="")
            cancelled = json.loads((data_dir / "exports" / f"{running['id']}.json").read_text(encoding="utf-8"))
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertFalse((data_dir / "exports" / f"{running['id']}.mp4").exists())


if __name__ == "__main__":
    unittest.main()
