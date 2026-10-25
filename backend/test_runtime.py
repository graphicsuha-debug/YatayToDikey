"""Packaged paths must not depend on PATH or write into Program Files."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from backend import runtime


class RuntimePathTests(unittest.TestCase):
    def test_frozen_storage_defaults_to_local_app_data(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(sys, "frozen", True, create=True), patch.dict(os.environ, {"LOCALAPPDATA": directory}, clear=True):
                self.assertEqual(runtime.data_root(), Path(directory) / "DikeyStudio" / "data")

    def test_desktop_overrides_asset_and_data_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"DIKEY_DATA_DIR": str(root / "data"), "DIKEY_ASSETS_DIR": str(root / "assets")}):
                self.assertEqual(runtime.data_root(), (root / "data").resolve())
                self.assertEqual(runtime.assets_root(), (root / "assets").resolve())

    def test_bundled_ffmpeg_is_found_without_system_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            suffix = ".exe" if os.name == "nt" else ""
            for name in ("ffmpeg", "ffprobe"):
                (root / f"{name}{suffix}").write_bytes(b"test executable")
            with patch.dict(os.environ, {"DIKEY_FFMPEG_DIR": directory, "PATH": ""}):
                ffmpeg, ffprobe = runtime.media_tools()
            self.assertEqual(ffmpeg, str((root / f"ffmpeg{suffix}").resolve()))
            self.assertEqual(ffprobe, str((root / f"ffprobe{suffix}").resolve()))

    def test_frozen_camera_worker_reuses_executable_not_python_script(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", "dikey-backend.exe"):
            command = runtime.camera_worker_command("ffmpeg.exe", Path("clip.mp4"), 1920, 1080, 10)
        self.assertEqual(command[:2], ["dikey-backend.exe", "--detect-camera"])
        self.assertEqual(command[2:], ["ffmpeg.exe", "clip.mp4", "1920", "1080", "10"])


if __name__ == "__main__":
    unittest.main()
