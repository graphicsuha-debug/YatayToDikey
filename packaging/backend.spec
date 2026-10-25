# Build with scripts/build-backend.ps1. Frontend and FFmpeg are Electron resources.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent
analysis = Analysis(
    [str(root / "scripts" / "frozen_backend.py")],
    pathex=[str(root)],
    binaries=[],
    datas=collect_data_files("cv2", includes=["data/haarcascade_frontalface_default.xml"]),
    hiddenimports=[
        "backend.camera", "cv2", "numpy", "python_multipart", "multipart",
        "uvicorn.logging", "uvicorn.loops.asyncio", "uvicorn.protocols.http.h11_impl",
        "uvicorn.lifespan.on",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)
# We use OpenCV only for Haar detection. Its separately licensed video decoder
# DLL is unnecessary because all frame decoding uses the bundled FFmpeg tools.
analysis.binaries = [item for item in analysis.binaries if "opencv_videoio_ffmpeg" not in item[0].lower()]
analysis.datas = [item for item in analysis.datas if "opencv_videoio_ffmpeg" not in item[0].lower()]
python_archive = PYZ(analysis.pure)
executable = EXE(
    python_archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="dikey-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
collection = COLLECT(executable, analysis.binaries, analysis.datas, strip=False, upx=False, name="dikey-backend")
