"""Local-only API and FFmpeg worker for landscape-to-portrait videos."""

from __future__ import annotations

import atexit
import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import math
import mimetypes
import os
from pathlib import Path
import re
import subprocess
import threading
from typing import Literal
from urllib.parse import urlparse
import uuid

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.runtime import assets_root, camera_worker_command, data_root, media_tools


ROOT = assets_root()
MAX_UPLOAD_BYTES = 20 * 1024 * 1024 * 1024
FORMATS = "mov,matroska,webm,avi,mpegts,mpeg,asf,flv"
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".ts", ".mts", ".m2ts", ".wmv", ".flv"}
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LOGGER = logging.getLogger("dikey")


class Crop(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    x: float = Field(ge=0, lt=1)
    y: float = Field(ge=0, lt=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def inside_source(self):
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError("Kamera alanı videonun sınırları içinde olmalı.")
        return self


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    videoId: str
    camera: Crop
    split: float = Field(default=0.32, ge=0.2, le=0.5)
    fit: Literal["cover", "contain"] = "cover"
    focus: float = Field(default=0.5, ge=0, le=1)
    start: float = Field(default=0, ge=0)
    end: float = Field(gt=0)
    resolution: Literal[720, 1080] = 1080
    fps: Literal[30, 60] = 30
    muted: bool = False

    @model_validator(mode="after")
    def valid_range(self):
        if self.end - self.start < 0.1:
            raise ValueError("En az 0,1 saniyelik bir aralık seçin.")
        return self


class SavedJob(BaseModel):
    """Only these validated fields may be restored from local metadata."""
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    status: Literal["queued", "processing", "completed", "failed", "cancelled"]
    progress: int = Field(ge=0, le=100)
    filename: str = Field(min_length=1, max_length=200, pattern=r'^[^<>:"/\\|?*\x00-\x1f]+$')
    videoName: str = Field(max_length=1000)
    createdAt: str
    artifact: str
    error: str | None = Field(default=None, max_length=2000)


def run_process(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    # Desktop stdin is a private shutdown pipe being read by another thread.
    # Children must not inherit that pipe (Windows may block during startup).
    return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, creationflags=CREATE_NO_WINDOW)


def pixel_crop(crop: Crop, width: int, height: int) -> tuple[int, int, int, int]:
    """Return a chroma-aligned crop that cannot extend beyond the input."""
    x = min(int(crop.x * width) // 2 * 2, (width - 2) // 2 * 2)
    y = min(int(crop.y * height) // 2 * 2, (height - 2) // 2 * 2)
    w = max(2, min(int(crop.width * width) // 2 * 2, (width - x) // 2 * 2))
    h = max(2, min(int(crop.height * height) // 2 * 2, (height - y) // 2 * 2))
    return x, y, w, h


class VideoService:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.uploads = data_dir / "uploads"
        self.exports = data_dir / "exports"
        self.posters = data_dir / "posters"
        for directory in (self.uploads, self.exports, self.posters):
            directory.mkdir(parents=True, exist_ok=True)
        self.ffmpeg, self.ffprobe = media_tools()
        self.videos: dict[str, dict] = {}
        self.jobs: dict[str, dict] = {}
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dikey-export")
        self.closed = False
        self.demo_lock = threading.Lock()
        self.restore_videos()
        self.restore_jobs()

    def restore_videos(self):
        for metadata_file in self.uploads.glob("*.json"):
            try:
                video = json.loads(metadata_file.read_text(encoding="utf-8"))
                path = Path(video["_path"]).resolve()
                if path.parent == self.uploads.resolve() and path.is_file():
                    self.videos[video["id"]] = video
            except (OSError, ValueError, KeyError):
                continue

    def persist_job(self, job: dict) -> bool:
        """Atomically replace metadata; never store absolute artifact paths."""
        metadata = {**self.public_job(job), "artifact": f"{job['id']}.mp4"}
        target = self.exports / f"{job['id']}.json"
        temporary = target.with_suffix(".json.tmp")
        try:
            temporary.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
            temporary.replace(target)
            return True
        except OSError:
            LOGGER.warning("Export metadata could not be saved for %s", job["id"], exc_info=True)
            return False

    def restore_jobs(self):
        restored = []
        export_root = self.exports.resolve()
        for metadata_file in self.exports.glob("*.json"):
            try:
                if metadata_file.resolve().parent != export_root:
                    continue
                saved = SavedJob.model_validate_json(metadata_file.read_text(encoding="utf-8"))
                if metadata_file.stem != saved.id or saved.artifact != f"{saved.id}.mp4":
                    continue
                artifact = self.exports / saved.artifact
                if artifact.resolve().parent != export_root:
                    continue
                datetime.fromisoformat(saved.createdAt)
                job = saved.model_dump(exclude={"artifact"}, exclude_none=True)
                job.update(_path=str(artifact), _cancel=threading.Event(), _process=None)
                if job["status"] in ("queued", "processing"):
                    job.update(status="failed", error="Uygulama kapandığı için bu dışa aktarma yarım kaldı. Videoyu yeniden dışa aktarın.")
                elif job["status"] == "completed":
                    if artifact.is_file() and artifact.stat().st_size:
                        job.update(progress=100, url=f"/api/exports/{saved.id}/download", size=artifact.stat().st_size)
                    else:
                        job.update(status="failed", error="Çıktı dosyası bulunamadı. Videoyu yeniden dışa aktarın.")
                if job["status"] != "completed":
                    job.pop("url", None)
                    artifact.unlink(missing_ok=True)
                restored.append(job)
            except (OSError, ValueError, KeyError, TypeError):
                LOGGER.warning("Invalid export metadata skipped: %s", metadata_file.name)
        for job in sorted(restored, key=lambda item: item["createdAt"]):
            self.jobs[job["id"]] = job
            self.persist_job(job)

    def require_ffmpeg(self):
        if not self.ffmpeg or not self.ffprobe:
            raise HTTPException(503, "FFmpeg bulunamadı. FFmpeg'i kurup uygulamayı yeniden başlatın.")

    def probe(self, path: Path) -> dict:
        self.require_ffmpeg()
        try:
            result = run_process([self.ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe", "-format_whitelist", FORMATS, "-show_format", "-show_streams", "-of", "json", str(path)], 30)
            if result.returncode:
                raise ValueError("Dosya okunamadı.")
            info = json.loads(result.stdout)
            stream = next(item for item in info["streams"] if item["codec_type"] == "video" and not item.get("disposition", {}).get("attached_pic"))
            width, height = int(stream["width"]), int(stream["height"])
            rotation = int(float(stream.get("tags", {}).get("rotate", 0)))
            for side_data in stream.get("side_data_list", []):
                if "rotation" in side_data:
                    rotation = int(side_data["rotation"])
            if abs(rotation) % 180 == 90:
                width, height = height, width
            if width < 2 or height < 2 or width * height > 8192 * 8192:
                raise ValueError("Video boyutu desteklenmiyor.")
            duration = float(info.get("format", {}).get("duration", stream.get("duration", 0)))
            if not math.isfinite(duration) or duration <= 0 or duration > 24 * 3600:
                raise ValueError("Video süresi okunamadı veya 24 saati aşıyor.")
            numerator, denominator = stream.get("avg_frame_rate", "30/1").split("/")
            fps = float(numerator) / float(denominator) if float(denominator) else 30
            return {"width": width, "height": height, "duration": duration, "fps": round(fps, 3), "size": path.stat().st_size, "_hasAudio": any(item["codec_type"] == "audio" for item in info["streams"])}
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, StopIteration, TypeError) as error:
            raise HTTPException(422, "Bu dosyada okunabilir bir video bulunamadı. MP4, MOV, MKV veya WebM deneyin.") from error

    def detect_camera(self, path: Path, width: int, height: int, duration: float) -> tuple[dict, dict]:
        fallback = {"x": 0.025, "y": 0.60, "width": 0.275, "height": 0.36}
        fallback_message = {"mode": "suggested", "message": "Kamera otomatik bulunamadı. Önerilen alanı önizlemeden kameranızın üzerine taşıyın."}
        try:
            # OpenCV can deadlock during Python 3.14 shutdown when it has run on
            # an asyncio worker thread. Keep detection in a short-lived process.
            result = run_process(camera_worker_command(self.ffmpeg, path, width, height, duration), 60)
            camera = json.loads(result.stdout) if result.returncode == 0 else None
            if camera:
                camera = Crop.model_validate(camera).model_dump()
                return camera, {"mode": "detected", "message": "Köşede tekrarlanan bir yüz bulundu. Kamera çerçevesi tahminidir; dışa aktarmadan önce kontrol edin."}
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
        return fallback, fallback_message

    def register(self, path: Path, name: str, video_id: str | None = None, demo: bool = False) -> dict:
        info = self.probe(path)
        video_id = video_id or uuid.uuid4().hex
        if demo:
            camera = {"x": 0.025, "y": 0.6, "width": 0.275, "height": 0.36}
            detection = {"mode": "suggested", "message": "Örnek videonun kamera alanı hazır. Kendi videonuzda otomatik yüz tespiti kullanılır."}
        else:
            camera, detection = self.detect_camera(path, info["width"], info["height"], info["duration"])
        video = {"id": video_id, "name": name, **info, "url": f"/api/videos/{video_id}/stream", "poster": f"/api/videos/{video_id}/poster", "camera": camera, "detection": detection, "_path": str(path.resolve())}
        poster = self.posters / f"{video_id}.jpg"
        try:
            result = run_process([self.ffmpeg, "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "file,pipe", "-y", "-ss", str(min(info["duration"] / 4, 3)), "-i", str(path), "-frames:v", "1", "-vf", "scale=1280:-2", "-q:v", "3", str(poster)], 30)
            if result.returncode:
                poster.unlink(missing_ok=True)
        except (OSError, subprocess.TimeoutExpired):
            poster.unlink(missing_ok=True)
        with self.lock:
            self.videos[video_id] = video
            if path.resolve().parent == self.uploads.resolve():
                (self.uploads / f"{video_id}.json").write_text(json.dumps(video, ensure_ascii=False), encoding="utf-8")
        return self.public_video(video)

    @staticmethod
    def public_video(video: dict) -> dict:
        return {key: value for key, value in video.items() if not key.startswith("_")}

    def get_video(self, video_id: str) -> dict:
        with self.lock:
            video = self.videos.get(video_id)
        if not video or not Path(video["_path"]).is_file():
            raise HTTPException(404, "Video bulunamadı. Dosyayı yeniden yükleyin.")
        return video

    @staticmethod
    def public_job(job: dict) -> dict:
        return {key: value for key, value in job.items() if not key.startswith("_")}

    def get_job(self, job_id: str) -> dict:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                raise HTTPException(404, "Dışa aktarma bulunamadı.")
            return self.public_job(job)

    def enqueue(self, settings: ExportRequest) -> dict:
        self.require_ffmpeg()
        video = self.get_video(settings.videoId)
        if settings.start >= video["duration"] or settings.end > video["duration"] + 0.05:
            raise HTTPException(422, "Seçilen zaman aralığı video süresini aşıyor.")
        if settings.camera.width * video["width"] < 2 or settings.camera.height * video["height"] < 2:
            raise HTTPException(422, "Kamera alanı en az 2 × 2 piksel olmalı.")
        with self.lock:
            if self.closed:
                raise HTTPException(503, "Uygulama kapanıyor.")
            if sum(job["status"] in ("queued", "processing") for job in self.jobs.values()) >= 10:
                raise HTTPException(429, "Sıra dolu. Bir dışa aktarma tamamlandıktan sonra yeniden deneyin.")
            job_id = uuid.uuid4().hex
            stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(video["name"]).stem).strip(" .")[:100] or "video"
            filename = f"{stem}_dikey_{settings.resolution}p.mp4"
            job = {"id": job_id, "status": "queued", "progress": 0, "filename": filename, "videoName": video["name"], "createdAt": datetime.now(timezone.utc).isoformat(), "_path": str(self.exports / f"{job_id}.mp4"), "_cancel": threading.Event(), "_process": None}
            if not self.persist_job(job):
                raise HTTPException(507, "Dışa aktarma kaydedilemiyor. Disk alanını ve klasör izinlerini kontrol edin.")
            self.jobs[job_id] = job
            self.executor.submit(self.render, job_id, video.copy(), settings)
            return self.public_job(job)

    def build_command(self, video: dict, settings: ExportRequest, destination: Path) -> list[str]:
        width = settings.resolution
        height = width * 16 // 9
        top_height = round(height * settings.split / 2) * 2
        bottom_height = height - top_height
        x, y, crop_width, crop_height = pixel_crop(settings.camera, video["width"], video["height"])
        camera = f"[camera]crop={crop_width}:{crop_height}:{x}:{y},scale={width}:{top_height}:force_original_aspect_ratio=increase,crop={width}:{top_height},setsar=1[top]"
        if settings.fit == "contain":
            content = f"[content]scale={width}:{bottom_height}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={width}:{bottom_height}:(ow-iw)/2:(oh-ih)/2:color=0x0b0d12,setsar=1[bottom]"
        else:
            content = f"[content]scale={width}:{bottom_height}:force_original_aspect_ratio=increase,crop={width}:{bottom_height}:(iw-ow)*{settings.focus:.6f}:(ih-oh)/2,setsar=1[bottom]"
        graph = f"[0:v:0]split=2[camera][content];{camera};{content};[top][bottom]vstack=inputs=2,setsar=1[outv]"
        command = [self.ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-protocol_whitelist", "file,pipe", "-ss", f"{settings.start:.6f}", "-i", video["_path"], "-t", f"{min(settings.end, video['duration']) - settings.start:.6f}", "-filter_complex_threads", "1", "-filter_complex", graph, "-map", "[outv]"]
        if settings.muted:
            command += ["-an"]
        else:
            command += ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "160k"]
        command += ["-r", str(settings.fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-threads", "4", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(destination)]
        return command

    def render(self, job_id: str, video: dict, settings: ExportRequest):
        with self.lock:
            job = self.jobs[job_id]
            if job["_cancel"].is_set():
                job["status"] = "cancelled"
                self.persist_job(job)
                return
            job["status"], job["progress"] = "processing", 1
            self.persist_job(job)
        destination = Path(job["_path"])
        errors: deque[str] = deque(maxlen=20)
        process = None
        try:
            command = self.build_command(video, settings, destination)
            with self.lock:
                if job["_cancel"].is_set():
                    job["status"] = "cancelled"
                    return
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=CREATE_NO_WINDOW)
                job["_process"] = process
            for line in process.stdout:
                if line.startswith("out_time_us="):
                    try:
                        elapsed = int(line.split("=", 1)[1]) / 1_000_000
                        with self.lock:
                            if job["status"] == "processing":
                                job["progress"] = min(99, max(1, round(elapsed / (settings.end - settings.start) * 100)))
                    except ValueError:
                        pass
                elif "=" not in line:
                    errors.append(line.strip())
            return_code = process.wait()
            with self.lock:
                if job["_cancel"].is_set():
                    job["status"] = "cancelled"
                elif return_code != 0 or not destination.is_file() or destination.stat().st_size == 0:
                    job["status"] = "failed"
                    job["error"] = "Video işlenemedi. Başka bir kamera alanı veya video dosyası deneyin."
                    job["_details"] = "\n".join(errors)
                else:
                    job.update(status="completed", progress=100, url=f"/api/exports/{job_id}/download", size=destination.stat().st_size)
        except Exception as error:
            with self.lock:
                job["status"] = "cancelled" if job["_cancel"].is_set() else "failed"
                if job["status"] == "failed":
                    job["error"] = "Dışa aktarma başlatılamadı. Disk alanını ve FFmpeg kurulumunu kontrol edin."
                job["_details"] = str(error)
        finally:
            if process and process.poll() is None:
                process.kill()
                process.wait()
            if process and process.stdout:
                process.stdout.close()
            with self.lock:
                job["_process"] = None
                if job["status"] != "completed":
                    try:
                        destination.unlink(missing_ok=True)
                    except OSError:
                        LOGGER.warning("Partial export could not be removed: %s", destination.name)
                self.persist_job(job)

    def cancel(self, job_id: str) -> dict:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                raise HTTPException(404, "Dışa aktarma bulunamadı.")
            if job["status"] in ("completed", "failed", "cancelled"):
                return self.public_job(job)
            job["_cancel"].set()
            process = job["_process"]
            job["status"] = "cancelled"
            if process and process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    pass
            self.persist_job(job)
            return self.public_job(job)

    def shutdown(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            for job_id in list(self.jobs):
                self.cancel(job_id)
        self.executor.shutdown(wait=True, cancel_futures=True)


def stream_file(path: Path, request: Request):
    size = path.stat().st_size
    range_header = request.headers.get("range")
    start, end = 0, size - 1
    status = 200
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"}
    if range_header:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
        if not match or not any(match.groups()):
            return JSONResponse({"detail": "Geçersiz video aralığı."}, status_code=416, headers={"Content-Range": f"bytes */{size}"})
        if not match[1]:
            suffix = int(match[2])
            start = max(0, size - suffix)
        else:
            start = int(match[1])
            end = min(size - 1, int(match[2])) if match[2] else size - 1
        if start >= size or end < start:
            return JSONResponse({"detail": "Video aralığı dosya dışında."}, status_code=416, headers={"Content-Range": f"bytes */{size}"})
        status = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    length = end - start + 1
    headers["Content-Length"] = str(length)

    def chunks():
        with path.open("rb") as video_file:
            video_file.seek(start)
            remaining = length
            while remaining:
                chunk = video_file.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
    return StreamingResponse(chunks(), status_code=status, media_type=mimetypes.guess_type(path.name)[0] or "video/mp4", headers=headers)


def create_app(data_dir: Path | None = None) -> FastAPI:
    service = VideoService(data_dir or data_root())

    @asynccontextmanager
    async def lifespan(application):
        yield
        await asyncio.to_thread(service.shutdown)

    application = FastAPI(title="Dikey local video API", docs_url=None, redoc_url=None, lifespan=lifespan)
    application.state.service = service
    atexit.register(service.shutdown)

    @application.middleware("http")
    async def local_only(request: Request, call_next):
        allowed_hosts = {"localhost", "127.0.0.1", "::1", "testserver"}
        if request.url.hostname not in allowed_hosts:
            return JSONResponse({"detail": "Bu uygulama yalnızca bu bilgisayardan kullanılabilir."}, status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin:
                parsed = urlparse(origin)
                if parsed.hostname not in allowed_hosts or parsed.scheme not in ("http", "https"):
                    return JSONResponse({"detail": "Bu kaynaktan işlem yapılamaz."}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Bu kaynaktan işlem yapılamaz."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @application.get("/api/health")
    def health():
        return {"ok": True, "ffmpeg": bool(service.ffmpeg and service.ffprobe)}

    @application.post("/api/videos")
    async def upload_video(file: UploadFile = File(...)):
        service.require_ffmpeg()
        name = (file.filename or "video.mp4").replace("\\", "/").split("/")[-1]
        extension = Path(name).suffix.lower()
        if extension not in VIDEO_EXTENSIONS:
            await file.close()
            raise HTTPException(422, "MP4, MOV, MKV, WebM, AVI veya TS video dosyası seçin.")
        video_id = uuid.uuid4().hex
        path = service.uploads / f"{video_id}{extension}"
        try:
            total = 0
            with path.open("wb") as destination:
                while chunk := await file.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_UPLOAD_BYTES:
                        raise HTTPException(413, "En fazla 20 GB büyüklüğünde bir video yükleyebilirsiniz.")
                    destination.write(chunk)
            if not total:
                raise HTTPException(422, "Seçilen dosya boş.")
            return await asyncio.to_thread(service.register, path, name, video_id)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        finally:
            await file.close()

    @application.get("/api/demo")
    def demo_video():
        with service.demo_lock:
            if "demo" in service.videos:
                return service.public_video(service.get_video("demo"))
            path = ROOT / "public" / "demo.mp4"
            if not path.is_file():
                raise HTTPException(404, "Örnek video henüz hazır değil. Kendi videonuzu yükleyebilirsiniz.")
            return service.register(path, "Örnek yayın.mp4", "demo", demo=True)

    @application.get("/api/videos/{video_id}/stream")
    def video_stream(video_id: str, request: Request):
        return stream_file(Path(service.get_video(video_id)["_path"]), request)

    @application.get("/api/videos/{video_id}/poster")
    def video_poster(video_id: str):
        service.get_video(video_id)
        path = service.posters / f"{video_id}.jpg"
        if not path.is_file():
            raise HTTPException(404, "Video görseli oluşturulamadı.")
        return FileResponse(path, media_type="image/jpeg")

    @application.post("/api/exports")
    def export_video(settings: ExportRequest):
        return service.enqueue(settings)

    @application.get("/api/exports")
    def exports_list():
        with service.lock:
            return [service.public_job(job) for job in reversed(list(service.jobs.values()))]

    @application.get("/api/exports/{job_id}")
    def export_status(job_id: str):
        return service.get_job(job_id)

    @application.post("/api/exports/{job_id}/cancel")
    def cancel_export(job_id: str):
        return service.cancel(job_id)

    @application.get("/api/exports/{job_id}/download")
    def download_export(job_id: str):
        job = service.get_job(job_id)
        if job["status"] != "completed":
            raise HTTPException(409, "Bu dışa aktarma henüz hazır değil.")
        with service.lock:
            path = Path(service.jobs[job_id]["_path"])
        if not path.is_file():
            raise HTTPException(404, "Çıktı dosyası bulunamadı.")
        return FileResponse(path, filename=job["filename"], media_type="video/mp4")

    assets = ROOT / "dist" / "assets"
    if assets.is_dir():
        application.mount("/assets", StaticFiles(directory=assets), name="assets")

    @application.get("/{requested_path:path}")
    def frontend(requested_path: str):
        if requested_path.startswith("api/") or requested_path == "api":
            raise HTTPException(404, "İşlem bulunamadı.")
        dist = (ROOT / "dist").resolve()
        requested = (dist / requested_path).resolve()
        if requested.is_relative_to(dist) and requested.is_file():
            return FileResponse(requested)
        index = dist / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse({"detail": "Arayüz henüz oluşturulmadı. Geliştirme sunucusunu açın veya arayüzü derleyin."}, status_code=503)

    return application


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("DIKEY_PORT", "4318")), log_level="info")
