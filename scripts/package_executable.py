#!/usr/bin/env python3
"""
Standalone Desktop Package and Executable Distribution Builder for Ragapp.

This builder:
1. Validates repository prerequisites (backend, frontend build, local models, conda/python runtime).
2. Compiles or verifies the React Single Page Application in `frontend/dist`.
3. Assembles a unified portable desktop distribution in `dist_desktop/`:
   - Backend application package (`backend/`)
   - Pre-compiled React SPA assets (`frontend/dist/`)
   - Local model repositories and configs (`models/`)
   - Data directories scaffolding (`data/uploads`, `data/qdrant_storage`)
   - Production offline configuration (`.env`)
4. Generates one-click native execution launchers:
   - `dist_desktop/RagApp.bat`: Interactive one-click runner with runtime auto-detection.
   - `dist_desktop/launch_desktop.vbs`: Quiet/silent launcher running with native window/browser
     without leaving console clutter.
   - `dist_desktop/launch_browser.bat`: Dedicated browser-mode launcher.
   - `dist_desktop/launch_headless.bat`: Dedicated background headless server launcher.
5. If PyInstaller is available, compiles a standalone `.exe` runner into `dist_desktop/bin/RagApp.exe`
   or `dist_desktop/RagApp.exe`.
6. Generates SHA-256 cryptographic manifests (`package_manifest.json`) and user instructions (`README.md`).
7. Executes an automated self-test verification (`--check-only`) to confirm the package boots cleanly.
"""

import os
import sys
import json
import shutil
import hashlib
import argparse
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

# Base paths
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "dist_desktop"
DEFAULT_FRONTEND_DIR = REPO_ROOT / "frontend"
DEFAULT_BACKEND_DIR = REPO_ROOT / "backend"
DEFAULT_MODELS_DIR = REPO_ROOT / "models"


def compute_sha256(file_path: Path, chunk_size: int = 65536) -> str:
    """Computes SHA-256 checksum of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def ensure_frontend_build(repo_root: Path, force_build: bool = False) -> bool:
    """
    Ensures frontend/dist exists with a valid index.html.
    If missing or force_build is True, attempts `npm run build`.
    """
    frontend_dir = repo_root / "frontend"
    dist_dir = frontend_dir / "dist"
    index_html = dist_dir / "index.html"

    if index_html.exists() and not force_build:
        print(f"  [OK] Found compiled frontend at {dist_dir}")
        return True

    print(f"  [*] Compiling React frontend via npm in {frontend_dir}...")
    npm_cmd = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm_cmd:
        print("  [!] Error: 'npm' command not found in PATH. Cannot build frontend.", file=sys.stderr)
        return index_html.exists()

    try:
        res = subprocess.run(
            [npm_cmd, "run", "build"],
            cwd=str(frontend_dir),
            capture_output=True,
            text=True,
            timeout=180,
            shell=True,
        )
        if res.returncode == 0 and index_html.exists():
            print("  [OK] Frontend built successfully into frontend/dist")
            return True
        else:
            print(f"  [!] Frontend build returned non-zero code {res.returncode}:\n{res.stderr}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"  [!] Failed to execute npm build: {e}", file=sys.stderr)
        return False


def copy_distribution_tree(repo_root: Path, output_dir: Path) -> Dict[str, Any]:
    """
    Assembles all essential application components into the portable distribution folder.
    """
    print(f"  [*] Assembling application tree into {output_dir}...")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Copy backend
    target_backend = output_dir / "backend"
    if target_backend.exists():
        shutil.rmtree(target_backend)
    
    def ignore_patterns(path, names):
        ignored = set()
        for name in names:
            if name in ("__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"):
                ignored.add(name)
            elif name.endswith((".pyc", ".pyo", ".pyd")):
                ignored.add(name)
        return ignored

    shutil.copytree(repo_root / "backend", target_backend, ignore=ignore_patterns)
    print("  [OK] Copied backend application module")

    # 2. Copy frontend dist
    target_frontend_dist = output_dir / "frontend" / "dist"
    if target_frontend_dist.exists():
        shutil.rmtree(target_frontend_dist)
    target_frontend_dist.parent.mkdir(parents=True, exist_ok=True)

    src_dist = repo_root / "frontend" / "dist"
    if src_dist.exists():
        shutil.copytree(src_dist, target_frontend_dist)
        print("  [OK] Copied compiled React SPA assets")
    else:
        print("  [!] Warning: frontend/dist not found!")

    # 3. Copy models if available
    src_models = repo_root / "models"
    target_models = output_dir / "models"
    if src_models.exists():
        if target_models.exists():
            shutil.rmtree(target_models)
        shutil.copytree(src_models, target_models, ignore=ignore_patterns)
        print("  [OK] Copied local models directory")
    else:
        target_models.mkdir(parents=True, exist_ok=True)

    # 4. Initialize clean data directories
    data_dir = output_dir / "data"
    (data_dir / "uploads").mkdir(parents=True, exist_ok=True)
    (data_dir / "qdrant_storage").mkdir(parents=True, exist_ok=True)
    print("  [OK] Prepared local data scaffolding (uploads, qdrant_storage)")

    # 5. Create local standalone .env configuration
    env_file = output_dir / ".env"
    env_content = (
        "# Ragapp Desktop Standalone Environment Configuration\n"
        "APP_NAME=Local Production RAG\n"
        "APP_VERSION=1.0.0\n"
        "APP_ENV=production\n"
        "DEBUG=False\n"
        "HOST=127.0.0.1\n"
        "PORT=8000\n"
        "AIRGAP_MODE=True\n"
        "QDRANT_PATH=./data/qdrant_storage\n"
        "DATABASE_URL=sqlite+aiosqlite:///./data/ragapp.db\n"
        "ENABLE_METRICS=True\n"
    )
    with open(env_file, "w", encoding="utf-8") as f:
        f.write(env_content)
    print("  [OK] Created production desktop .env file")

    return {
        "backend": str(target_backend),
        "frontend": str(target_frontend_dist),
        "models": str(target_models),
        "data": str(data_dir),
    }


def generate_launchers(output_dir: Path) -> List[Path]:
    """
    Creates one-click standalone runners:
    - RagApp.bat (Interactive batch script with runtime detection)
    - launch_desktop.vbs (Silent runner that launches native GUI with zero console window)
    - launch_browser.bat (Browser-only mode runner)
    - launch_headless.bat (Headless server runner)
    """
    created_files = []

    # 1. RagApp.bat
    bat_path = output_dir / "RagApp.bat"
    bat_content = r"""@echo off
setlocal enabledelayedexpansion
title Ragapp - Sovereign Local RAG System
cd /d "%~dp0"

echo =====================================================================
echo   RAGAPP - SOVEREIGN LOCAL INTELLIGENCE ^& RAG APPLICATION
echo =====================================================================
echo.

:: 1. Check if standalone compiled executable is present in bin or root
if exist "%~dp0bin\RagApp\RagApp.exe" (
    echo [*] Starting compiled native application binary...
    "%~dp0bin\RagApp\RagApp.exe" %*
    goto :end
)
if exist "%~dp0bin\RagApp.exe" (
    echo [*] Starting compiled native application binary...
    "%~dp0bin\RagApp.exe" %*
    goto :end
)
if exist "%~dp0RagApp.exe" (
    echo [*] Starting compiled native application binary...
    "%~dp0RagApp.exe" %*
    goto :end
)

:: 2. Search for Python interpreter
set "PYTHON_EXE="

:: Check bundled python
if exist "%~dp0python\python.exe" (
    set "PYTHON_EXE=%~dp0python\python.exe"
    goto :found_python
)

:: Check active conda environment
if defined CONDA_PREFIX (
    if exist "%CONDA_PREFIX%\python.exe" (
        set "PYTHON_EXE=%CONDA_PREFIX%\python.exe"
        goto :found_python
    )
)
if exist "%USERPROFILE%\miniconda3\envs\ragapp\python.exe" (
    set "PYTHON_EXE=%USERPROFILE%\miniconda3\envs\ragapp\python.exe"
    goto :found_python
)
if exist "%USERPROFILE%\anaconda3\envs\ragapp\python.exe" (
    set "PYTHON_EXE=%USERPROFILE%\anaconda3\envs\ragapp\python.exe"
    goto :found_python
)

:: Check system python
for %%P in (python.exe py.exe) do (
    where %%P >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_EXE=%%P"
        goto :found_python
    )
)

:found_python
if "%PYTHON_EXE%"=="" (
    echo [!] ERROR: Python 3.10+ runtime was not detected on this system.
    echo Please install Python or copy a portable python distribution into '%~dp0python\'.
    pause
    exit /b 1
)

:: 3. Configure environment variables
set "BASE_DIR=%~dp0"
set "AIRGAP_MODE=1"
set "HF_HUB_OFFLINE=1"
set "TRANSFORMERS_OFFLINE=1"
set "HF_DATASETS_OFFLINE=1"
set "PYTHONPATH=%~dp0;%~dp0backend;!PYTHONPATH!"

echo [*] Launching desktop application via !PYTHON_EXE!...
"%PYTHON_EXE%" "%~dp0backend\desktop_launcher.py" %*

:end
if %errorlevel% neq 0 (
    echo.
    echo [!] Application exited with status code %errorlevel%.
    pause
)
"""
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_content)
    created_files.append(bat_path)
    print(f"  [OK] Generated interactive launcher: {bat_path.name}")

    # 2. launch_desktop.vbs (Runs quietly without console clutter)
    vbs_path = output_dir / "launch_desktop.vbs"
    vbs_content = r'''Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strPath = fso.GetParentFolderName(WScript.ScriptFullName)

' Collect any arguments passed to the script
args = ""
For i = 0 To WScript.Arguments.Count - 1
    args = args & " """ & WScript.Arguments(i) & """"
Next

' Check if standalone binary exists
If fso.FileExists(strPath & "\bin\RagApp\RagApp.exe") Then
    WshShell.Run """" & strPath & "\bin\RagApp\RagApp.exe""" & args, 0, False
ElseIf fso.FileExists(strPath & "\bin\RagApp.exe") Then
    WshShell.Run """" & strPath & "\bin\RagApp.exe""" & args, 0, False
ElseIf fso.FileExists(strPath & "\RagApp.exe") Then
    WshShell.Run """" & strPath & "\RagApp.exe""" & args, 0, False
Else
    ' Run RagApp.bat with window hidden (0 = hide window, False = asynchronous)
    WshShell.Run """" & strPath & "\RagApp.bat""" & args, 0, False
End If
'''
    with open(vbs_path, "w", encoding="utf-8") as f:
        f.write(vbs_content)
    created_files.append(vbs_path)
    print(f"  [OK] Generated silent windowless launcher: {vbs_path.name}")

    # 3. launch_browser.bat
    browser_bat = output_dir / "launch_browser.bat"
    browser_content = r"""@echo off
cd /d "%~dp0"
call "%~dp0RagApp.bat" --browser %*
"""
    with open(browser_bat, "w", encoding="utf-8") as f:
        f.write(browser_content)
    created_files.append(browser_bat)
    print(f"  [OK] Generated browser launcher: {browser_bat.name}")

    # 4. launch_headless.bat
    headless_bat = output_dir / "launch_headless.bat"
    headless_content = r"""@echo off
cd /d "%~dp0"
call "%~dp0RagApp.bat" --headless %*
"""
    with open(headless_bat, "w", encoding="utf-8") as f:
        f.write(headless_content)
    created_files.append(headless_bat)
    print(f"  [OK] Generated headless launcher: {headless_bat.name}")

    return created_files


def compile_pyinstaller_exe(repo_root: Path, output_dir: Path) -> Optional[Path]:
    """
    Attempts to compile backend/desktop_launcher.py into a standalone .exe binary
    using PyInstaller if available in the environment.
    """
    pyinstaller_cmd = None
    # Check conda env first, then PATH
    conda_candidates = [
        Path(os.environ.get("CONDA_PREFIX", "")) / "Scripts" / "pyinstaller.exe",
        Path.home() / "miniconda3" / "envs" / "ragapp" / "Scripts" / "pyinstaller.exe",
        Path.home() / "anaconda3" / "envs" / "ragapp" / "Scripts" / "pyinstaller.exe",
    ]
    for cand in conda_candidates:
        if cand.exists():
            pyinstaller_cmd = str(cand)
            break
    if not pyinstaller_cmd:
        which_pi = shutil.which("pyinstaller")
        if which_pi:
            pyinstaller_cmd = which_pi

    if not pyinstaller_cmd:
        print("  [-] PyInstaller not detected. Skipping standalone .exe compilation.")
        return None

    bin_dir = output_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    launcher_py = repo_root / "backend" / "desktop_launcher.py"

    print(f"  [*] Compiling standalone executable via PyInstaller: {pyinstaller_cmd}...")
    cmd = [
        pyinstaller_cmd,
        "--name", "RagApp",
        "--onedir",
        "--distpath", str(bin_dir),
        "--workpath", str(repo_root / "build_temp"),
        "--specpath", str(repo_root / "build_temp"),
        "--clean",
        "--noconfirm",
        "--log-level", "WARN",
        "--hidden-import", "aiosqlite",
        "--hidden-import", "sqlalchemy.dialects.sqlite.aiosqlite",
        "--hidden-import", "sqlite3",
        "--collect-all", "uvicorn",
        "--collect-all", "aiosqlite",
        "--collect-all", "fastapi",
        "--collect-all", "starlette",
        str(launcher_py),
    ]

    try:
        res = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True, timeout=300)
        # Clean build temp
        temp_dir = repo_root / "build_temp"
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

        built_exe = bin_dir / "RagApp" / "RagApp.exe"
        if built_exe.exists():
            print(f"  [OK] Standalone executable successfully built: {built_exe}")
            return built_exe
        else:
            print(f"  [!] PyInstaller completed but binary not found at expected path: {res.stderr}")
            return None
    except Exception as e:
        print(f"  [!] PyInstaller build failed: {e}")
        return None


def generate_manifest(output_dir: Path, repo_root: Path, exe_path: Optional[Path] = None) -> Path:
    """
    Generates cryptographic manifest (package_manifest.json) and README.md.
    """
    manifest_file = output_dir / "package_manifest.json"
    readme_file = output_dir / "README.md"

    # Compute key asset hashes
    key_files = {}
    for rel_path in [
        "RagApp.bat",
        "launch_desktop.vbs",
        "launch_browser.bat",
        "launch_headless.bat",
        ".env",
        "backend/desktop_launcher.py",
        "backend/app/main.py",
        "frontend/dist/index.html",
    ]:
        fpath = output_dir / rel_path
        if fpath.exists():
            key_files[rel_path] = {
                "sha256": compute_sha256(fpath),
                "size_bytes": fpath.stat().st_size,
            }

    if exe_path and exe_path.exists():
        key_files["bin/RagApp/RagApp.exe"] = {
            "sha256": compute_sha256(exe_path),
            "size_bytes": exe_path.stat().st_size,
        }

    manifest_data = {
        "package_name": "Ragapp Desktop Standalone",
        "version": "1.0.0",
        "build_target": "windows-x86_64",
        "components": {
            "fastapi_backend": True,
            "qdrant_vector_store": True,
            "react_single_page_app": True,
            "airgap_offline_mode": True,
            "desktop_pywebview_window": True,
            "silent_vbs_launcher": True,
            "one_click_batch_runner": True,
        },
        "entrypoints": {
            "one_click_interactive": "RagApp.bat",
            "windowless_silent": "launch_desktop.vbs",
            "browser_mode": "launch_browser.bat",
            "headless_server": "launch_headless.bat",
            "python_entrypoint": "backend/desktop_launcher.py",
        },
        "checksums": key_files,
    }

    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)
    print(f"  [OK] Generated cryptographic package manifest: {manifest_file.name}")

    readme_content = """# Ragapp - Sovereign Local RAG Desktop Package

This directory contains the standalone, fully portable local distribution of **Ragapp**.
It connects the complete FastAPI backend, local vector store, local inference detectors,
and the compiled React + TypeScript frontend into a single unified desktop application.

## Quick Start (How to Run)

### Option 1: Silent Desktop App (Recommended)
Double-click **`launch_desktop.vbs`**.
- Starts the backend quietly without opening a black command prompt window.
- Opens the application in a native desktop window (or your default browser).

### Option 2: One-Click Interactive Runner
Double-click **`RagApp.bat`**.
- Displays startup status, system checks, and local port assignments.
- Supports command-line options:
  - `RagApp.bat --browser` (Open in system web browser)
  - `RagApp.bat --headless` (Run backend server only)
  - `RagApp.bat --port 8080` (Specify custom listening port)
  - `RagApp.bat --check-only` (Run automated diagnostic self-test)

## Architecture Overview
- **Single-Port Architecture**: FastAPI hosts both `/api/v1/...` REST endpoints and the compiled Single Page Application (`/`) on port `8000`.
- **Zero-Egress Enforcement**: Offline air-gap mode is locked via `AIRGAP_MODE=True` and HuggingFace offline environment flags.
- **Embedded Storage**: Relational records in `./data/ragapp.db` (SQLite) and vector embeddings in `./data/qdrant_storage/`.
- **Hardware Integration**: Automatically detects NVIDIA RTX / AMD GPUs for local high-throughput inference.
"""
    with open(readme_file, "w", encoding="utf-8") as f:
        f.write(readme_content)
    print(f"  [OK] Generated documentation: {readme_file.name}")

    return manifest_file


def verify_package(output_dir: Path) -> bool:
    """
    Boots the packaged application using desktop_launcher.py with --check-only
    to verify that the package is fully operational.
    """
    print("  [*] Running automated verification test on packaged distribution...")
    launcher = output_dir / "backend" / "desktop_launcher.py"
    if not launcher.exists():
        print(f"  [!] Launcher script not found at {launcher}", file=sys.stderr)
        return False

    python_exe = sys.executable
    cmd = [python_exe, str(launcher), "--check-only", "--port", "8096"]

    env = os.environ.copy()
    env["BASE_DIR"] = str(output_dir)

    try:
        res = subprocess.run(
            cmd,
            cwd=str(output_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if res.returncode == 0:
            print("  [OK] Verification self-test PASSED! Backend booted, connected, and verified cleanly.")
            return True
        else:
            print(f"  [!] Verification self-test FAILED with exit code {res.returncode}:\n{res.stderr}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"  [!] Verification failed with exception: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Ragapp Standalone Desktop Packaging Tool")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Destination distribution directory")
    parser.add_argument("--build-exe", action="store_true", help="Compile standalone PyInstaller executable")
    parser.add_argument("--skip-exe", action="store_true", help="Skip PyInstaller compilation")
    parser.add_argument("--force-build-frontend", action="store_true", help="Force npm rebuild of React frontend")
    parser.add_argument("--verify", action="store_true", default=True, help="Run diagnostic health test on packaged build")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    print("=====================================================================")
    print("  RAGAPP - STANDALONE DESKTOP APPLICATION PACKAGER")
    print("=====================================================================")
    print(f"Target Output Directory: {output_dir}")

    # Step 1: Ensure frontend build
    if not ensure_frontend_build(REPO_ROOT, force_build=args.force_build_frontend):
        print("[-] Frontend build verification failed. Aborting packaging.", file=sys.stderr)
        sys.exit(1)

    # Step 2: Copy distribution tree
    copy_distribution_tree(REPO_ROOT, output_dir)

    # Step 3: Generate launchers
    generate_launchers(output_dir)

    # Step 4: Standalone executable compilation
    exe_path = None
    if args.build_exe or (not args.skip_exe and shutil.which("pyinstaller")):
        exe_path = compile_pyinstaller_exe(REPO_ROOT, output_dir)

    # Step 5: Manifest & documentation
    generate_manifest(output_dir, REPO_ROOT, exe_path=exe_path)

    # Step 6: Package self-test
    if args.verify:
        success = verify_package(output_dir)
        if not success:
            print("[!] Package verification encountered errors.", file=sys.stderr)
            sys.exit(1)

    print("=====================================================================")
    print(f"  SUCCESS: Standalone package generated at: {output_dir}")
    print("  Run 'dist_desktop/RagApp.bat' or 'dist_desktop/launch_desktop.vbs' to launch.")
    print("=====================================================================")


if __name__ == "__main__":
    main()
