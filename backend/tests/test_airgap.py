"""
Tests for Air-Gap Hardening and Zero-Egress Enforcement.
"""

import os
import socket
import pytest
from pathlib import Path

from backend.app.core.config import settings
from backend.app.core.network_guard import (
    assert_offline_mode,
    block_egress,
    restore_egress,
    is_egress_blocked,
    get_egress_audit_log,
    clear_egress_audit_log,
    is_allowed_host,
    ZeroEgressGuard,
    EgressBlockedError,
    AirgapViolationError,
    audit_network_guard,
)
from scripts.package_airgap import (
    verify_model_weights,
    generate_airgap_startup_scripts,
    create_sample_model_placeholders,
)


def test_offline_environment_variables():
    """Verify that mandatory offline environment variables are active."""
    assert os.environ.get("HF_HUB_OFFLINE") == "1"
    assert os.environ.get("TRANSFORMERS_OFFLINE") == "1"
    assert os.environ.get("HF_DATASETS_OFFLINE") == "1"


def test_assert_offline_mode_success():
    """Verify assert_offline_mode passes with current configuration."""
    assert assert_offline_mode() is True


def test_assert_offline_mode_detects_tampering(monkeypatch):
    """Verify assert_offline_mode raises AirgapViolationError if flags are disabled."""
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    with pytest.raises(AirgapViolationError) as exc_info:
        assert_offline_mode()
    assert "HF_HUB_OFFLINE" in str(exc_info.value)


def test_config_airgap_settings():
    """Verify settings contains AIRGAP_MODE and local model paths."""
    assert settings.AIRGAP_MODE is True
    assert settings.LOCAL_MODELS_DIR.exists()
    assert settings.OFFLINE_LLM_DIR.exists()
    assert settings.OFFLINE_EMBEDDING_DIR.exists()
    assert settings.OFFLINE_RERANKER_DIR.exists()

    # Aliases
    assert settings.LOCAL_LLM_DIR == settings.OFFLINE_LLM_DIR
    assert settings.LOCAL_EMBEDDING_DIR == settings.OFFLINE_EMBEDDING_DIR
    assert settings.LOCAL_RERANKER_DIR == settings.OFFLINE_RERANKER_DIR


def test_is_allowed_host_logic():
    """Verify host classification: loopback & container services vs internet."""
    # Loopback / local
    assert is_allowed_host("localhost") is True
    assert is_allowed_host("127.0.0.1") is True
    assert is_allowed_host("::1") is True
    assert is_allowed_host("0.0.0.0") is True
    assert is_allowed_host("host.docker.internal") is True

    # Internal docker-compose container names
    assert is_allowed_host("qdrant") is True
    assert is_allowed_host("postgres") is True
    assert is_allowed_host("vllm") is True
    assert is_allowed_host("phoenix") is True

    # External internet hosts must be blocked
    assert is_allowed_host("8.8.8.8") is False
    assert is_allowed_host("1.1.1.1") is False
    assert is_allowed_host("huggingface.co") is False
    assert is_allowed_host("api.external-cloud.com") is False
    assert is_allowed_host("google.com") is False


def test_egress_blocker_interception_and_audit():
    """Verify ZeroEgressGuard intercepts outbound socket connection and logs audit event."""
    clear_egress_audit_log()

    with ZeroEgressGuard():
        assert is_egress_blocked() is True

        # Attempt connection to public internet
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        with pytest.raises(EgressBlockedError) as exc_info:
            s.connect(("8.8.8.8", 443))
        s.close()

        assert "8.8.8.8" in str(exc_info.value)

    # Blocker should be restored after context exit
    assert is_egress_blocked() is False

    # Check audit log
    logs = get_egress_audit_log()
    assert len(logs) >= 1
    blocked_event = logs[-1]
    assert blocked_event["action"] == "BLOCKED"
    assert blocked_event["target_host"] == "8.8.8.8"
    assert blocked_event["target_port"] == 443
    assert blocked_event["allowed"] is False


def test_audit_network_guard_report():
    """Verify comprehensive diagnostic audit report structure."""
    report = audit_network_guard()
    assert report["offline_verified"] is True
    assert report["environment_variables"]["HF_HUB_OFFLINE"] == "1"
    assert report["environment_variables"]["TRANSFORMERS_OFFLINE"] == "1"
    assert report["environment_variables"]["HF_DATASETS_OFFLINE"] == "1"
    assert "total_audit_events" in report


def test_package_airgap_model_verification(tmp_path):
    """Verify packager model weights inspection and placeholder initialization."""
    models_dir = tmp_path / "models"
    create_sample_model_placeholders(models_dir)

    report = verify_model_weights(models_dir)
    assert report["all_valid"] is True
    assert "embeddings" in report["models"]
    assert "reranker" in report["models"]
    assert "llm" in report["models"]
    assert report["models"]["embeddings"]["valid"] is True
    assert report["models"]["reranker"]["valid"] is True
    assert report["models"]["llm"]["valid"] is True


def test_airgap_startup_scripts_generation(tmp_path):
    """Verify generation of run_airgap.ps1 and run_airgap.sh with airgap flags."""
    ps1, sh = generate_airgap_startup_scripts(tmp_path)
    assert ps1.exists()
    assert sh.exists()

    ps1_text = ps1.read_text(encoding="utf-8")
    assert "$env:HF_HUB_OFFLINE = \"1\"" in ps1_text
    assert "$env:AIRGAP_MODE = \"true\"" in ps1_text

    sh_text = sh.read_text(encoding="utf-8")
    assert "export HF_HUB_OFFLINE=1" in sh_text
    assert "export AIRGAP_MODE=true" in sh_text
