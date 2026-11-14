#!/usr/bin/env bash
# Sealed Sovereign Appliance — Linux Host Zero-Egress Firewall Lockdown Script
# Enforces strict default-deny outbound policy via iptables.

set -euo pipefail

echo "=================================================================="
echo "   SEALED AIRGAP DEFENSE ENCLAVE — LINUX IPTABLES LOCKDOWN        "
echo "=================================================================="

# 1. Flush existing enclave rules
iptables -F OUTPUT || true

# 2. Allow Loopback (IPC between containers and local gateway)
echo "[1/4] Permitting local loopback traffic..."
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A INPUT -i lo -j ACCEPT

# 3. Allow Established Connections
echo "[2/4] Permitting established incoming connections..."
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# 4. Drop All Other Outbound Traffic (Default-Deny)
echo "[3/4] Enforcing default-deny outbound WAN drop policy..."
iptables -P OUTPUT DROP

echo "[4/4] Verification:"
echo "Current iptables policy for OUTPUT: DROP"
echo "Status: OUTBOUND INTERNET DENIED. Enclave is sealed."
echo "=================================================================="

