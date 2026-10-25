"""Resolve bundled resources and writable storage without system dependencies."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)).resolve()


def assets_root() -> Path:
    configured = os.environ.get("DIKEY_ASSETS_DIR")
    return Path(configured).resolve() if configured else bundle_root()


def data_root() -> Path:
    configured = os.environ.get("DIKEY_DATA_DIR")
    if configured:
        return Path(configured).resolve()
    if frozen():
        configured_local = os.environ.get("LOCALAPPDATA")
        local_app_data = Path(configured_local) if configured_local else Path.home() / "AppData" / "Local"
        return local_app_data / "DikeyStudio" / "data"
    return bundle_root() / "data"


def media_tools() -> tuple[str | None, str | None]:
    executable_root = Path(sys.executable).resolve().parent
    directories = []
    configured = os.environ.get("DIKEY_FFMPEG_DIR")
    if configured:
        directories.append(Path(configured))
    directories += [bundle_root() / "ffmpeg", executable_root / "ffmpeg", executable_root.parent / "ffmpeg", executable_root.parent.parent / "ffmpeg"]
    suffix = ".exe" if os.name == "nt" else ""
    for directory in directories:
        ffmpeg = directory / f"ffmpeg{suffix}"
        ffprobe = directory / f"ffprobe{suffix}"
        if ffmpeg.is_file() and ffprobe.is_file():
            return str(ffmpeg.resolve()), str(ffprobe.resolve())
    return shutil.which("ffmpeg"), shutil.which("ffprobe")


def camera_worker_command(ffmpeg: str, source: Path, width: int, height: int, duration: float) -> list[str]:
    worker = [sys.executable, "--detect-camera"] if frozen() else [sys.executable, str(Path(__file__).with_name("camera.py"))]
    return [*worker, ffmpeg, str(source), str(width), str(height), str(duration)]
