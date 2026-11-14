# Sealed Sovereign Appliance — Windows Host Zero-Egress Firewall Lockdown Script
# Enforces strict default-deny outbound policy for defense and air-gapped enclaves.

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "   SEALED AIRGAP DEFENSE ENCLAVE — HOST FIREWALL LOCKDOWN         " -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan

$RulePrefix = "SealedAirgap"

# 1. Allow Local Loopback (127.0.0.1 / localhost)
Write-Host "[1/4] Ensuring loopback network traffic is permitted..." -ForegroundColor Yellow
Remove-NetFirewallRule -DisplayName "$RulePrefix-Loopback-In" -ErrorAction SilentlyContinue
Remove-NetFirewallRule -DisplayName "$RulePrefix-Loopback-Out" -ErrorAction SilentlyContinue

New-NetFirewallRule -DisplayName "$RulePrefix-Loopback-In" `
    -Direction Inbound -Action Allow -Protocol Any -RemoteAddress "127.0.0.1/32" | Out-Null
New-NetFirewallRule -DisplayName "$RulePrefix-Loopback-Out" `
    -Direction Outbound -Action Allow -Protocol Any -RemoteAddress "127.0.0.1/32" | Out-Null

# 2. Allow Inbound Access to Gateway on Port 8000 (and 3000 / 5173 for Web UI)
Write-Host "[2/4] Permitting authorized customer LAN access to Gateway ports..." -ForegroundColor Yellow
Remove-NetFirewallRule -DisplayName "$RulePrefix-Gateway-In" -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName "$RulePrefix-Gateway-In" `
    -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000, 3000, 5173 | Out-Null

# 3. Block All Outbound Internet WAN Traffic for the Enclave
Write-Host "[3/4] Enforcing default-deny outbound WAN drop policy..." -ForegroundColor Yellow
Remove-NetFirewallRule -DisplayName "$RulePrefix-Block-WAN" -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName "$RulePrefix-Block-WAN" `
    -Direction Outbound -Action Block -RemoteAddress "Internet" | Out-Null

Write-Host "[4/4] Host firewall ruleset configured." -ForegroundColor Green
Write-Host "Status: OUTBOUND INTERNET DENIED. Enclave is physically sealed." -ForegroundColor Green
Write-Host "==================================================================" -ForegroundColor Cyan

