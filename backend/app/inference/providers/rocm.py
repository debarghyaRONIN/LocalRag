import shutil
import subprocess
from typing import Dict, Any, Optional
import httpx

from backend.app.inference.providers.base import BaseInferenceProvider
from backend.app.inference.detector.models import HardwareDetectionResult, GPUVendor
from backend.app.inference.detector.amd import AMDDetector
from backend.app.inference.registry.manager import CompatibilityRegistry


class ROCmInferenceProvider(BaseInferenceProvider):
    """
    Inference provider managing vLLM on AMD hardware with ROCm acceleration.
    Supports both CDNA Instinct accelerators and RDNA workstation/consumer GPUs with HSA overrides.
    """

    def __init__(self, registry: Optional[CompatibilityRegistry] = None):
        self.detector = AMDDetector()
        self.registry = registry or CompatibilityRegistry()
        self.container_name = "ragapp-vllm-rocm"
        self.host_port = 8001
        self.base_url = f"http://localhost:{self.host_port}/v1"

    def detect_hardware(self) -> HardwareDetectionResult:
        devices = self.detector.detect_devices()
        docker_access = self.detector.validate_docker_access()
        selected = devices[0] if devices else None

        return HardwareDetectionResult(
            os_type="linux",
            detected_devices=devices,
            selected_device=selected,
            selected_vendor=GPUVendor.AMD,
            docker_access=docker_access,
            recommended_provider="rocm",
            is_vllm_supported=bool(selected and selected.is_compatible and docker_access.rocm_container_accessible),
            status_summary=f"ROCm Provider: {selected.name if selected else 'No AMD device'} ({selected.compute_capability if selected else ''})."
        )

    def check_compatibility(self, model_name: str) -> Dict[str, Any]:
        detection = self.detect_hardware()
        if not detection.selected_device:
            return {"compatible": False, "error": "No AMD GPU detected on host."}

        return self.registry.get_runtime_for_device(detection.selected_device, model_name)

    def get_runtime_config(self, model_name: str) -> Dict[str, Any]:
        return self.check_compatibility(model_name)

    async def start(self, model_name: str) -> Dict[str, Any]:
        config = self.get_runtime_config(model_name)
        if not config.get("compatible"):
            return {"status": "error", "error": config.get("error", "AMD hardware incompatible.")}

        docker_bin = shutil.which("docker")
        if not docker_bin:
            return {"status": "error", "error": "Docker not installed or not found on PATH."}

        # Check if already running
        h = await self.health()
        if h.get("online"):
            return {"status": "already_running", "endpoint": self.base_url, "model": model_name}

        # Clean existing container
        subprocess.run([docker_bin, "rm", "-f", self.container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        cmd = [
            docker_bin, "run", "-d",
            "--name", self.container_name,
            "--restart", "unless-stopped",
            "--ipc", "host",
            "--shm-size", "16g",
            "--device", "/dev/kfd",
            "--device", "/dev/dri",
            "--group-add", "video",
            "--group-add", "render",
            "--security-opt", "seccomp=unconfined",
            "-v", "huggingface_data:/root/.cache/huggingface",
            "-p", f"{self.host_port}:8000"
        ]

        # Pass HSA environment overrides if needed (e.g. for RDNA 3 RX 7900 cards)
        for env_k, env_v in config.get("environment", {}).items():
            cmd.extend(["-e", f"{env_k}={env_v}"])

        cmd.append(config["image"])
        cmd.extend(config["command"].split())

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return {
                "status": "started",
                "container_id": res.stdout.strip()[:12],
                "endpoint": self.base_url,
                "model": model_name,
                "rocm_environment": config.get("environment", {}),
            }
        except subprocess.CalledProcessError as e:
            return {"status": "error", "error": f"Failed to start ROCm container: {e.stderr}"}

    async def stop(self) -> Dict[str, Any]:
        docker_bin = shutil.which("docker")
        if not docker_bin:
            return {"status": "error", "error": "Docker not found."}

        try:
            subprocess.run([docker_bin, "stop", self.container_name], capture_output=True, text=True)
            subprocess.run([docker_bin, "rm", "-f", self.container_name], capture_output=True, text=True)
            return {"status": "stopped", "container_name": self.container_name}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def health(self) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(f"{self.base_url}/models")
                if res.status_code == 200:
                    models = [m.get("id") for m in res.json().get("data", [])]
                    return {
                        "online": True,
                        "provider": "rocm",
                        "active_models": models,
                        "endpoint": self.base_url,
                    }
        except Exception:
            pass

        return {"online": False, "provider": "rocm", "endpoint": self.base_url}

    async def logs(self, tail: int = 100) -> str:
        docker_bin = shutil.which("docker")
        if not docker_bin:
            return "Docker not available."
        try:
            res = subprocess.run([docker_bin, "logs", "--tail", str(tail), self.container_name], capture_output=True, text=True)
            return res.stdout + res.stderr
        except Exception as e:
            return f"Error reading logs: {str(e)}"

