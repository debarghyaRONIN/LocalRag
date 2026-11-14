from typing import Dict, Any, Optional
from backend.app.inference.providers.base import BaseInferenceProvider
from backend.app.inference.detector.models import (
    HardwareDetectionResult,
    GPUVendor,
    DockerGPUAccess,
)


class CPUInferenceProvider(BaseInferenceProvider):
    """
    Fallback inference provider when no compatible NVIDIA or AMD GPU is detected.
    Explicitly reports that vLLM CPU support is not part of the initial supported
    production deployment, fails fast, and avoids silent fallback to CPU that harms user experience.
    """

    def __init__(self):
        self.error_message = (
            "vLLM CPU execution is not supported in this production deployment. "
            "vLLM requires high-throughput hardware acceleration via NVIDIA CUDA (Pascal+) "
            "or AMD ROCm (RDNA 2/3, CDNA 1/2/3). Running large language models on unaccelerated "
            "CPU leads to excessive latency and memory thrashing."
        )

    def detect_hardware(self) -> HardwareDetectionResult:
        return HardwareDetectionResult(
            os_type="linux",
            detected_devices=[],
            selected_device=None,
            selected_vendor=GPUVendor.CPU_ONLY,
            docker_access=DockerGPUAccess(
                docker_available=True,
                nvidia_container_accessible=False,
                rocm_container_accessible=False,
                rocm_kfd_accessible=False,
                rocm_dri_accessible=False,
            ),
            recommended_provider="cpu",
            is_vllm_supported=False,
            status_summary="No compatible NVIDIA CUDA or AMD ROCm GPU detected. vLLM CPU mode is disabled.",
        )

    def check_compatibility(self, model_name: str) -> Dict[str, Any]:
        return {
            "compatible": False,
            "error": self.error_message,
            "provider": "cpu",
            "model": model_name,
            "troubleshooting": [
                "Verify NVIDIA GPU is installed and 'nvidia-smi' runs successfully.",
                "Ensure NVIDIA Container Toolkit is installed for Docker access.",
                "Verify AMD GPU is installed and 'rocminfo' / 'rocm-smi' runs successfully.",
                "Ensure user has permissions to /dev/kfd and /dev/dri (render/video groups).",
            ],
        }

    def get_runtime_config(self, model_name: str) -> Dict[str, Any]:
        return self.check_compatibility(model_name)

    async def start(self, model_name: str) -> Dict[str, Any]:
        return {
            "status": "error",
            "provider": "cpu",
            "error": self.error_message,
            "action": "blocked",
        }

    async def stop(self) -> Dict[str, Any]:
        return {
            "status": "noop",
            "provider": "cpu",
            "message": "No CPU inference container is running.",
        }

    async def health(self) -> Dict[str, Any]:
        return {
            "online": False,
            "provider": "cpu",
            "status": "unsupported",
            "error": self.error_message,
        }

    async def logs(self, tail: int = 100) -> str:
        return (
            "[CPU Provider Diagnostic]\n"
            f"ERROR: {self.error_message}\n"
            "Action Required: Provision an NVIDIA (CUDA 12+) or AMD (ROCm 6+) accelerator."
        )
