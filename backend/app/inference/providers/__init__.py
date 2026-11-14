from typing import Optional
from backend.app.inference.providers.base import BaseInferenceProvider
from backend.app.inference.providers.cuda import CUDAInferenceProvider
from backend.app.inference.providers.rocm import ROCmInferenceProvider
from backend.app.inference.providers.cpu import CPUInferenceProvider
from backend.app.inference.detector.models import HardwareDetectionResult, GPUVendor
from backend.app.inference.registry.manager import CompatibilityRegistry


def get_inference_provider(
    hardware_result: HardwareDetectionResult,
    registry: Optional[CompatibilityRegistry] = None,
) -> BaseInferenceProvider:
    """
    Factory function to instantiate the appropriate inference provider based on hardware detection.
    """
    if hardware_result.selected_vendor == GPUVendor.NVIDIA or hardware_result.recommended_provider == "cuda":
        return CUDAInferenceProvider(registry=registry)
    elif hardware_result.selected_vendor == GPUVendor.AMD or hardware_result.recommended_provider == "rocm":
        return ROCmInferenceProvider(registry=registry)
    else:
        return CPUInferenceProvider()


__all__ = [
    "BaseInferenceProvider",
    "CUDAInferenceProvider",
    "ROCmInferenceProvider",
    "CPUInferenceProvider",
    "get_inference_provider",
]

