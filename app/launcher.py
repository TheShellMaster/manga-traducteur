"""Manga Translator Studio - desktop launcher.

One process, no tray icon, nothing left running in the background:
- with pywebview installed: opens a native window; closing it stops everything;
- otherwise: opens the default browser; the server stops by itself ~40 s after
  the last tab is closed (heartbeat), or immediately via the "Quitter" button.
"""

import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

if getattr(sys, "frozen", False):
    sys.path.insert(0, getattr(sys, "_MEIPASS", str(Path(sys.executable).parent)))
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _free_port(preferred: int = 8000) -> int:
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    return preferred


def _already_running(port: int = 8000) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/settings", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def _wait_ready(url: str, timeout: float = 20.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url + "/api/settings", timeout=1):
                return True
        except Exception:
            time.sleep(0.2)
    return False


def main() -> None:
    if _already_running():
        webbrowser.open("http://127.0.0.1:8000")
        return

    try:
        import webview  # type: ignore
    except Exception:
        webview = None

    if webview is None or "--browser" in sys.argv:
        os.environ["MTS_AUTO_EXIT"] = "1"

    import uvicorn
    from server import app

    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    if os.environ.get("MTS_AUTO_EXIT") == "1":
        threading.Thread(target=lambda: _wait_ready(url) and webbrowser.open(url), daemon=True).start()
        server.run()
        return

    threading.Thread(target=server.run, daemon=True).start()
    _wait_ready(url)
    webview.create_window("Manga Translator Studio", url, width=1280, height=820, min_size=(380, 600))
    webview.start()
    # Window closed: stop the server and leave nothing behind
    server.should_exit = True
    time.sleep(0.3)
    os._exit(0)


if __name__ == "__main__":
    main()
