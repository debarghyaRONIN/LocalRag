# Sealed Sovereign Enclave - Enterprise PowerShell Setup
[CmdletBinding()]
param(
    [string]$InstallPath = "$env:LOCALAPPDATA\Sealed Sovereign Enclave",
    [string]$ApplyAirgapFirewall = "false",
    [string]$LaunchAfterInstall = "true"
)

Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "  SEALED SOVEREIGN ENCLAVE - ENTERPRISE AIR-GAP SETUP" -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host ""

$SourceDir = Join-Path $PSScriptRoot "app"
if (!(Test-Path $SourceDir)) {
    Write-Error "Application source payload not found at '$SourceDir'."
    exit 1
}

Write-Host "[INFO] Destination path: $InstallPath" -ForegroundColor Yellow
if (!(Test-Path $InstallPath)) {
    New-Item -ItemType Directory -Path $InstallPath -Force | Out-Null
}

Write-Host "[INFO] Copying Sealed binaries, React frontend, and local models..." -ForegroundColor Gray
Copy-Item -Path "$SourceDir\*" -Destination $InstallPath -Recurse -Force

# Create Desktop Shortcut
$WshShell = New-Object -ComObject WScript.Shell
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopPath "Sealed - Sovereign Intelligence.lnk"
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = Join-Path $InstallPath "Sealed.exe"
$Shortcut.IconLocation = Join-Path $InstallPath "icons\icon.ico"
$Shortcut.Description = "Sealed Sovereign Air-Gapped Desktop Intelligence"
$Shortcut.Save()
Write-Host "[SUCCESS] Desktop shortcut created." -ForegroundColor Green

# Optional Firewall Lockdown
if ($ApplyAirgapFirewall -eq "true" -or $ApplyAirgapFirewall -eq $true) {
    $FirewallScript = Join-Path $InstallPath "scripts\lockdown_airgap.ps1"
    if (Test-Path $FirewallScript) {
        Write-Host "[INFO] Applying default-deny air-gap host firewall rules..." -ForegroundColor Yellow
        & powershell -NoProfile -ExecutionPolicy Bypass -File $FirewallScript
    }
}

Write-Host ""
Write-Host "[SUCCESS] Sealed Sovereign Enclave installed successfully!" -ForegroundColor Green

if ($LaunchAfterInstall -eq "true" -or $LaunchAfterInstall -eq $true) {
    Write-Host "[INFO] Launching Sealed desktop application..." -ForegroundColor Cyan
    Start-Process -FilePath (Join-Path $InstallPath "Sealed.exe")
}
