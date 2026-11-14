#!/usr/bin/env python3
"""
Desktop Launcher for Ragapp - Sovereign Local RAG Application.

This entrypoint provides a single unified desktop experience:
1. Resolves repository and distribution paths (supporting both source and frozen PyInstaller builds).
2. Verifies and discovers available local network ports.
3. Spawns the production FastAPI backend (which hosts both API endpoints and the compiled React SPA)
   inside a managed background daemon thread.
4. Verifies health connectivity at `/api/v1/health`.
5. Opens a native desktop window via PyWebView, or falls back seamlessly to the system's default browser.
6. Handles graceful shutdown on window closure or process termination.
"""

import os
import sys
import time
import socket
import logging
import argparse
import threading
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Tuple
from logging.handlers import RotatingFileHandler

# Configure robust dual logging (stdout + persistent file for diagnostic support)
log_handlers = [logging.StreamHandler(sys.stdout)]
try:
    log_dir = None
    if "SEALED_DATA_DIR" in os.environ and Path(os.environ["SEALED_DATA_DIR"]).exists():
        log_dir = Path(os.environ["SEALED_DATA_DIR"]) / "logs"
    elif "LOCALAPPDATA" in os.environ:
        log_dir = Path(os.environ["LOCALAPPDATA"]) / "Sealed Sovereign Enclave" / "logs"
    else:
        log_dir = Path.home() / ".sealed_sovereign" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    file_h = RotatingFileHandler(str(log_dir / "backend.log"), maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8")
    log_handlers.append(file_h)
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=log_handlers,
)
logger = logging.getLogger("ragapp.desktop")


def resolve_base_dir() -> Path:
    """
    Determines the application base directory across multiple deployment modes:
    - PyInstaller bundled one-file or one-dir executable
    - Portable desktop folder distribution
    - Direct python execution from repository checkout
    """
    if "BASE_DIR" in os.environ and Path(os.environ["BASE_DIR"]).exists():
        base = Path(os.environ["BASE_DIR"]).resolve()
        if (base / "backend" / "app").exists() or (base / "app").exists():
            return base

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        for cand in [exe_dir, exe_dir.parent, exe_dir.parent.parent]:
            if (cand / "backend" / "app").exists():
                return cand.resolve()
        if hasattr(sys, "_MEIPASS"):
            meipass = Path(sys._MEIPASS).resolve()
            if (meipass / "backend" / "app").exists():
                return meipass
        return exe_dir
    
    # Standalone script execution from backend/ or project root
    current = Path(__file__).resolve()
    # If file is in backend/desktop_launcher.py -> parent is backend -> parent.parent is repo root
    if current.parent.name == "backend":
        return current.parent.parent
    return current.parent


def is_parent_alive(pid: int) -> bool:
    """Checks whether the parent process is still running on Windows/POSIX."""
    if pid <= 0:
        return True
    if sys.platform == "win32":
        try:
            import ctypes
            SYNCHRONIZE = 0x00100000
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
            if not handle:
                err = ctypes.windll.kernel32.GetLastError()
                # 5 = ERROR_ACCESS_DENIED (process exists and is running under higher/different integrity level)
                # If we cannot query parent due to permissions or virtualization, assume it is ALIVE.
                if err == 5:
                    return True
                return True
            res = ctypes.windll.kernel32.WaitForSingleObject(handle, 0)
            ctypes.windll.kernel32.CloseHandle(handle)
            # 258 is WAIT_TIMEOUT, indicating the process is still running
            return res == 258
        except Exception:
            return True
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def ensure_ollama_running() -> bool:
    """If Ollama is installed on the host, ensure the local daemon is running."""
    import socket, subprocess, shutil
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.4)
    try:
        s.connect(("127.0.0.1", 11434))
        s.close()
        return True
    except Exception:
        pass

    ollama_candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path("C:/Program Files/Ollama/ollama.exe"),
    ]
    which_ollama = shutil.which("ollama.exe") or shutil.which("ollama")
    if which_ollama:
        ollama_candidates.insert(0, Path(which_ollama))

    for cand in ollama_candidates:
        if cand.exists():
            try:
                logger.info("Auto-starting local Ollama engine via %s...", cand)
                creationflags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
                subprocess.Popen([str(cand), "serve"], creationflags=creationflags)
                return True
            except Exception as e:
                logger.warning("Could not auto-start Ollama: %s", e)
    return False


# Bootstrap environment BEFORE importing backend modules
BASE_DIR = resolve_base_dir()
os.environ.setdefault("BASE_DIR", str(BASE_DIR))
os.environ.setdefault("AIRGAP_MODE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

# Ensure BASE_DIR and backend are on sys.path
for sp in [str(BASE_DIR), str(BASE_DIR / "backend"), str(Path.cwd()), str(Path.cwd() / "backend")]:
    if sp not in sys.path and Path(sp).exists():
        sys.path.insert(0, sp)


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Checks whether a TCP port is currently occupied or unavailable for binding."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return False
        except OSError:
            return True


def find_available_port(preferred_port: int = 8000, max_attempts: int = 50, host: str = "127.0.0.1") -> int:
    """
    Returns preferred_port if free, or scans forward to find the next open port.
    """
    if not is_port_in_use(preferred_port, host=host):
        return preferred_port
    
    logger.warning("Port %d is already in use. Searching for open port...", preferred_port)
    for p in range(preferred_port + 1, preferred_port + 1 + max_attempts):
        if not is_port_in_use(p, host=host):
            logger.info("Found available port: %d", p)
            return p
            
    # Dynamic OS ephemeral fallback
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def wait_for_server(health_url: str, timeout: float = 30.0, interval: float = 0.25) -> Tuple[bool, dict]:
    """
    Polls the FastAPI health endpoint until HTTP 200 is returned or timeout expires.
    """
    import json
    import http.client
    import urllib.parse
    deadline = time.time() + timeout
    last_error = None

    parsed = urllib.parse.urlparse(health_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8000
    path = (parsed.path or "/api/v1/health") + (f"?{parsed.query}" if parsed.query else "")

    while time.time() < deadline:
        conn = None
        try:
            conn = http.client.HTTPConnection(host, port, timeout=5.0)
            conn.request("GET", path, headers={"User-Agent": "RagappDesktopLauncher/1.0"})
            resp = conn.getresponse()
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                return True, data
        except Exception as e:
            last_error = e
            time.sleep(interval)
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    logger.error("Timed out waiting for server at %s. Last error: %s", health_url, last_error)
    return False, {"error": str(last_error)}


class DesktopServer:
    """Manages the Uvicorn FastAPI server in a background daemon thread."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8000):
        self.host = host
        self.port = port
        self.server = None
        self.thread = None
        self._is_running = False

    def start(self):
        """Starts uvicorn in a daemon thread."""
        import uvicorn
        from backend.app.main import app
        from backend.app.core.config import settings

        # Ensure frontend dist fallback is mounted if dist is located in alt paths
        self._ensure_frontend_mount(app, settings)

        config = uvicorn.Config(
            app=app,
            host=self.host,
            port=self.port,
            log_level="info",
            access_log=False,
            loop="asyncio",
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, name="FastAPIServerThread", daemon=True)
        self.thread.start()
        self._is_running = True
        logger.info("FastAPI background server thread started on http://%s:%d", self.host, self.port)

    def _ensure_frontend_mount(self, app, settings):
        """Checks potential distribution locations for frontend/dist and mounts static assets."""
        from fastapi.staticfiles import StaticFiles
        from fastapi.responses import FileResponse

        candidate_dirs = [
            settings.BASE_DIR / "frontend" / "dist",
            settings.BASE_DIR / "dist",
            Path(__file__).resolve().parent.parent / "frontend" / "dist",
            Path(__file__).resolve().parent.parent / "dist",
        ]
        
        found_dist = None
        for cd in candidate_dirs:
            if cd.exists() and (cd / "index.html").exists():
                found_dist = cd
                break

        if found_dist:
            logger.info("Frontend dist identified at: %s", found_dist)
            # Ensure assets route mounted if not already mounted
            has_assets = any(getattr(route, "path", None) == "/assets" for route in app.routes)
            if not has_assets and (found_dist / "assets").exists():
                app.mount("/assets", StaticFiles(directory=found_dist / "assets"), name="static_assets")

    def stop(self, timeout: float = 3.0):
        """Signals server shutdown and waits for thread completion."""
        if self.server:
            self.server.should_exit = True
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=timeout)
        self._is_running = False
        logger.info("FastAPI background server stopped.")

    @property
    def is_running(self) -> bool:
        return self._is_running and self.thread is not None and self.thread.is_alive()


def launch_desktop_gui(url: str, title: str = "Ragapp - Sovereign Local RAG System", force_browser: bool = False) -> bool:
    """
    Launches the desktop GUI.
    Prefers native pywebview window. Falls back gracefully to system browser if pywebview is unavailable.
    """
    if force_browser:
        logger.info("Opening Ragapp in default web browser: %s", url)
        import webbrowser
        webbrowser.open(url)
        return False

    try:
        import webview
        logger.info("Launching native desktop window via pywebview...")
        webview.create_window(
            title=title,
            url=url,
            width=1280,
            height=860,
            min_size=(900, 600),
            confirm_close=True,
            text_select=True,
        )
        # webview.start blocks until the window is closed
        webview.start()
        logger.info("Native window closed by user.")
        return True
    except Exception as e:
        logger.warning("Native PyWebView unavailable (%s). Falling back to system browser...", e)
        import webbrowser
        webbrowser.open(url)
        return False


def run_desktop_app(
    host: str = "127.0.0.1",
    preferred_port: int = 8000,
    exact_port: bool = False,
    headless: bool = False,
    force_browser: bool = False,
    check_only: bool = False,
    timeout: float = 30.0,
) -> int:
    """
    Main orchestration loop for the desktop runner.
    """
    port = preferred_port
    if exact_port:
        # Give previous process up to 10s to release port if transitioning
        deadline = time.time() + 10.0
        while is_port_in_use(port, host=host) and time.time() < deadline:
            logger.info("Waiting for port %d to be released by previous instance...", port)
            time.sleep(0.5)
        if is_port_in_use(port, host=host):
            logger.error("Port %d is already in use and --exact-port was specified.", port)
            return 1
    else:
        port = find_available_port(preferred_port, host=host)

    server = DesktopServer(host=host, port=port)
    server.start()
    ensure_ollama_running()

    health_url = f"http://{host}:{port}/api/v1/health"
    app_url = f"http://{host}:{port}/"
    logger.info("Verifying server readiness at %s...", health_url)

    healthy, health_data = wait_for_server(health_url, timeout=timeout)
    if not healthy:
        logger.error("Server failed to become healthy within %s seconds.", timeout)
        server.stop()
        return 1

    logger.info("Server is healthy: %s", health_data.get("status", "unknown"))

    # If --check-only is specified (e.g., automated CI / test validation), exit immediately with success
    if check_only:
        logger.info("Self-check completed successfully. Shutting down server...")
        server.stop()
        return 0

    if headless:
        logger.info("Running in headless mode. Server listening at %s. Press Ctrl+C to terminate.", app_url)
        parent_pid = os.getppid()
        try:
            while server.is_running:
                time.sleep(0.5)
                if parent_pid > 1 and not is_parent_alive(parent_pid):
                    logger.info("Parent process (PID %d) terminated. Shutting down server...", parent_pid)
                    break
        except KeyboardInterrupt:
            logger.info("Interrupted by user. Exiting...")
        finally:
            server.stop()
        return 0

    # Launch GUI window or open browser
    used_webview = launch_desktop_gui(app_url, force_browser=force_browser)
    
    # If system browser was used (which returns immediately), keep process alive until Ctrl+C
    if not used_webview:
        logger.info("Browser opened. Press Ctrl+C in this console to terminate application.")
        try:
            while server.is_running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            server.stop()
    else:
        # Webview window was closed, terminate server
        server.stop()

    return 0


def parse_args():
    parser = argparse.ArgumentParser(description="Ragapp Desktop Application Launcher")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--exact-port", action="store_true", help="Fail if exact port is unavailable instead of finding next free port")
    parser.add_argument("--headless", "--no-gui", action="store_true", dest="headless", help="Run server only without opening GUI window or browser")
    parser.add_argument("--browser", action="store_true", dest="force_browser", help="Force opening in standard browser instead of native webview")
    parser.add_argument("--check-only", action="store_true", help="Boot server, verify /api/v1/health, and exit immediately with status code 0")
    parser.add_argument("--timeout", type=float, default=30.0, help="Timeout in seconds to wait for backend health check")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    sys.exit(
        run_desktop_app(
            host=args.host,
            preferred_port=args.port,
            exact_port=args.exact_port,
            headless=args.headless,
            force_browser=args.force_browser,
            check_only=args.check_only,
            timeout=args.timeout,
        )
    )
