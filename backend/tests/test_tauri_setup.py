"""
Test Suite for Tauri Desktop Application and Offline Air-Gap Setup Installer.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DIST_SETUP = REPO_ROOT / "dist_setup"
TAURI_RELEASE_DIR = REPO_ROOT / "frontend" / "src-tauri" / "target" / "release"


def test_tauri_executable_built():
    """Confirms Tauri native executable exists and is non-empty."""
    exe_path = TAURI_RELEASE_DIR / "sealed.exe"
    if not exe_path.exists():
        exe_path = TAURI_RELEASE_DIR / "app.exe"
    assert exe_path.exists(), f"Tauri binary missing in {TAURI_RELEASE_DIR}"
    assert exe_path.stat().st_size > 1_000_000, "Tauri binary is suspiciously small"


def test_offline_installer_executable_exists():
    """Confirms the standalone installer setup executable was generated."""
    setup_exe = DIST_SETUP / "Sealed_Setup_x64.exe"
    assert setup_exe.exists(), f"Installer missing at {setup_exe}"
    assert setup_exe.stat().st_size > 1_000_000, "Installer executable is too small"


def test_offline_install_scripts_exist():
    """Verifies batch and PowerShell installers exist with correct flags."""
    bat_path = DIST_SETUP / "Install_Sealed_Offline.bat"
    ps_path = DIST_SETUP / "setup_offline.ps1"
    assert bat_path.exists(), "Install_Sealed_Offline.bat missing"
    assert ps_path.exists(), "setup_offline.ps1 missing"

    bat_content = bat_path.read_text(encoding="utf-8")
    assert "Sealed.exe" in bat_content
    assert "Sealed Sovereign Enclave" in bat_content

    ps_content = ps_path.read_text(encoding="utf-8")
    assert "Sealed.exe" in ps_content
    assert "lockdown_airgap.ps1" in ps_content


def test_package_payload_offline_configuration():
    """Verifies the packaged application payload enforces 100% offline air-gap operation."""
    app_dir = DIST_SETUP / "app"
    assert (app_dir / "Sealed.exe").exists(), "Payload Sealed.exe missing"
    assert (app_dir / "frontend" / "dist" / "index.html").exists(), "Payload frontend dist missing"
    assert (app_dir / "backend").exists(), "Payload backend directory missing"
    assert (app_dir / "models").exists(), "Payload models directory missing"
    assert (app_dir / "data" / "license.sig").exists(), "Payload offline license missing"

    env_path = app_dir / ".env"
    assert env_path.exists(), "Payload .env missing"
    env_content = env_path.read_text(encoding="utf-8")
    assert "AIRGAP_MODE=1" in env_content
    assert "HF_HUB_OFFLINE=1" in env_content
    assert "TRANSFORMERS_OFFLINE=1" in env_content
    assert "SEALED_AIRGAP_ENFORCED=1" in env_content


def test_package_manifest_integrity():
    """Verifies package_manifest.json contains valid SHA-256 hashes for all files."""
    manifest_path = DIST_SETUP / "package_manifest.json"
    assert manifest_path.exists(), "package_manifest.json missing"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "files" in data
    assert len(data["files"]) > 50
    for path, meta in data["files"].items():
        assert "sha256" in meta
        assert len(meta["sha256"]) == 64
        assert "size_bytes" in meta


def test_package_payload_pristine_zero_documents():
    """Confirms the packaged setup payload contains NO pre-existing files, documents, or vector points."""
    app_dir = DIST_SETUP / "app"
    data_dir = app_dir / "data"
    assert data_dir.exists(), "Data directory missing in app payload"

    uploads = list((data_dir / "uploads").iterdir())
    assert len(uploads) == 0, f"Payload uploads directory must be empty on installation, found: {uploads}"

    qdrant = list((data_dir / "qdrant_storage").iterdir())
    assert len(qdrant) == 0, f"Payload qdrant storage must be empty on installation, found: {qdrant}"

    db_files = list(data_dir.glob("*.db"))
    assert len(db_files) == 0, f"Payload must not bundle pre-existing database files, found: {db_files}"


