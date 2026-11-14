"""
Unit and integration tests for Ragapp desktop packaging and launcher.

Tests:
1. Port detection and availability scanning.
2. Base directory and runtime environment resolution.
3. Server lifecycle: spawning daemon server thread, polling /api/v1/health, and clean shutdown.
4. Desktop launcher --check-only mode.
5. Distribution artifacts: RagApp.bat, launch_desktop.vbs, launch_browser.bat, manifest integrity.
"""

import os
import json
import socket
import pytest
from pathlib import Path

from backend.desktop_launcher import (
    resolve_base_dir,
    is_port_in_use,
    find_available_port,
    wait_for_server,
    DesktopServer,
    run_desktop_app,
)
from scripts.package_executable import compute_sha256


def test_base_dir_resolution():
    """Verify that resolve_base_dir accurately locates the repository root."""
    base_dir = resolve_base_dir()
    assert base_dir.exists(), f"Base directory does not exist: {base_dir}"
    assert (base_dir / "backend").exists(), "backend/ directory missing from resolved BASE_DIR"
    assert (base_dir / "backend" / "app" / "main.py").exists(), "main.py missing from resolved BASE_DIR"


def test_port_detection_and_scan():
    """Verify is_port_in_use and find_available_port logic."""
    # Bind an ephemeral port to make it occupied
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        busy_port = sock.getsockname()[1]

        # Port must be reported in use
        assert is_port_in_use(busy_port, host="127.0.0.1") is True

        # Searching starting from busy_port must return an available port != busy_port
        free_port = find_available_port(preferred_port=busy_port, max_attempts=10, host="127.0.0.1")
        assert free_port != busy_port
        assert is_port_in_use(free_port, host="127.0.0.1") is False


def test_desktop_server_lifecycle_and_health():
    """Verify DesktopServer spawns daemon thread, passes health check, and stops cleanly."""
    free_port = find_available_port(preferred_port=8090, max_attempts=20)
    server = DesktopServer(host="127.0.0.1", port=free_port)
    server.start()

    try:
        assert server.is_running is True
        health_url = f"http://127.0.0.1:{free_port}/api/v1/health"
        is_healthy, health_data = wait_for_server(health_url, timeout=20.0)
        assert is_healthy is True, f"Server failed health check: {health_data}"
        assert health_data.get("status") == "healthy"
        assert "app_version" in health_data
    finally:
        server.stop(timeout=5.0)
        assert server.is_running is False


def test_run_desktop_app_check_only():
    """Verify run_desktop_app with check_only=True returns 0."""
    free_port = find_available_port(preferred_port=8085, max_attempts=20)
    ret = run_desktop_app(
        host="127.0.0.1",
        preferred_port=free_port,
        exact_port=False,
        check_only=True,
        timeout=15.0,
    )
    assert ret == 0


def test_dist_desktop_artifacts_exist():
    """Verify that dist_desktop distribution contains all mandatory deployment files."""
    repo_root = resolve_base_dir()
    dist_dir = repo_root / "dist_desktop"

    # Mandatory distribution components
    bat_file = dist_dir / "RagApp.bat"
    vbs_file = dist_dir / "launch_desktop.vbs"
    browser_bat = dist_dir / "launch_browser.bat"
    headless_bat = dist_dir / "launch_headless.bat"
    env_file = dist_dir / ".env"
    manifest_file = dist_dir / "package_manifest.json"
    readme_file = dist_dir / "README.md"
    spa_index = dist_dir / "frontend" / "dist" / "index.html"

    assert bat_file.exists(), "RagApp.bat is missing from dist_desktop"
    assert vbs_file.exists(), "launch_desktop.vbs is missing from dist_desktop"
    assert browser_bat.exists(), "launch_browser.bat is missing from dist_desktop"
    assert headless_bat.exists(), "launch_headless.bat is missing from dist_desktop"
    assert env_file.exists(), ".env is missing from dist_desktop"
    assert manifest_file.exists(), "package_manifest.json is missing from dist_desktop"
    assert readme_file.exists(), "README.md is missing from dist_desktop"
    assert spa_index.exists(), "frontend/dist/index.html is missing from dist_desktop"

    # Verify manifest JSON contents
    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest.get("package_name") == "Ragapp Desktop Standalone"
    assert "components" in manifest
    assert manifest["components"].get("fastapi_backend") is True
    assert manifest["components"].get("react_single_page_app") is True
    assert manifest["components"].get("airgap_offline_mode") is True
    assert "entrypoints" in manifest
    assert manifest["entrypoints"].get("one_click_interactive") == "RagApp.bat"
    assert manifest["entrypoints"].get("windowless_silent") == "launch_desktop.vbs"

    # Check that SHA-256 in manifest matches actual file hash
    bat_checksum = manifest["checksums"]["RagApp.bat"]["sha256"]
    assert compute_sha256(bat_file) == bat_checksum


def test_package_executable_all_checksums_and_env():
    """Verify all checksum entries in package_manifest.json match actual files, and .env has AIRGAP_MODE."""
    repo_root = resolve_base_dir()
    dist_dir = repo_root / "dist_desktop"
    manifest_file = dist_dir / "package_manifest.json"

    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    for rel_path, meta in manifest.get("checksums", {}).items():
        full_path = dist_dir / rel_path
        assert full_path.exists(), f"Manifest lists {rel_path} but file does not exist"
        assert compute_sha256(full_path) == meta["sha256"]

    # Verify .env contents
    env_content = (dist_dir / ".env").read_text(encoding="utf-8")
    assert "AIRGAP_MODE=True" in env_content
    assert "DATABASE_URL=" in env_content
    assert "QDRANT_PATH=" in env_content


def test_desktop_launcher_arg_parsing():
    """Verify desktop_launcher argument parser defaults and flags."""
    from backend.desktop_launcher import parse_args
    import sys

    original_argv = sys.argv
    try:
        sys.argv = ["desktop_launcher.py", "--check-only", "--port", "8555", "--headless"]
        args = parse_args()
        assert args.check_only is True
        assert args.port == 8555
        assert args.headless is True
        assert args.host == "127.0.0.1"
    finally:
        sys.argv = original_argv

