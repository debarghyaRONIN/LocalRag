#!/usr/bin/env python3
"""
Standalone Offline Packager for Ragapp Air-Gap Deployment.

This script:
1. Verifies local model weights (Embeddings, Reranker, and LLM).
2. Generates weights manifests with SHA-256 checksums and file sizes.
3. Exports docker images to standalone tar archives for air-gapped container hosts.
4. Generates production offline startup scripts (run_airgap.ps1 and run_airgap.sh).
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

# Base repository root
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

# Default directories
DEFAULT_MODELS_DIR = REPO_ROOT / "models"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "airgap_bundle"

# Required Docker images for air-gapped orchestration
REQUIRED_DOCKER_IMAGES = [
    "qdrant/qdrant:v1.12.1",
    "postgres:16-alpine",
    "vllm/vllm-openai:latest",
    "arizephoenix/phoenix:latest",
]

# Expected model directories & key signature files
MODEL_TARGETS = {
    "embeddings": {
        "name": "BAAI/bge-small-en-v1.5",
        "relative_dir": "embeddings",
        "key_files": ["model.onnx", "model_quantized.onnx", "tokenizer.json", "config.json"],
        "min_files": 1,
    },
    "reranker": {
        "name": "BAAI/bge-reranker-base",
        "relative_dir": "reranker",
        "key_files": ["model.onnx", "model_quantized.onnx", "tokenizer.json", "config.json"],
        "min_files": 1,
    },
    "llm": {
        "name": "Qwen/Qwen2.5-3B-Instruct",
        "relative_dir": "llm",
        "key_files": [
            "config.json",
            "model.safetensors",
            "model-00001-of-00002.safetensors",
            "model.gguf",
            "pytorch_model.bin",
        ],
        "min_files": 1,
    },
}


def calculate_sha256(file_path: Path, chunk_size: int = 65536) -> str:
    """Computes SHA-256 hash for a given file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            data = f.read(chunk_size)
            if not data:
                break
            hasher.update(data)
    return hasher.hexdigest()


def verify_model_weights(models_dir: Path, compute_hashes: bool = False) -> Dict[str, Any]:
    """
    Verifies the presence and integrity of local model weights in models_dir.
    Returns a comprehensive status report.
    """
    models_dir = Path(models_dir).resolve()
    report: Dict[str, Any] = {
        "models_dir": str(models_dir),
        "exists": models_dir.exists(),
        "all_valid": True,
        "models": {},
    }

    if not models_dir.exists():
        report["all_valid"] = False
        report["error"] = f"Models directory '{models_dir}' does not exist."
        return report

    for key, spec in MODEL_TARGETS.items():
        target_dir = models_dir / spec["relative_dir"]
        model_info: Dict[str, Any] = {
            "name": spec["name"],
            "directory": str(target_dir),
            "directory_exists": target_dir.exists(),
            "valid": False,
            "present_files": [],
            "missing_key_files": [],
            "total_bytes": 0,
            "total_mb": 0.0,
        }

        if not target_dir.exists():
            model_info["error"] = f"Directory not found: {target_dir}"
            report["models"][key] = model_info
            report["all_valid"] = False
            continue

        all_files = [p for p in target_dir.rglob("*") if p.is_file()]
        total_size = sum(f.stat().st_size for f in all_files)
        model_info["total_bytes"] = total_size
        model_info["total_mb"] = round(total_size / (1024 * 1024), 2)

        file_names = {f.name for f in all_files}

        # Check for matching key files or weights
        matched_keys = [kf for kf in spec["key_files"] if kf in file_names]
        # Also check for any .onnx, .safetensors, .bin, .gguf files
        weight_extensions = {".onnx", ".safetensors", ".bin", ".gguf"}
        has_weight_file = any(f.suffix.lower() in weight_extensions for f in all_files)

        is_valid = (len(all_files) >= spec["min_files"]) and (len(matched_keys) > 0 or has_weight_file)
        model_info["valid"] = is_valid
        if not is_valid:
            report["all_valid"] = False

        for f in all_files:
            file_record: Dict[str, Any] = {
                "name": f.name,
                "relative_path": str(f.relative_to(target_dir)),
                "size_bytes": f.stat().st_size,
            }
            if compute_hashes:
                file_record["sha256"] = calculate_sha256(f)
            model_info["present_files"].append(file_record)

        report["models"][key] = model_info

    return report


def check_docker_available() -> Tuple[bool, str]:
    """Checks if the Docker CLI and daemon are operational."""
    try:
        res = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        if res.returncode == 0:
            return True, "Docker daemon is active."
        return False, f"Docker command failed with code {res.returncode}: {res.stderr.strip()}"
    except Exception as e:
        return False, f"Docker is not available: {str(e)}"


def get_local_docker_images() -> List[str]:
    """Returns a list of local docker image repositories/tags."""
    try:
        res = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        if res.returncode == 0:
            return [line.strip() for line in res.stdout.splitlines() if line.strip()]
    except Exception:
        pass
    return []


def export_docker_images(
    output_dir: Path,
    images: Optional[List[str]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Exports required Docker images to tar files in output_dir/docker_images.
    """
    images_to_export = images or REQUIRED_DOCKER_IMAGES
    dest_dir = Path(output_dir) / "docker_images"
    dest_dir.mkdir(parents=True, exist_ok=True)

    docker_ok, docker_msg = check_docker_available()
    local_images = get_local_docker_images() if docker_ok else []

    export_report: Dict[str, Any] = {
        "output_directory": str(dest_dir),
        "docker_available": docker_ok,
        "docker_status": docker_msg,
        "exported_images": [],
        "missing_local_images": [],
        "failed_exports": [],
    }

    for img in images_to_export:
        clean_name = img.replace("/", "_").replace(":", "_") + ".tar"
        tar_path = dest_dir / clean_name

        img_available = any(img in li or li.startswith(img) for li in local_images)

        record: Dict[str, Any] = {
            "image": img,
            "tar_file": str(tar_path),
            "archive_name": clean_name,
            "locally_present": img_available,
            "status": "pending",
        }

        if not docker_ok:
            record["status"] = "skipped (docker unavailable)"
            export_report["missing_local_images"].append(record)
            continue

        if not img_available:
            record["status"] = "skipped (image not pulled locally)"
            export_report["missing_local_images"].append(record)
            continue

        if dry_run:
            record["status"] = "dry_run (ready to export)"
            export_report["exported_images"].append(record)
            continue

        # Perform actual docker save
        print(f"[PackageAirgap] Exporting docker image: {img} -> {clean_name} ...")
        try:
            cmd = ["docker", "save", img, "-o", str(tar_path)]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=600)
            if res.returncode == 0 and tar_path.exists():
                record["status"] = "exported"
                record["size_bytes"] = tar_path.stat().st_size
                record["size_mb"] = round(tar_path.stat().st_size / (1024 * 1024), 2)
                export_report["exported_images"].append(record)
            else:
                record["status"] = f"failed: {res.stderr.strip()}"
                export_report["failed_exports"].append(record)
        except Exception as e:
            record["status"] = f"exception: {str(e)}"
            export_report["failed_exports"].append(record)

    # Save manifest
    manifest_path = dest_dir / "images_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(export_report, f, indent=2)

    return export_report


def generate_airgap_startup_scripts(target_dir: Path) -> Tuple[Path, Path]:
    """
    Generates run_airgap.ps1 (PowerShell) and run_airgap.sh (Bash)
    startup scripts for air-gapped environments.
    """
    target_dir = Path(target_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    # 1. PowerShell Script (run_airgap.ps1)
    ps1_content = """# ==============================================================================
# Ragapp Air-Gap Production Startup Script (PowerShell / Windows)
# Zero-Egress Offline Mode Enforcement
# ==============================================================================
param (
    [Parameter(Position=0)]
    [ValidateSet("start", "dev", "verify", "load-images", "docker-up", "docker-down")]
    [string]$Command = "start",

    [string]$HostIP = "0.0.0.0",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$SCRIPT_ROOT = $PSScriptRoot
$MODELS_DIR = Join-Path $SCRIPT_ROOT "models"
$IMAGES_DIR = Join-Path $SCRIPT_ROOT "docker_images"

# ------------------------------------------------------------------------------
# 1. Enforce Air-Gap / Zero-Egress Environment Flags
# ------------------------------------------------------------------------------
Write-Host "🛡️  Enforcing Zero-Egress Air-Gap Environment Variables..." -ForegroundColor Cyan
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:HF_DATASETS_OFFLINE = "1"
$env:AIRGAP_MODE = "true"
$env:DISABLE_TELEMETRY = "1"
$env:DO_NOT_TRACK = "1"

# Redirect model cache directories to local air-gapped models
$env:HF_HOME = $MODELS_DIR
$env:TRANSFORMERS_CACHE = $MODELS_DIR
$env:FASTEMBED_CACHE_PATH = Join-Path $MODELS_DIR "embeddings"

Write-Host "   HF_HUB_OFFLINE        = $env:HF_HUB_OFFLINE" -ForegroundColor DarkGray
$PythonCmd = if ($env:CONDA_PREFIX -and (Test-Path "$env:CONDA_PREFIX\\python.exe")) {
    "$env:CONDA_PREFIX\\python.exe"
} elseif (Test-Path "$env:USERPROFILE\\miniconda3\\envs\\ragapp\\python.exe") {
    "$env:USERPROFILE\\miniconda3\\envs\\ragapp\\python.exe"
} elseif (Test-Path "$env:USERPROFILE\\anaconda3\\envs\\ragapp\\python.exe") {
    "$env:USERPROFILE\\anaconda3\\envs\\ragapp\\python.exe"
} else {
    "python"
}

# ------------------------------------------------------------------------------
# 2. Command Execution
# ------------------------------------------------------------------------------
switch ($Command) {
    "verify" {
        Write-Host "🔍 Running Airgap Offline Preflight Verification..." -ForegroundColor Cyan
        & $PythonCmd -c "from backend.app.core.network_guard import assert_offline_mode, audit_network_guard; assert_offline_mode(); print('✅ Air-gap offline verification successful:', audit_network_guard())"
    }

    "load-images" {
        Write-Host "📦 Loading offline Docker tar images from $IMAGES_DIR..." -ForegroundColor Cyan
        if (Test-Path $IMAGES_DIR) {
            Get-ChildItem -Path $IMAGES_DIR -Filter "*.tar" | ForEach-Object {
                Write-Host "   Loading: $($_.Name)..." -ForegroundColor Yellow
                docker load -i $_.FullName
            }
            Write-Host "✅ All offline Docker images loaded." -ForegroundColor Green
        } else {
            Write-Warning "No docker_images directory found at $IMAGES_DIR."
        }
    }

    "docker-up" {
        Write-Host "🐳 Launching local container infrastructure in offline mode..." -ForegroundColor Cyan
        Set-Location $SCRIPT_ROOT
        docker compose up -d
        Write-Host "✅ Offline services running (Qdrant, Postgres, Phoenix, vLLM)." -ForegroundColor Green
    }

    "docker-down" {
        Write-Host "🛑 Stopping offline containers..." -ForegroundColor Cyan
        Set-Location $SCRIPT_ROOT
        docker compose down
    }

    "dev" {
        Write-Host "🚀 Launching Ragapp in Air-Gapped Development Mode..." -ForegroundColor Green
        Set-Location $SCRIPT_ROOT
        & $PythonCmd -m uvicorn backend.app.main:app --host $HostIP --port $Port --reload
    }

    "start" {
        Write-Host "⚡ Launching Ragapp Air-Gapped Production Server on http://${HostIP}:${Port}..." -ForegroundColor Green
        Set-Location $SCRIPT_ROOT
        & $PythonCmd -m uvicorn backend.app.main:app --host $HostIP --port $Port
    }
}
"""

    # 2. POSIX Bash Script (run_airgap.sh)
    sh_content = """#!/usr/bin/env bash
# ==============================================================================
# Ragapp Air-Gap Production Startup Script (POSIX Bash / Linux)
# Zero-Egress Offline Mode Enforcement
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMAND="${1:-start}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

MODELS_DIR="${SCRIPT_DIR}/models"
IMAGES_DIR="${SCRIPT_DIR}/docker_images"

# ------------------------------------------------------------------------------
# 1. Enforce Air-Gap / Zero-Egress Environment Flags
# ------------------------------------------------------------------------------
echo "🛡️  Enforcing Zero-Egress Air-Gap Environment Variables..."
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_DATASETS_OFFLINE=1
export AIRGAP_MODE=true
export DISABLE_TELEMETRY=1
export DO_NOT_TRACK=1

# Local model paths
export HF_HOME="${MODELS_DIR}"
export TRANSFORMERS_CACHE="${MODELS_DIR}"
export FASTEMBED_CACHE_PATH="${MODELS_DIR}/embeddings"

PYTHON_BIN="$(which python3 || which python || echo "python3")"

# ------------------------------------------------------------------------------
# 2. Command Execution
# ------------------------------------------------------------------------------
case "${COMMAND}" in
    verify)
        echo "🔍 Running Airgap Offline Preflight Verification..."
        "${PYTHON_BIN}" -c "from backend.app.core.network_guard import assert_offline_mode, audit_network_guard; assert_offline_mode(); print('✅ Air-gap offline verification successful:', audit_network_guard())"
        ;;
    load-images)
        echo "📦 Loading offline Docker tar images from ${IMAGES_DIR}..."
        if [ -d "${IMAGES_DIR}" ]; then
            for img in "${IMAGES_DIR}"/*.tar; do
                if [ -f "${img}" ]; then
                    echo "   Loading: $(basename "${img}")..."
                    docker load -i "${img}"
                fi
            done
            echo "✅ All offline Docker images loaded."
        else
            echo "⚠️  No docker_images directory found at ${IMAGES_DIR}."
        fi
        ;;
    docker-up)
        echo "🐳 Launching local container infrastructure in offline mode..."
        cd "${SCRIPT_DIR}"
        docker compose up -d
        echo "✅ Offline services running (Qdrant, Postgres, Phoenix, vLLM)."
        ;;
    docker-down)
        echo "🛑 Stopping offline containers..."
        cd "${SCRIPT_DIR}"
        docker compose down
        ;;
    dev)
        echo "🚀 Launching Ragapp in Air-Gapped Development Mode..."
        cd "${SCRIPT_DIR}"
        exec "${PYTHON_BIN}" -m uvicorn backend.app.main:app --host "${HOST}" --port "${PORT}" --reload
        ;;
    start)
        echo "⚡ Launching Ragapp Air-Gapped Production Server on http://${HOST}:${PORT}..."
        cd "${SCRIPT_DIR}"
        exec "${PYTHON_BIN}" -m uvicorn backend.app.main:app --host "${HOST}" --port "${PORT}"
        ;;
    *)
        echo "Usage: $0 {start|dev|verify|load-images|docker-up|docker-down}"
        exit 1
        ;;
esac
"""

    ps1_path = target_dir / "run_airgap.ps1"
    sh_path = target_dir / "run_airgap.sh"

    with open(ps1_path, "w", encoding="utf-8") as f:
        f.write(ps1_content)

    with open(sh_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(sh_content)

    try:
        # Make bash script executable if on Unix
        os.chmod(sh_path, 0o755)
    except Exception:
        pass

    return ps1_path, sh_path


def create_sample_model_placeholders(models_dir: Path) -> None:
    """
    Creates lightweight placeholder files for testing environments
    where offline weights are mocked or stubbed.
    """
    models_dir = Path(models_dir).resolve()

    # 1. Embeddings model
    emb_dir = models_dir / "embeddings"
    emb_dir.mkdir(parents=True, exist_ok=True)
    (emb_dir / "config.json").write_text(json.dumps({"model_type": "bge-small-en-v1.5", "dim": 384}, indent=2), encoding="utf-8")
    (emb_dir / "tokenizer.json").write_text(json.dumps({"version": "1.0", "vocab_size": 30522}, indent=2), encoding="utf-8")
    if not (emb_dir / "model.onnx").exists():
        (emb_dir / "model.onnx").write_bytes(b"ONNX_MOCK_EMBEDDING_MODEL_WEIGHTS")

    # 2. Reranker model
    rerank_dir = models_dir / "reranker"
    rerank_dir.mkdir(parents=True, exist_ok=True)
    (rerank_dir / "config.json").write_text(json.dumps({"model_type": "bge-reranker-base"}, indent=2), encoding="utf-8")
    (rerank_dir / "tokenizer.json").write_text(json.dumps({"version": "1.0", "vocab_size": 30522}, indent=2), encoding="utf-8")
    if not (rerank_dir / "model.onnx").exists():
        (rerank_dir / "model.onnx").write_bytes(b"ONNX_MOCK_RERANKER_MODEL_WEIGHTS")

    # 3. LLM model
    llm_dir = models_dir / "llm"
    llm_dir.mkdir(parents=True, exist_ok=True)
    (llm_dir / "config.json").write_text(json.dumps({"architectures": ["Qwen2ForCausalLM"], "model_type": "qwen2"}, indent=2), encoding="utf-8")
    (llm_dir / "tokenizer.json").write_text(json.dumps({"version": "1.0"}, indent=2), encoding="utf-8")
    if not (llm_dir / "model.safetensors").exists():
        (llm_dir / "model.safetensors").write_bytes(b"SAFETENSORS_MOCK_LLM_WEIGHTS")

    print(f"[PackageAirgap] Model placeholders initialized in: {models_dir}")


def main():
    parser = argparse.ArgumentParser(description="Ragapp Standalone Air-Gap Packager and Verifier")
    parser.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR, help="Path to local models directory")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Path for airgap bundle output")
    parser.add_argument("--verify-only", action="store_true", help="Only verify model weights and exit")
    parser.add_argument("--generate-scripts-only", action="store_true", help="Only generate run_airgap scripts")
    parser.add_argument("--skip-docker", action="store_true", help="Skip Docker image export")
    parser.add_argument("--create-placeholders", action="store_true", help="Create model weight placeholders if missing")
    parser.add_argument("--compute-hashes", action="store_true", help="Compute SHA-256 for all model files")
    args = parser.parse_args()

    print("=" * 70)
    print("🚀  Ragapp Air-Gap Packager & Zero-Egress Tool")
    print("=" * 70)

    # 1. Placeholders if requested
    if args.create_placeholders:
        create_sample_model_placeholders(args.models_dir)

    # 2. Generate Startup Scripts (always generate in REPO_ROOT and optionally output_dir)
    print("\n📝 Generating Offline Startup Scripts...")
    ps1_root, sh_root = generate_airgap_startup_scripts(REPO_ROOT)
    print(f"   Created: {ps1_root}")
    print(f"   Created: {sh_root}")

    if args.generate_scripts_only:
        print("\n✅ Script generation complete.")
        return 0

    # 3. Verify Model Weights
    print(f"\n🔍 Verifying Model Weights in: {args.models_dir}...")
    weights_report = verify_model_weights(args.models_dir, compute_hashes=args.compute_hashes)

    for m_key, m_spec in weights_report.get("models", {}).items():
        status = "✅ VALID" if m_spec.get("valid") else "⚠️  MISSING / INCOMPLETE"
        print(f"   - [{m_key.upper()}]: {m_spec.get('name')} -> {status} ({m_spec.get('total_mb', 0)} MB, {len(m_spec.get('present_files', []))} files)")

    if args.verify_only:
        print("\nVerification status:", "PASSED" if weights_report["all_valid"] else "INCOMPLETE")
        return 0 if weights_report["all_valid"] else 1

    # 4. Export Docker Images
    if not args.skip_docker:
        print(f"\n🐳 Exporting Docker Images to bundle...")
        docker_report = export_docker_images(args.output_dir, dry_run=False)
        print(f"   Docker Status: {docker_report.get('docker_status')}")
        print(f"   Exported Images: {len(docker_report.get('exported_images', []))}")
        print(f"   Missing/Skipped: {len(docker_report.get('missing_local_images', []))}")
    else:
        print("\n⏩ Skipping Docker export (--skip-docker requested).")

    # 5. Generate package bundle artifacts
    args.output_dir.mkdir(parents=True, exist_ok=True)
    generate_airgap_startup_scripts(args.output_dir)

    # Write summary manifest
    bundle_manifest = {
        "packager_version": "1.0.0",
        "airgap_mode": True,
        "models_verification": weights_report,
        "required_images": REQUIRED_DOCKER_IMAGES,
    }
    with open(args.output_dir / "airgap_manifest.json", "w", encoding="utf-8") as f:
        json.dump(bundle_manifest, f, indent=2)

    print(f"\n🎉 Airgap package bundle generated at: {args.output_dir}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
