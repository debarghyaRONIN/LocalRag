import os
import sys
import urllib.request
import urllib.error
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

# Resolve frontend dist directory
CANDIDATE_DIRS = [
    Path("/app/frontend/dist"),
    Path(__file__).resolve().parent.parent.parent / "frontend" / "dist",
    Path("frontend/dist"),
    Path("./dist"),
]

DIST_DIR = next((p for p in CANDIDATE_DIRS if p.exists() and (p / "index.html").exists()), Path("/app/frontend/dist"))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
BACKEND_BASE = os.environ.get("BACKEND_INTERNAL_URL", "http://127.0.0.1:8000")


class SPAProxyHandler(SimpleHTTPRequestHandler):
    """
    Production-grade single-page application (SPA) handler:
    1. Proxies /api/*, /docs, /openapi.json to the local FastAPI backend.
    2. Serves static CSS/JS/HTML assets directly from DIST_DIR with caching headers.
    3. Falls back to index.html for all client-side routes (SPA pushState support).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST_DIR), **kwargs)

    def _proxy_to_backend(self, method: str):
        target_url = f"{BACKEND_BASE.rstrip('/')}{self.path}"
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else None

        # Copy request headers, excluding host
        req_headers = {k: v for k, v in self.headers.items() if k.lower() != "host"}

        req = urllib.request.Request(target_url, data=body, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                self.send_response(resp.status)
                for header, val in resp.getheaders():
                    # Strip hop-by-hop headers
                    if header.lower() not in ("transfer-encoding", "content-encoding", "connection"):
                        self.send_header(header, val)
                self.end_headers()
                self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            for header, val in e.headers.items():
                if header.lower() not in ("transfer-encoding", "content-encoding", "connection"):
                    self.send_header(header, val)
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_error(502, f"Bad Gateway to Backend at {target_url}: {e}")

    def do_GET(self):
        # Proxy API, docs, and metrics to backend
        if (
            self.path.startswith("/api/")
            or self.path.startswith("/docs")
            or self.path.startswith("/redoc")
            or self.path.startswith("/openapi.json")
            or self.path.startswith("/metrics")
        ):
            return self._proxy_to_backend("GET")

        # Static file check
        clean_path = self.path.split("?")[0].lstrip("/")
        file_on_disk = DIST_DIR / clean_path
        if not file_on_disk.exists() or file_on_disk.is_dir():
            # SPA client-side route fallback to index.html
            self.path = "/index.html"

        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            return self._proxy_to_backend("POST")
        self.send_error(405, "Method Not Allowed")

    def do_PUT(self):
        if self.path.startswith("/api/"):
            return self._proxy_to_backend("PUT")
        self.send_error(405, "Method Not Allowed")

    def do_DELETE(self):
        if self.path.startswith("/api/"):
            return self._proxy_to_backend("DELETE")
        self.send_error(405, "Method Not Allowed")

    def log_message(self, format, *args):
        # Suppress routine asset GET logs to keep container output clean
        if "GET /assets/" in format % args:
            return
        super().log_message(format, *args)


def run():
    print(f"[Frontend Server] Serving Nocturne SPA from '{DIST_DIR}' on 0.0.0.0:{PORT}")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), SPAProxyHandler)
    server.serve_forever()


if __name__ == "__main__":
    run()

