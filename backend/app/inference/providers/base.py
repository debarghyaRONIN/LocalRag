from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from backend.app.inference.detector.models import GPUDevice, HardwareDetectionResult


class BaseInferenceProvider(ABC):
    """
    Vendor-independent inference provider interface for vLLM container management.
    """

    @abstractmethod
    def detect_hardware(self) -> HardwareDetectionResult:
        """Detect underlying hardware and validate device nodes."""
        pass

    @abstractmethod
    def check_compatibility(self, model_name: str) -> Dict[str, Any]:
        """Verify whether detected hardware can run the requested model with this provider."""
        pass

    @abstractmethod
    def get_runtime_config(self, model_name: str) -> Dict[str, Any]:
        """Produce the Docker / container orchestration configuration for this provider."""
        pass

    @abstractmethod
    async def start(self, model_name: str) -> Dict[str, Any]:
        """Start and supervise the vLLM container."""
        pass

    @abstractmethod
    async def stop(self) -> Dict[str, Any]:
        """Stop and terminate the vLLM container."""
        pass

    @abstractmethod
    async def health(self) -> Dict[str, Any]:
        """Query vLLM health and model readiness."""
        pass

    @abstractmethod
    async def logs(self, tail: int = 100) -> str:
        """Retrieve recent container stdout/stderr logs for diagnostics."""
        pass

