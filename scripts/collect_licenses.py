"""Collect notices from the exact installed dependencies used by a Windows build.

Run with the backend's virtual-environment interpreter, after npm ci and the
backend build. The output is bundled as an Electron extraResource. This records
licenses and provenance; it does not claim to supply all GPL corresponding source.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def copy(source: Path, target: Path) -> bool:
    if not source.is_file():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def collect(output: Path, download_source: bool = False) -> None:
    output.mkdir(parents=True, exist_ok=True)
    inventory: dict = {"python": sys.version, "python_packages": [], "javascript_packages": []}
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not copy(python_license, output / "python" / "Python-LICENSE.txt"):
        raise RuntimeError(f"Python runtime license was not found: {python_license}")

    for dist in sorted(importlib.metadata.distributions(), key=lambda item: item.metadata.get("Name", "")):
        name = dist.metadata.get("Name", "unknown")
        entry = {"name": name, "version": dist.version, "license": dist.metadata.get("License-Expression") or dist.metadata.get("License"), "notices": []}
        for file in dist.files or []:
            basename = Path(str(file)).name.lower()
            if not (basename.startswith("license") or basename.startswith("licence") or basename.startswith("copying") or basename == "notice"):
                continue
            if basename.endswith((".py", ".pyc", ".so", ".dll")):
                continue
            source = Path(dist.locate_file(file))
            # Keep subdirectories to retain notices with the same basename.
            relative = Path(*[part for part in Path(str(file)).parts if part not in ("..", ".")])
            target = output / "python" / name / relative
            if copy(source, target):
                entry["notices"].append(target.relative_to(output).as_posix())
        inventory["python_packages"].append(entry)

    for name in ["react", "react-dom", "scheduler", "lucide-react", "electron"]:
        package_root = ROOT / "node_modules" / name
        package_json = package_root / "package.json"
        if not package_json.exists():
            continue
        package = json.loads(package_json.read_text(encoding="utf-8"))
        inventory["javascript_packages"].append({"name": name, "version": package["version"], "license": package.get("license")})
        for filename in ["LICENSE", "LICENSE.txt", "LICENSE.md", "NOTICE"]:
            copy(package_root / filename, output / "javascript" / name / filename)
        if name == "electron":
            for filename in ["LICENSE", "LICENSES.chromium.html"]:
                copy(package_root / "dist" / filename, output / "electron" / filename)

    for source in (ROOT / "public" / "fonts").glob("*-OFL.txt"):
        copy(source, output / "fonts" / source.name)

    packed_ffmpeg = ROOT / "build" / "backend" / "ffmpeg" / "ffmpeg.exe"
    command = str(packed_ffmpeg) if packed_ffmpeg.is_file() else shutil.which("ffmpeg")
    if not command:
        raise RuntimeError("FFmpeg is required to record the redistributed build's provenance")
    ffmpeg = Path(command)
    ffmpeg_dir = output / "ffmpeg"
    ffmpeg_dir.mkdir(parents=True, exist_ok=True)
    version = subprocess.run([command, "-version"], capture_output=True, text=True, check=True).stdout
    configuration = subprocess.run([command, "-buildconf"], capture_output=True, text=True, check=True)
    (ffmpeg_dir / "ffmpeg-build.txt").write_text(version + "\n" + configuration.stdout + configuration.stderr, encoding="utf-8")
    parents = [ffmpeg.parent, ffmpeg.parent.parent]
    readme_text = ""
    license_found = False
    for folder in parents:
        for filename in ["LICENSE", "LICENSE.txt", "COPYING.GPLv3", "FFmpeg-GPLv2.txt", "x264-COPYING.txt"]:
            if copy(folder / filename, ffmpeg_dir / filename):
                license_found = True
        for filename in ["README.txt", "README.md"]:
            if copy(folder / filename, ffmpeg_dir / filename):
                readme_text += (folder / filename).read_text(encoding="utf-8", errors="replace") + "\n"
    if not license_found:
        raise RuntimeError("The FFmpeg distributor's license was not found beside its binary or package root")
    custom_build = "Dikey Studio Windows x64 video engine" in readme_text
    for filename in ["config.log", "config.mak", "x264-config.log", "x264-config.mak", "SOURCE-SHA256SUMS.txt", "BINARY-SHA256SUMS.txt", "compiler-version.txt", "build-package-versions.txt"]:
        copy(ffmpeg.parent / filename, ffmpeg_dir / filename)
    if (ffmpeg.parent / "toolchain-notices").is_dir():
        shutil.copytree(ffmpeg.parent / "toolchain-notices", ffmpeg_dir / "toolchain-notices", dirs_exist_ok=True)
    source_match = re.search(r"https://github\.com/FFmpeg/FFmpeg/commit/([a-f0-9]+)", readme_text)
    source_commit = source_match.group(1) if source_match else None
    version_match = re.search(r"ffmpeg version (\d+\.\d+(?:\.\d+)?)", version)
    source_url = (f"https://github.com/FFmpeg/FFmpeg/archive/{source_commit}.tar.gz" if source_commit else
                  f"https://ffmpeg.org/releases/ffmpeg-{version_match.group(1)}.tar.xz" if version_match else None)
    inventory["ffmpeg"] = {"version": version.splitlines()[0], "sha256": digest(ffmpeg), "source_commit": source_commit, "upstream_source_url": source_url, "custom_media_build": custom_build}
    probe = ffmpeg.parent / "ffprobe.exe"
    if probe.exists():
        inventory["ffmpeg"]["ffprobe_sha256"] = digest(probe)
    reference = ["FFmpeg build provenance", "", version.splitlines()[0],
                 f"Upstream FFmpeg source: {source_url or 'See distributor README'}"]
    if custom_build:
        reference += ["", "Built for Dikey Studio from unmodified FFmpeg and x264 source archives.",
                      "Exact source archives, hashes and the reproducible build recipe are provided",
                      "in the separate FFmpeg-Corresponding-Source release artifact.",
                      "The project working copy stores these files in third_party/sources.",
                      "Only x264 is enabled as an external media library. Windows system libraries",
                      "and the MinGW/GCC runtime retain their notices and runtime exceptions.",
                      "See README.txt, config.mak, x264-config.mak and SOURCE-SHA256SUMS.txt."]
    else:
        reference += [f"Exact distributor source commit: {source_commit or 'Not supplied'}",
                      "Binary distributor: see original README.txt", "",
                      "The optional downloaded source archive contains upstream FFmpeg only.",
                      "It does NOT cover every external library in a precompiled static build.",
                      "Supply corresponding library sources and build materials before distribution."]
    if download_source and source_url:
        sources = ROOT / "third_party" / "sources"
        sources.mkdir(parents=True, exist_ok=True)
        filename = f"ffmpeg-{source_commit}.tar.gz" if source_commit else f"ffmpeg-{version_match.group(1)}.tar.xz"
        archive = sources / filename
        if not archive.is_file():
            request = urllib.request.Request(source_url, headers={"User-Agent": "Dikey-Studio-build"})
            with urllib.request.urlopen(request, timeout=120) as response, archive.open("wb") as stream:
                shutil.copyfileobj(response, stream)
        checksum = digest(archive)
        (sources / (filename + ".sha256")).write_text(f"{checksum}  {filename}\n", encoding="utf-8")
        reference += ["", f"Local upstream archive: third_party/sources/{filename}", f"Archive SHA-256: {checksum}"]
    (ffmpeg_dir / "SOURCE-REFERENCE.txt").write_text("\n".join(reference) + "\n", encoding="utf-8")
    (output / "dependency-inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Collected exact dependency notices in {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "LICENSES")
    parser.add_argument("--download-ffmpeg-source", action="store_true", help="Also save upstream FFmpeg's source archive as a separate release artifact")
    args = parser.parse_args()
    collect(args.output, args.download_ffmpeg_source)
