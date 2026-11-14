#!/usr/bin/env python3
"""
Offline Desktop Package & Setup Installer Builder for Sealed Sovereign Enclave.

This script:
1. Validates the compiled Tauri desktop binary (Sealed.exe).
2. Packages the full offline application tree (Tauri native shell, React SPA,
   FastAPI sovereign backend, Qdrant/SQLite storage, and offline models).
3. Generates the enterprise Inno Setup script (setup.iss).
4. Compiles the standalone self-extracting installer executable: `Sealed_Setup_x64.exe`.
5. Generates the one-click `Install_Sealed_Offline.bat` and `setup_offline.ps1` runners.
6. Computes SHA-256 integrity checksums for the entire offline distribution.
"""

import os
import sys
import json
import shutil
import hashlib
import hmac
import subprocess
from pathlib import Path
from typing import Dict, Any, List

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = REPO_ROOT / "frontend"
TAURI_RELEASE_DIR = FRONTEND_DIR / "src-tauri" / "target" / "release"
DIST_SETUP_DIR = REPO_ROOT / "dist_setup"
APP_PAYLOAD_DIR = DIST_SETUP_DIR / "app"

local_app_data = os.environ.get("LOCALAPPDATA")
ISCC_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
]
if local_app_data:
    ISCC_CANDIDATES.insert(0, Path(local_app_data) / "Programs" / "Inno Setup 6" / "ISCC.exe")


def compute_sha256(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def find_iscc() -> Path | None:
    for cand in ISCC_CANDIDATES:
        if cand.exists():
            return cand
    which_iscc = shutil.which("ISCC.exe") or shutil.which("iscc")
    if which_iscc:
        return Path(which_iscc)
    return None


def assemble_app_payload():
    print(f"[*] Assembling offline application payload into {APP_PAYLOAD_DIR}...")
    if APP_PAYLOAD_DIR.exists():
        shutil.rmtree(APP_PAYLOAD_DIR, ignore_errors=True)
    APP_PAYLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Locate and copy Sealed.exe
    sealed_exe = TAURI_RELEASE_DIR / "sealed.exe"
    if not sealed_exe.exists():
        sealed_exe = TAURI_RELEASE_DIR / "app.exe"
    if not sealed_exe.exists():
        raise FileNotFoundError(f"Tauri binary not found in {TAURI_RELEASE_DIR}. Compile it first.")

    dest_exe = APP_PAYLOAD_DIR / "Sealed.exe"
    shutil.copy2(sealed_exe, dest_exe)
    print(f"  [+] Copied Tauri native executable: {dest_exe} ({dest_exe.stat().st_size / 1024 / 1024:.2f} MB)")

    # 2. Copy icons
    icons_src = FRONTEND_DIR / "src-tauri" / "icons"
    if icons_src.exists():
        shutil.copytree(icons_src, APP_PAYLOAD_DIR / "icons", dirs_exist_ok=True)

    # 3. Copy React Frontend dist
    frontend_dist = FRONTEND_DIR / "dist"
    if not (frontend_dist / "index.html").exists():
        raise FileNotFoundError(f"React frontend dist not found at {frontend_dist}")
    shutil.copytree(frontend_dist, APP_PAYLOAD_DIR / "frontend" / "dist", dirs_exist_ok=True)
    print("  [+] Copied compiled React SPA into frontend/dist/")

    # 4. Copy Backend
    backend_src = REPO_ROOT / "backend"
    shutil.copytree(
        backend_src,
        APP_PAYLOAD_DIR / "backend",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".pytest_cache"),
    )
    print("  [+] Copied FastAPI sovereign backend package")

    # 5. Copy Models (Offline Model Integration)
    models_src = REPO_ROOT / "models"
    if not models_src.exists():
        models_src = REPO_ROOT / "dist_desktop" / "models"

    dest_models = APP_PAYLOAD_DIR / "models"
    dest_models.mkdir(parents=True, exist_ok=True)
    if models_src.exists():
        shutil.copytree(models_src, dest_models, dirs_exist_ok=True)
        print(f"  [+] Copied offline model repositories from {models_src}")
    else:
        (dest_models / "embeddings").mkdir(exist_ok=True)
        (dest_models / "reranker").mkdir(exist_ok=True)
        (dest_models / "llm").mkdir(exist_ok=True)

    # 6. Scaffolding Data Directories & Offline Signed License
    data_dir = APP_PAYLOAD_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "uploads").mkdir(exist_ok=True)
    (data_dir / "qdrant_storage").mkdir(exist_ok=True)

    # Generate offline signed enterprise pilot license (deterministic HMAC-SHA256)
    try:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        expiry = datetime.fromtimestamp(now.timestamp() + (60 * 86400), timezone.utc)
        payload = {
            "licensee": "Air-Gapped Sovereign Customer",
            "type": "Fixed-Scope 60-Day Pilot",
            "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expires_at": expiry.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "max_gpus": 2,
            "features": ["airgap_retrieval", "lora_tuning", "rag_triad_evals", "tamper_evident_ledger"],
            "telemetry_disabled": True,
            "license_server_required": False,
        }
        canonical_str = json.dumps(payload, sort_keys=True)
        secret_key = b"SEALED_SOVEREIGN_OFFLINE_ROOT_KEY_2026_AIRGAP"
        signature = hmac.new(secret_key, canonical_str.encode("utf-8"), hashlib.sha256).hexdigest()
        license_dict = {"payload": payload, "signature": signature, "algorithm": "HMAC-SHA256"}
        with open(data_dir / "license.sig", "w", encoding="utf-8") as f:
            f.write(json.dumps(license_dict, indent=2))
        print("  [+] Generated offline HMAC-SHA256 enterprise license: data/license.sig")
    except Exception as e:
        print(f"  [!] Note: License token generation fallback: {e}")

    # 7. Copy Scripts & Launchers
    scripts_dest = APP_PAYLOAD_DIR / "scripts"
    scripts_dest.mkdir(parents=True, exist_ok=True)
    for s_name in ["lockdown_airgap.ps1", "lockdown_airgap.sh", "backup.ps1", "preflight_check.py", "smoke_test.py", "no_egress_test.py"]:
        src_f = REPO_ROOT / "scripts" / s_name
        if src_f.exists():
            shutil.copy2(src_f, scripts_dest / s_name)

    if (REPO_ROOT / "backend" / "desktop_launcher.py").exists():
        shutil.copy2(REPO_ROOT / "backend" / "desktop_launcher.py", APP_PAYLOAD_DIR / "desktop_launcher.py")

    # 8. Write strictly offline .env
    env_content = (
        "# Sealed Sovereign Enclave — Production Air-Gap Configuration\n"
        "AIRGAP_MODE=1\n"
        "HF_HUB_OFFLINE=1\n"
        "TRANSFORMERS_OFFLINE=1\n"
        "HF_DATASETS_OFFLINE=1\n"
        "SEALED_AIRGAP_ENFORCED=1\n\n"
        "APP_NAME=Sealed\n"
        "APP_VERSION=1.0.0\n"
        "APP_HOST=127.0.0.1\n"
        "APP_PORT=8000\n\n"
        "VLLM_API_BASE=http://127.0.0.1:8001/v1\n"
        "ACTIVE_MODEL_NAME=Qwen/Qwen2.5-3B-Instruct\n"
        "EMBEDDING_MODEL_NAME=BAAI/bge-small-en-v1.5\n"
        "RERANKER_MODEL_NAME=BAAI/bge-reranker-base\n\n"
        "QDRANT_STORAGE_DIR=./data/qdrant_storage\n"
        "DATABASE_URL=sqlite+aiosqlite:///./data/sealed_sovereign.db\n"
        "AUDIT_LOG_PATH=./data/audit_ledger.jsonl\n"
        "LICENSE_FILE_PATH=./data/license.sig\n"
    )
    with open(APP_PAYLOAD_DIR / ".env", "w", encoding="utf-8") as f:
        f.write(env_content)
    print("  [+] Configured 100% offline airgap environment (.env)")

    # 9. Standalone Native Windows Backend Runtime (Zero Docker / Zero External Python dependency)
    backend_runtime_src = REPO_ROOT / "test_dist" / "sealed-backend"
    if not backend_runtime_src.exists():
        backend_runtime_src = REPO_ROOT / "dist_backend" / "sealed-backend"

    if backend_runtime_src.exists():
        dest_backend_runtime = APP_PAYLOAD_DIR / "sealed-backend"
        if dest_backend_runtime.exists():
            shutil.rmtree(dest_backend_runtime, ignore_errors=True)
        shutil.copytree(backend_runtime_src, dest_backend_runtime)
        print("  [+] Bundled native Windows standalone backend runtime into sealed-backend/ (Zero Docker dependency)")
    else:
        print("  [!] Warning: Standalone backend runtime not found in test_dist/sealed-backend")


def generate_inno_setup_script() -> Path:
    iss_path = DIST_SETUP_DIR / "setup.iss"
    app_dir_abs = str(APP_PAYLOAD_DIR.resolve())
    icon_path_abs = str((APP_PAYLOAD_DIR / "icons" / "icon.ico").resolve())
    dist_setup_abs = str(DIST_SETUP_DIR.resolve())

    lines = [
        "; Sealed Sovereign Enclave - Inno Setup Script",
        '#define MyAppName "Sealed Sovereign Enclave"',
        '#define MyAppVersion "1.0.0"',
        '#define MyAppPublisher "Sealed Systems Inc."',
        '#define MyAppExeName "Sealed.exe"',
        "",
        "[Setup]",
        "AppId={{B98E7B24-8134-4C57-9C1D-89736450A9F1}}",
        "AppName={#MyAppName}",
        "AppVersion={#MyAppVersion}",
        "AppPublisher={#MyAppPublisher}",
        "DefaultDirName={autopf}\\{#MyAppName}",
        "DefaultGroupName={#MyAppName}",
        "PrivilegesRequired=lowest",
        "PrivilegesRequiredOverridesAllowed=dialog commandline",
        "DisableProgramGroupPage=yes",
        "OutputBaseFilename=Sealed_Setup_x64",
        "OutputDir=.",
        "Compression=lzma2/ultra64",
        "SolidCompression=yes",
        "ArchitecturesInstallIn64BitMode=x64compatible",
        "WizardStyle=modern",
        "SetupIconFile=app\\icons\\icon.ico",
        "UninstallDisplayIcon={app}\\{#MyAppExeName}",
        "",
        "[Languages]",
        'Name: "english"; MessagesFile: "compiler:Default.isl"',
        "",
        "[Tasks]",
        'Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"',
        'Name: "lockdownfirewall"; Description: "Enforce Host Air-Gap Lockdown (Block all outbound traffic, permit local loopback)"; Flags: checkedonce',
        "",
        "[Dirs]",
        'Name: "{app}\\data"; Permissions: users-modify',
        "",
        "[Files]",
        'Source: "app\\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs',
        "",
        "[Icons]",
        'Name: "{group}\\{#MyAppName}"; Filename: "{app}\\{#MyAppExeName}"; IconFilename: "{app}\\icons\\icon.ico"',
        'Name: "{group}\\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"',
        'Name: "{autodesktop}\\{#MyAppName}"; Filename: "{app}\\{#MyAppExeName}"; IconFilename: "{app}\\icons\\icon.ico"; Tasks: desktopicon',
        "",
        "[Run]",
        'Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\\scripts\\lockdown_airgap.ps1"""; Flags: runhidden; Tasks: lockdownfirewall',
        'Filename: "{app}\\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent',
    ]

    with open(iss_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  [+] Generated Inno Setup script: {iss_path}")
    return iss_path


def compile_inno_setup(iss_path: Path) -> bool:
    iscc = find_iscc()
    if not iscc:
        print("  [!] ISCC.exe not found. Skipping .exe compilation.")
        return False

    print(f"[*] Compiling standalone setup executable via {iscc}...")
    res = subprocess.run([str(iscc), str(iss_path)], capture_output=True, text=True)
    if res.returncode == 0:
        setup_exe = DIST_SETUP_DIR / "Sealed_Setup_x64.exe"
        if setup_exe.exists():
            size_mb = setup_exe.stat().st_size / (1024 * 1024)
            print(f"  [SUCCESS] Compiled standalone installer: {setup_exe} ({size_mb:.2f} MB)")
            return True
    else:
        print(f"  [!] Inno Setup compiler output:\n{res.stdout}\n{res.stderr}")
        return False
    return False


def generate_batch_and_ps_installers():
    # 1. Install_Sealed_Offline.bat
    bat_lines = [
        "@echo off",
        "setlocal enabledelayedexpansion",
        "title Sealed Sovereign Enclave - Offline Installer",
        'cd /d "%~dp0"',
        "",
        "echo =====================================================================",
        "echo   SEALED SOVEREIGN ENCLAVE - AIR-GAPPED DESKTOP INSTALLER",
        "echo   Offline Standalone Installation ^| Zero Cloud Egress",
        "echo =====================================================================",
        "echo.",
        "",
        'set "TARGET_DIR=%LOCALAPPDATA%\\Sealed Sovereign Enclave"',
        "",
        "echo [INFO] Target installation directory: !TARGET_DIR!",
        'if not exist "!TARGET_DIR!" mkdir "!TARGET_DIR!"',
        "",
        "echo [INFO] Copying application payload and local model weights...",
        'xcopy /E /I /Y /Q "%~dp0app\\*" "!TARGET_DIR!\\" >nul',
        "",
        "echo [INFO] Creating Desktop Shortcut...",
        'powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([System.IO.Path]::Combine([Environment]::GetFolderPath(\'Desktop\'), \'Sealed - Sovereign Intelligence.lnk\')); $s.TargetPath = \'%TARGET_DIR%\\Sealed.exe\'; $s.IconLocation = \'%TARGET_DIR%\\icons\\icon.ico\'; $s.Description = \'Sealed Sovereign Local Intelligence Enclave\'; $s.Save()"',
        "",
        "echo [INFO] Creating Start Menu Shortcut...",
        'powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $programs = [Environment]::GetFolderPath(\'Programs\'); $dir = Join-Path $programs \'Sealed Sovereign Enclave\'; if (!(Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }; $s = $ws.CreateShortcut((Join-Path $dir \'Sealed.lnk\')); $s.TargetPath = \'%TARGET_DIR%\\Sealed.exe\'; $s.IconLocation = \'%TARGET_DIR%\\icons\\icon.ico\'; $s.Save()"',
        "",
        "echo.",
        "echo =====================================================================",
        "echo   INSTALLATION COMPLETE!",
        "echo   Desktop shortcut created: \'Sealed - Sovereign Intelligence\'",
        "echo =====================================================================",
        "echo.",
        'set /p RUN_NOW="Launch Sealed Desktop Application now? (Y/N): "',
        'if /i "!RUN_NOW!"=="Y" (',
        '    start "" "!TARGET_DIR%\\Sealed.exe"',
        ")",
    ]
    with open(DIST_SETUP_DIR / "Install_Sealed_Offline.bat", "w", encoding="utf-8") as f:
        f.write("\n".join(bat_lines) + "\n")

    # 2. setup_offline.ps1
    ps_lines = [
        "# Sealed Sovereign Enclave - Enterprise PowerShell Setup",
        "[CmdletBinding()]",
        "param(",
        '    [string]$InstallPath = "$env:LOCALAPPDATA\\Sealed Sovereign Enclave",',
        '    [string]$ApplyAirgapFirewall = "false",',
        '    [string]$LaunchAfterInstall = "true"',
        ")",
        "",
        'Write-Host "=====================================================================" -ForegroundColor Cyan',
        'Write-Host "  SEALED SOVEREIGN ENCLAVE - ENTERPRISE AIR-GAP SETUP" -ForegroundColor Cyan',
        'Write-Host "=====================================================================" -ForegroundColor Cyan',
        'Write-Host ""',
        "",
        '$SourceDir = Join-Path $PSScriptRoot "app"',
        "if (!(Test-Path $SourceDir)) {",
        '    Write-Error "Application source payload not found at \'$SourceDir\'."',
        "    exit 1",
        "}",
        "",
        'Write-Host "[INFO] Destination path: $InstallPath" -ForegroundColor Yellow',
        "if (!(Test-Path $InstallPath)) {",
        "    New-Item -ItemType Directory -Path $InstallPath -Force | Out-Null",
        "}",
        "",
        'Write-Host "[INFO] Copying Sealed binaries, React frontend, and local models..." -ForegroundColor Gray',
        'Copy-Item -Path "$SourceDir\\*" -Destination $InstallPath -Recurse -Force',
        "",
        "# Create Desktop Shortcut",
        "$WshShell = New-Object -ComObject WScript.Shell",
        '$DesktopPath = [Environment]::GetFolderPath("Desktop")',
        '$ShortcutPath = Join-Path $DesktopPath "Sealed - Sovereign Intelligence.lnk"',
        "$Shortcut = $WshShell.CreateShortcut($ShortcutPath)",
        '$Shortcut.TargetPath = Join-Path $InstallPath "Sealed.exe"',
        '$Shortcut.IconLocation = Join-Path $InstallPath "icons\\icon.ico"',
        '$Shortcut.Description = "Sealed Sovereign Air-Gapped Desktop Intelligence"',
        "$Shortcut.Save()",
        'Write-Host "[SUCCESS] Desktop shortcut created." -ForegroundColor Green',
        "",
        "# Optional Firewall Lockdown",
        'if ($ApplyAirgapFirewall -eq "true" -or $ApplyAirgapFirewall -eq $true) {',
        '    $FirewallScript = Join-Path $InstallPath "scripts\\lockdown_airgap.ps1"',
        "    if (Test-Path $FirewallScript) {",
        '        Write-Host "[INFO] Applying default-deny air-gap host firewall rules..." -ForegroundColor Yellow',
        "        & powershell -NoProfile -ExecutionPolicy Bypass -File $FirewallScript",
        "    }",
        "}",
        "",
        'Write-Host ""',
        'Write-Host "[SUCCESS] Sealed Sovereign Enclave installed successfully!" -ForegroundColor Green',
        "",
        'if ($LaunchAfterInstall -eq "true" -or $LaunchAfterInstall -eq $true) {',
        '    Write-Host "[INFO] Launching Sealed desktop application..." -ForegroundColor Cyan',
        '    Start-Process -FilePath (Join-Path $InstallPath "Sealed.exe")',
        "}",
    ]
    with open(DIST_SETUP_DIR / "setup_offline.ps1", "w", encoding="utf-8") as f:
        f.write("\n".join(ps_lines) + "\n")
    print("  [+] Generated Install_Sealed_Offline.bat and setup_offline.ps1")


def generate_manifest():
    manifest_entries = {}
    for p in DIST_SETUP_DIR.rglob("*"):
        if p.is_file():
            rel = str(p.relative_to(DIST_SETUP_DIR)).replace("\\", "/")
            manifest_entries[rel] = {
                "size_bytes": p.stat().st_size,
                "sha256": compute_sha256(p),
            }
    with open(DIST_SETUP_DIR / "package_manifest.json", "w", encoding="utf-8") as f:
        json.dump({"manifest_version": "1.0.0", "package": "Sealed_Setup", "files": manifest_entries}, f, indent=2)
    print(f"  [+] Generated SHA-256 integrity manifest ({len(manifest_entries)} files)")


def main():
    print("=" * 70)
    print("  BUILDING SEALED SOVEREIGN DESKTOP & OFFLINE SETUP INSTALLER")
    print("=" * 70)
    DIST_SETUP_DIR.mkdir(parents=True, exist_ok=True)
    assemble_app_payload()
    iss_path = generate_inno_setup_script()
    compile_inno_setup(iss_path)
    generate_batch_and_ps_installers()
    generate_manifest()
    print("=" * 70)
    print("  SETUP PACKAGE READY IN dist_setup/")
    print("=" * 70)


if __name__ == "__main__":
    main()
