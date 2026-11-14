import shutil
import subprocess
from typing import Dict, Any, Optional
import httpx

from backend.app.inference.providers.base import BaseInferenceProvider
from backend.app.inference.detector.models import HardwareDetectionResult, GPUVendor
from backend.app.inference.detector.nvidia import NvidiaDetector
from backend.app.inference.registry.manager import CompatibilityRegistry


class CUDAInferenceProvider(BaseInferenceProvider):
    """
    Inference provider managing vLLM on NVIDIA hardware with CUDA acceleration.
    """

    def __init__(self, registry: Optional[CompatibilityRegistry] = None):
        self.detector = NvidiaDetector()
        self.registry = registry or CompatibilityRegistry()
        self.container_name = "ragapp-vllm"
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
            selected_vendor=GPUVendor.NVIDIA,
            docker_access=docker_access,
            recommended_provider="cuda",
            is_vllm_supported=bool(selected and selected.is_compatible and docker_access.nvidia_container_accessible),
            status_summary=f"CUDA Provider: {selected.name if selected else 'No NVIDIA device'} with {selected.vram_total_mb if selected else 0} MB VRAM."
        )

    def check_compatibility(self, model_name: str) -> Dict[str, Any]:
        detection = self.detect_hardware()
        if not detection.selected_device:
            return {"compatible": False, "error": "No NVIDIA GPU detected on host."}

        return self.registry.get_runtime_for_device(detection.selected_device, model_name)

    def get_runtime_config(self, model_name: str) -> Dict[str, Any]:
        return self.check_compatibility(model_name)

    async def start(self, model_name: str) -> Dict[str, Any]:
        config = self.get_runtime_config(model_name)
        if not config.get("compatible"):
            return {"status": "error", "error": config.get("error", "Hardware incompatible.")}

        docker_bin = shutil.which("docker")
        if not docker_bin:
            return {"status": "error", "error": "Docker not installed or not found on PATH."}

        # Check if already running
        h = await self.health()
        if h.get("online"):
            return {"status": "already_running", "endpoint": self.base_url, "model": model_name}

        # Remove existing stopped container if present
        subprocess.run([docker_bin, "rm", "-f", self.container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        cmd = [
            docker_bin, "run", "-d",
            "--name", self.container_name,
            "--restart", "unless-stopped",
            "--ipc", "host",
            "--gpus", "all",
            "-v", "huggingface_data:/root/.cache/huggingface",
            "-p", f"{self.host_port}:8000",
            config["image"]
        ]
        cmd.extend(config["command"].split())

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return {
                "status": "started",
                "container_id": res.stdout.strip()[:12],
                "endpoint": self.base_url,
                "model": model_name,
            }
        except subprocess.CalledProcessError as e:
            return {"status": "error", "error": f"Failed to start CUDA container: {e.stderr}"}

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
                        "provider": "cuda",
                        "active_models": models,
                        "endpoint": self.base_url,
                    }
        except Exception:
            pass

        return {"online": False, "provider": "cuda", "endpoint": self.base_url}

    async def logs(self, tail: int = 100) -> str:
        docker_bin = shutil.which("docker")
        if not docker_bin:
            return "Docker not available."
        try:
            res = subprocess.run([docker_bin, "logs", "--tail", str(tail), self.container_name], capture_output=True, text=True)
            return res.stdout + res.stderr
        except Exception as e:
            return f"Error reading logs: {str(e)}"

