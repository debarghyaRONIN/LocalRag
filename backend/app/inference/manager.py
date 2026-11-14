import logging
from typing import Dict, Any, Optional, List
from backend.app.core.config import settings
from backend.app.inference.detector.linux import SystemGPUDetector
from backend.app.inference.detector.models import HardwareDetectionResult, GPUDevice, GPUVendor
from backend.app.inference.registry.manager import CompatibilityRegistry
from backend.app.inference.providers.base import BaseInferenceProvider
from backend.app.inference.providers import get_inference_provider

logger = logging.getLogger(__name__)


class InferenceManager:
    """
    Unified Inference Supervisor and Manager.
    Coordinates automatic hardware detection across NVIDIA and AMD GPUs,
    evaluates vLLM compatibility against the model registry, selects the
    appropriate container provider (CUDA or ROCm), and exposes lifecycle controls.
    """

    _instance: Optional["InferenceManager"] = None

    def __init__(self, registry_dir: Optional[str] = None):
        self.detector = SystemGPUDetector()
        self.registry = CompatibilityRegistry(registry_dir=registry_dir)
        self._hardware_result: Optional[HardwareDetectionResult] = None
        self._active_provider: Optional[BaseInferenceProvider] = None
        self.default_model = settings.VLLM_MODEL
        self.host_port = 8001
        self.base_url = f"http://localhost:{self.host_port}/v1"

    @classmethod
    def get_instance(cls) -> "InferenceManager":
        """Singleton accessor for application-wide inference management."""
        if cls._instance is None:
            cls._instance = InferenceManager()
        return cls._instance

    def detect_hardware(self, force_refresh: bool = False) -> HardwareDetectionResult:
        """
        Detect installed GPUs (NVIDIA/AMD), drivers, and container toolkit access.
        Caches result unless force_refresh is True.
        """
        if self._hardware_result is None or force_refresh:
            logger.info("Detecting system GPU hardware...")
            self._hardware_result = self.detector.detect()
            self._active_provider = get_inference_provider(self._hardware_result, self.registry)
            logger.info(
                f"Detection complete: vendor={self._hardware_result.selected_vendor.value}, "
                f"provider={self._hardware_result.recommended_provider}, "
                f"vLLM supported={self._hardware_result.is_vllm_supported}"
            )
        return self._hardware_result

    def get_provider(self) -> BaseInferenceProvider:
        """Get the active inference provider for detected hardware."""
        if self._active_provider is None:
            self.detect_hardware()
        return self._active_provider  # type: ignore

    def check_compatibility(self, model_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Verify whether the detected hardware can run the requested model.
        """
        model = model_name or self.default_model
        provider = self.get_provider()
        return provider.check_compatibility(model)

    def get_runtime_config(self, model_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Retrieve container orchestration configuration for current hardware.
        """
        model = model_name or self.default_model
        provider = self.get_provider()
        return provider.get_runtime_config(model)

    async def start(self, model_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Start and supervise the hardware-accelerated vLLM inference container.
        """
        model = model_name or self.default_model
        provider = self.get_provider()
        logger.info(f"Starting inference with provider {type(provider).__name__} for model {model}...")
        return await provider.start(model)

    async def stop(self) -> Dict[str, Any]:
        """
        Stop the inference container.
        """
        provider = self.get_provider()
        logger.info(f"Stopping inference container via {type(provider).__name__}...")
        return await provider.stop()

    async def health(self) -> Dict[str, Any]:
        """
        Query vLLM health and container availability.
        """
        provider = self.get_provider()
        return await provider.health()

    async def logs(self, tail: int = 100) -> str:
        """
        Retrieve container stdout/stderr logs.
        """
        provider = self.get_provider()
        return await provider.logs(tail=tail)

    async def get_system_status(self) -> Dict[str, Any]:
        """
        Aggregate comprehensive hardware detection, compatibility, and container status.
        """
        hw = self.detect_hardware()
        provider = self.get_provider()
        h_status = await provider.health()

        selected = hw.selected_device
        return {
            "hardware": {
                "os": hw.os_type,
                "vendor": hw.selected_vendor.value,
                "recommended_provider": hw.recommended_provider,
                "is_vllm_supported": hw.is_vllm_supported,
                "status_summary": hw.status_summary,
                "device": {
                    "name": selected.name if selected else "No GPU",
                    "architecture": selected.architecture.value if selected else "unknown",
                    "compute_capability": selected.compute_capability if selected else None,
                    "vram_total_mb": selected.vram_total_mb if selected else 0,
                    "vram_free_mb": selected.vram_free_mb if selected else 0,
                    "driver_version": selected.driver_version if selected else None,
                    "pci_bus_id": selected.pci_bus_id if selected else None,
                } if selected else None,
                "docker_access": {
                    "docker_available": hw.docker_access.docker_available,
                    "nvidia_container_accessible": hw.docker_access.nvidia_container_accessible,
                    "rocm_container_accessible": hw.docker_access.rocm_container_accessible,
                    "rocm_kfd_accessible": hw.docker_access.rocm_kfd_accessible,
                    "rocm_dri_accessible": hw.docker_access.rocm_dri_accessible,
                },
            },
            "inference": {
                "provider": hw.recommended_provider,
                "online": h_status.get("online", False),
                "model": self.default_model,
                "base_url": self.base_url,
                "details": h_status,
            },
        }


# Global instance
inference_manager = InferenceManager.get_instance()
