@echo off
setlocal enabledelayedexpansion
title Sealed Sovereign Enclave - Offline Installer
cd /d "%~dp0"

echo =====================================================================
echo   SEALED SOVEREIGN ENCLAVE - AIR-GAPPED DESKTOP INSTALLER
echo   Offline Standalone Installation ^| Zero Cloud Egress
echo =====================================================================
echo.

set "TARGET_DIR=%LOCALAPPDATA%\Sealed Sovereign Enclave"

echo [INFO] Target installation directory: !TARGET_DIR!
if not exist "!TARGET_DIR!" mkdir "!TARGET_DIR!"

echo [INFO] Copying application payload and local model weights...
xcopy /E /I /Y /Q "%~dp0app\*" "!TARGET_DIR!\" >nul

echo [INFO] Creating Desktop Shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([System.IO.Path]::Combine([Environment]::GetFolderPath('Desktop'), 'Sealed - Sovereign Intelligence.lnk')); $s.TargetPath = '%TARGET_DIR%\Sealed.exe'; $s.IconLocation = '%TARGET_DIR%\icons\icon.ico'; $s.Description = 'Sealed Sovereign Local Intelligence Enclave'; $s.Save()"

echo [INFO] Creating Start Menu Shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $programs = [Environment]::GetFolderPath('Programs'); $dir = Join-Path $programs 'Sealed Sovereign Enclave'; if (!(Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }; $s = $ws.CreateShortcut((Join-Path $dir 'Sealed.lnk')); $s.TargetPath = '%TARGET_DIR%\Sealed.exe'; $s.IconLocation = '%TARGET_DIR%\icons\icon.ico'; $s.Save()"

echo.
echo =====================================================================
echo   INSTALLATION COMPLETE!
echo   Desktop shortcut created: 'Sealed - Sovereign Intelligence'
echo =====================================================================
echo.
set /p RUN_NOW="Launch Sealed Desktop Application now? (Y/N): "
if /i "!RUN_NOW!"=="Y" (
    start "" "!TARGET_DIR%\Sealed.exe"
)
