"""PyInstaller entry point: webcam worker or the desktop's private HTTP service."""

from __future__ import annotations

import multiprocessing
import os
import sys
import threading


def main():
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] == "--detect-camera":
        # Handle this before importing app, which creates data folders and a server.
        import json
        from backend.camera import detect

        try:
            result = detect(sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5]), float(sys.argv[6]))
        except Exception:
            result = None
        print(json.dumps(result), flush=True)
        return

    import uvicorn
    from backend.app import app

    config = uvicorn.Config(app, host="127.0.0.1", port=int(os.environ.get("DIKEY_PORT", "4318")), log_level="info", loop="asyncio", http="h11", ws="none", lifespan="on")
    server = uvicorn.Server(config)

    def desktop_input():
        # Only the Electron parent's private pipe can trigger this shutdown.
        # EOF also closes the service if the desktop process exits unexpectedly.
        try:
            for line in sys.stdin:
                if line.strip() == "__DIKEY_SHUTDOWN__":
                    break
        finally:
            server.should_exit = True

    if os.environ.get("DIKEY_DESKTOP") == "1" and sys.stdin is not None:
        threading.Thread(target=desktop_input, name="desktop-shutdown", daemon=True).start()
    server.run()


if __name__ == "__main__":
    main()
