# Third-party notices — Dikey Studio

Dikey Studio is made by **Suha Yar**. Bundled third-party components retain their own copyright notices and licenses; the author's credit does not replace those notices.

| Component | License / notices | Upstream |
| --- | --- | --- |
| Electron | MIT; Chromium includes additional licensed components | https://github.com/electron/electron |
| Chromium | BSD-style and third-party notices in LICENSES.chromium.html | https://www.chromium.org/ |
| React, React DOM, Scheduler | MIT | https://github.com/facebook/react |
| Lucide icons | ISC | https://github.com/lucide-icons/lucide |
| Python | PSF License and bundled notices | https://www.python.org/ |
| FastAPI, Starlette, Pydantic, Uvicorn and dependencies | Each installed distribution's original license | https://github.com/fastapi/fastapi |
| OpenCV | Apache-2.0 and bundled third-party notices | https://github.com/opencv/opencv |
| NumPy and OpenBLAS runtime | BSD-style and bundled notices | https://numpy.org/ |
| FFmpeg with x264 | GPL; exact terms accompany binary and source archive | https://ffmpeg.org/ |
| x264 | GPL-2.0-or-later | https://www.videolan.org/developers/x264.html |
| DM Sans | SIL Open Font License 1.1 | https://github.com/google/fonts/tree/main/ofl/dmsans |
| Manrope | SIL Open Font License 1.1 | https://github.com/google/fonts/tree/main/ofl/manrope |

The build collects exact installed versions and original license files into `resources/LICENSES`, including `dependency-inventory.json`. Electron's Chromium notices are preserved. Fonts are served locally with their OFL files.

## FFmpeg and x264 source

The published installer uses a minimal FFmpeg build with x264 and internal codecs and filters. It does not use the developer machine's general-purpose FFmpeg build. The application invokes FFmpeg as a separate executable.

`scripts/build-ffmpeg.sh` records exact source archives, build recipe, configuration and checksums. The corresponding source package is attached beside the installer on the same GitHub release, without an extra charge. It includes FFmpeg and x264 source, their licenses and the script used to build the supplied executables. Preserve the source package and notices when redistributing the installer.

The sources are also available from the upstream projects above. Build outputs record exact versions and hashes rather than relying on a changing default branch.

## Original demo

The sample video, presenter illustration, racing scene and application icon were created for this project. The demo includes no third-party game recording, photograph or commercial music. `scripts/create_demo.py` generates the sample assets.
