"""
Air-Gap Hardening and Zero-Egress Network Guard for Ragapp.

Enforces zero-egress policy by:
1. Setting offline environment variables for Hugging Face Hub, Transformers, and Datasets.
2. Providing assert_offline_mode() to verify airgap compliance.
3. Implementing socket-level outbound connection interceptor and audit logging
   that blocks external network egress while permitting local IPC / loopback communication
   (FastAPI, vLLM, Qdrant, Postgres, Phoenix).
"""

import os
import sys
import socket
import logging
import inspect
import ipaddress
import threading
from typing import Optional, Set, List, Dict, Any, Tuple, Union, Iterable
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# 1. Enforce Hugging Face Offline Environment Variables
# ---------------------------------------------------------------------------
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"

logger = logging.getLogger("ragapp.network_guard")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------
class EgressBlockedError(PermissionError, RuntimeError):
    """Raised when an outbound socket connection is blocked in air-gapped mode."""
    def __init__(self, host: str, port: Union[int, str] = 0, reason: str = "Zero-egress policy violation"):
        self.host = host
        self.port = port
        self.reason = reason
        super().__init__(f"Zero-egress violation: connection to '{host}:{port}' blocked ({reason})")


class AirgapViolationError(RuntimeError):
    """Raised when air-gap offline configuration or environment is violated."""
    pass


# ---------------------------------------------------------------------------
# Audit State & Helpers
# ---------------------------------------------------------------------------
_audit_log: List[Dict[str, Any]] = []
_audit_lock = threading.Lock()

_original_socket_connect = socket.socket.connect
_original_socket_connect_ex = socket.socket.connect_ex
_original_create_connection = socket.create_connection
_original_getaddrinfo = socket.getaddrinfo

_is_guard_active: bool = False
_active_allowed_hosts: Set[str] = set()
_allow_loopback_active: bool = True


def _record_audit_event(
    action: str,
    target_host: str,
    target_port: Union[int, str],
    allowed: bool,
    reason: str,
    protocol: str = "TCP",
) -> Dict[str, Any]:
    caller_frame = inspect.currentframe()
    caller_info = "unknown"
    try:
        if caller_frame and caller_frame.f_back and caller_frame.f_back.f_back:
            frame = caller_frame.f_back.f_back
            caller_info = f"{frame.f_code.co_filename}:{frame.f_lineno} in {frame.f_code.co_name}"
    except Exception:
        pass

    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "target_host": str(target_host),
        "target_port": target_port,
        "protocol": protocol,
        "allowed": allowed,
        "reason": reason,
        "caller": caller_info,
    }

    with _audit_lock:
        _audit_log.append(event)

    if allowed:
        logger.debug(f"[NetworkGuard] ALLOWED: {target_host}:{target_port} ({reason})")
    else:
        logger.warning(f"[NetworkGuard] BLOCKED: {target_host}:{target_port} ({reason})")

    return event


def is_allowed_host(
    host: str,
    allow_loopback: bool = True,
    custom_allowed: Optional[Iterable[str]] = None,
) -> bool:
    """
    Determines whether a target hostname or IP address is permitted in air-gapped mode.
    Loopback addresses and local container service names are permitted by default.
    Public IP addresses and external internet domain names are blocked.
    """
    if not host:
        return True

    host_clean = str(host).strip().strip("[]").lower()

    if custom_allowed and host_clean in {str(h).lower() for h in custom_allowed}:
        return True

    # Standard loopback and local hostnames
    if allow_loopback:
        if host_clean in {
            "localhost",
            "127.0.0.1",
            "::1",
            "0.0.0.0",
            "::",
            "host.docker.internal",
            "local",
        }:
            return True

        # Check IP address loopback / unspecified
        try:
            ip = ipaddress.ip_address(host_clean)
            if ip.is_loopback or ip.is_unspecified:
                return True
        except ValueError:
            pass

        # Internal container service names (e.g. 'qdrant', 'postgres', 'vllm', 'phoenix')
        # Service names in standard docker-compose networks do not contain dots.
        if "." not in host_clean:
            return True

    return False


def _extract_host_port(address: Any) -> Tuple[str, Union[int, str]]:
    """Extract (host, port) safely from socket address argument."""
    if isinstance(address, tuple):
        host = address[0] if len(address) > 0 else ""
        port = address[1] if len(address) > 1 else 0
        return str(host), port
    elif isinstance(address, (str, bytes)):
        # AF_UNIX domain socket
        return str(address), 0
    return str(address), 0


# ---------------------------------------------------------------------------
# Socket Interceptor Implementations
# ---------------------------------------------------------------------------
def _guarded_connect(self, address):
    host, port = _extract_host_port(address)

    # AF_UNIX sockets are local IPC
    if isinstance(address, (str, bytes)):
        return _original_socket_connect(self, address)

    if not is_allowed_host(host, _allow_loopback_active, _active_allowed_hosts):
        _record_audit_event(
            action="BLOCKED",
            target_host=host,
            target_port=port,
            allowed=False,
            reason="Outbound internet connection blocked by air-gap zero-egress guard",
        )
        raise EgressBlockedError(host, port, "Outbound internet egress blocked")

    _record_audit_event(
        action="ALLOWED",
        target_host=host,
        target_port=port,
        allowed=True,
        reason="Local loopback / internal service connection permitted",
    )
    return _original_socket_connect(self, address)


def _guarded_connect_ex(self, address):
    host, port = _extract_host_port(address)

    if isinstance(address, (str, bytes)):
        return _original_socket_connect_ex(self, address)

    if not is_allowed_host(host, _allow_loopback_active, _active_allowed_hosts):
        _record_audit_event(
            action="BLOCKED",
            target_host=host,
            target_port=port,
            allowed=False,
            reason="Outbound internet connection blocked by air-gap zero-egress guard",
        )
        raise EgressBlockedError(host, port, "Outbound internet egress blocked")

    _record_audit_event(
        action="ALLOWED",
        target_host=host,
        target_port=port,
        allowed=True,
        reason="Local loopback / internal service connection permitted",
    )
    return _original_socket_connect_ex(self, address)


def _guarded_create_connection(address, *args, **kwargs):
    host, port = _extract_host_port(address)

    if not is_allowed_host(host, _allow_loopback_active, _active_allowed_hosts):
        _record_audit_event(
            action="BLOCKED",
            target_host=host,
            target_port=port,
            allowed=False,
            reason="Outbound socket creation blocked by air-gap zero-egress guard",
        )
        raise EgressBlockedError(host, port, "Outbound internet egress blocked")

    return _original_create_connection(address, *args, **kwargs)


def _guarded_getaddrinfo(host, port, *args, **kwargs):
    if host is not None:
        host_str = str(host)
        if not is_allowed_host(host_str, _allow_loopback_active, _active_allowed_hosts):
            _record_audit_event(
                action="BLOCKED_DNS",
                target_host=host_str,
                target_port=port or 0,
                allowed=False,
                reason="External DNS resolution blocked in air-gap mode",
            )
            raise EgressBlockedError(host_str, port or 0, "External DNS resolution blocked")

    return _original_getaddrinfo(host, port, *args, **kwargs)


# ---------------------------------------------------------------------------
# Public Guard Management Functions
# ---------------------------------------------------------------------------
def block_egress(
    allow_loopback: bool = True,
    custom_allowed_hosts: Optional[Iterable[str]] = None,
    block_dns: bool = True,
) -> None:
    """
    Activates the zero-egress socket blocker across standard Python networking modules.
    Monkeypatches socket.socket.connect, connect_ex, create_connection, and getaddrinfo.
    """
    global _is_guard_active, _allow_loopback_active, _active_allowed_hosts

    _allow_loopback_active = allow_loopback
    _active_allowed_hosts = set(custom_allowed_hosts or [])

    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex
    socket.create_connection = _guarded_create_connection
    if block_dns:
        socket.getaddrinfo = _guarded_getaddrinfo

    _is_guard_active = True
    logger.info("Zero-egress socket blocker enabled (airgap enforcement active).")


def restore_egress() -> None:
    """
    Restores original socket networking methods, disabling the egress blocker.
    """
    global _is_guard_active

    socket.socket.connect = _original_socket_connect
    socket.socket.connect_ex = _original_socket_connect_ex
    socket.create_connection = _original_create_connection
    socket.getaddrinfo = _original_getaddrinfo

    _is_guard_active = False
    logger.info("Zero-egress socket blocker disabled (original networking restored).")


def is_egress_blocked() -> bool:
    """Returns True if the zero-egress blocker is currently installed and active."""
    return _is_guard_active


def get_egress_audit_log() -> List[Dict[str, Any]]:
    """Returns a shallow copy of the zero-egress audit log entries."""
    with _audit_lock:
        return list(_audit_log)


# Public aliases
activate_network_guard = block_egress
deactivate_network_guard = restore_egress
is_guard_active = is_egress_blocked
get_audit_log = get_egress_audit_log


def clear_egress_audit_log() -> None:
    """Clears the zero-egress audit log entries."""
    with _audit_lock:
        _audit_log.clear()


class ZeroEgressGuard:
    """
    Context manager to enforce zero-egress inside a with block:
    Example:
        with ZeroEgressGuard():
            # Outbound calls to external APIs will raise EgressBlockedError
            do_local_rag_work()
    """
    def __init__(
        self,
        allow_loopback: bool = True,
        custom_allowed_hosts: Optional[Iterable[str]] = None,
        block_dns: bool = True,
    ):
        self.allow_loopback = allow_loopback
        self.custom_allowed_hosts = custom_allowed_hosts
        self.block_dns = block_dns

    def __enter__(self):
        block_egress(
            allow_loopback=self.allow_loopback,
            custom_allowed_hosts=self.custom_allowed_hosts,
            block_dns=self.block_dns,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        restore_egress()


# ---------------------------------------------------------------------------
# Offline Compliance Assertion
# ---------------------------------------------------------------------------
def assert_offline_mode() -> bool:
    """
    Asserts that offline mode is strictly configured:
    - Environment variables HF_HUB_OFFLINE, TRANSFORMERS_OFFLINE, HF_DATASETS_OFFLINE must be '1'.
    - If backend.app.core.config.settings is present, settings.AIRGAP_MODE must be True.
    Raises AirgapViolationError on any non-compliance.
    """
    expected_vars = {
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
    }
    violations = []

    for var_name, expected_val in expected_vars.items():
        actual_val = os.environ.get(var_name)
        if actual_val != expected_val:
            violations.append(f"{var_name} must be '{expected_val}', found '{actual_val}'")

    try:
        from backend.app.core.config import settings
        if not getattr(settings, "AIRGAP_MODE", False):
            violations.append("settings.AIRGAP_MODE must be True")
    except Exception:
        # Settings might not be loaded or another config used
        pass

    if violations:
        error_msg = "Air-gap offline mode compliance check failed:\n" + "\n".join(f" - {v}" for v in violations)
        logger.error(error_msg)
        raise AirgapViolationError(error_msg)

    logger.info("Air-gap offline mode verified: all offline flags and configurations active.")
    return True


def audit_network_guard() -> Dict[str, Any]:
    """
    Generates a comprehensive diagnostic report of the network guard status,
    including offline environment flags, blocker status, and connection audit metrics.
    """
    logs = get_egress_audit_log()
    blocked_count = sum(1 for e in logs if not e.get("allowed", False))
    allowed_count = sum(1 for e in logs if e.get("allowed", False))

    status = {
        "offline_verified": False,
        "environment_variables": {
            "HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE"),
            "TRANSFORMERS_OFFLINE": os.environ.get("TRANSFORMERS_OFFLINE"),
            "HF_DATASETS_OFFLINE": os.environ.get("HF_DATASETS_OFFLINE"),
        },
        "egress_blocker_active": _is_guard_active,
        "allow_loopback": _allow_loopback_active,
        "total_audit_events": len(logs),
        "blocked_events_count": blocked_count,
        "allowed_events_count": allowed_count,
        "recent_audit_events": logs[-10:] if logs else [],
    }

    try:
        assert_offline_mode()
        status["offline_verified"] = True
    except AirgapViolationError as err:
        status["offline_verified"] = False
        status["error"] = str(err)

    return status
