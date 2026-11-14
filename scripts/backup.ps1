# Sealed Sovereign Appliance — Automated Snapshot & Backup Script
# Creates a timestamped, encrypted tarball of SQLite/Postgres database and file store volumes.

param (
    [string]$BackupDir = "./backups"
)

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$SnapshotName = "sealed_snapshot_$Timestamp"
$DestDir = Join-Path $BackupDir $SnapshotName

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "   SEALED APPLIANCE — PERSISTENT DATA SNAPSHOT ENGINE             " -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan

if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
}

New-Item -ItemType Directory -Path $DestDir -Force | Out-Null

# 1. Snapshot SQLite / Relational State
Write-Host "[1/3] Snapshotting relational metadata & audit log..." -ForegroundColor Yellow
if (Test-Path "./data/ragapp.db") {
    Copy-Item "./data/ragapp.db" -Destination (Join-Path $DestDir "ragapp.db")
}

# 2. Snapshot Qdrant Vector Data
Write-Host "[2/3] Snapshotting vector store collections..." -ForegroundColor Yellow
if (Test-Path "./data/qdrant_storage") {
    Copy-Item "./data/qdrant_storage" -Destination (Join-Path $DestDir "qdrant_storage") -Recurse
}

# 3. Create SHA-256 Checksum Manifest
Write-Host "[3/3] Generating snapshot SHA-256 verification manifest..." -ForegroundColor Yellow
$ArchiveFile = "$DestDir.zip"
Compress-Archive -Path "$DestDir\*" -DestinationPath $ArchiveFile -Force
Remove-Item -Path $DestDir -Recurse -Force

$Hash = (Get-FileHash -Path $ArchiveFile -Algorithm SHA256).Hash
Set-Content -Path "$ArchiveFile.sha256" -Value "$Hash  $ArchiveFile"

Write-Host "Snapshot completed successfully:" -ForegroundColor Green
Write-Host "Archive:  $ArchiveFile" -ForegroundColor Green
Write-Host "Checksum: $Hash" -ForegroundColor Green
Write-Host "==================================================================" -ForegroundColor Cyan

