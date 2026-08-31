from __future__ import annotations

import subprocess
import sys
import threading
import time
import urllib.request
import ctypes
from pathlib import Path

import server


ROOT = Path(__file__).resolve().parent


def show_error(message: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, message, "투자", 0x10)


def find_edge() -> Path | None:
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    return next((path for path in candidates if path.is_file()), None)


def existing_server_is_healthy() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8787/api/dashboard", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def open_edge_app(edge: Path, profile: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [str(edge), "--app=http://127.0.0.1:8787", f"--user-data-dir={profile}",
         "--no-first-run", "--disable-background-mode"],
        cwd=ROOT,
    )


def main() -> int:
    edge = find_edge()
    if edge is None:
        show_error("Microsoft Edge를 찾을 수 없습니다. Edge 설치 후 다시 실행하세요.")
        return 1
    server.init_db()
    app = None
    try:
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 8787), server.Handler)
    except OSError:
        if existing_server_is_healthy():
            profile = server.DATA / "desktop-profile"
            profile.mkdir(parents=True, exist_ok=True)
            open_edge_app(edge, profile)
            return 0
        show_error("이전 실행이 8787 포트를 점유하고 있습니다. 잠시 후 다시 실행해 주세요.")
        return 1
    httpd.daemon_threads = True
    server.LAST_HEARTBEAT = 0.0
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    profile = server.DATA / "desktop-profile"
    profile.mkdir(parents=True, exist_ok=True)
    try:
        app = open_edge_app(edge, profile)
        startup_deadline = time.monotonic() + 30
        while server.LAST_HEARTBEAT == 0 and time.monotonic() < startup_deadline:
            time.sleep(0.2)
        if server.LAST_HEARTBEAT == 0:
            show_error("앱 화면이 서버에 연결되지 못했습니다. 다시 실행해 주세요.")
        else:
            while time.monotonic() - server.LAST_HEARTBEAT < 6:
                time.sleep(0.5)
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)
        if app is not None and app.poll() is None:
            app.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
