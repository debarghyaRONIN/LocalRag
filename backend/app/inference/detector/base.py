from abc import ABC, abstractmethod
from typing import List
from backend.app.inference.detector.models import GPUDevice, DockerGPUAccess


class BaseGPUDetector(ABC):
    """
    Abstract interface for vendor-specific hardware and container access detection.
    """

    @abstractmethod
    def is_vendor_present(self) -> bool:
        """Return True if hardware or drivers from this vendor are present on the host."""
        pass

    @abstractmethod
    def detect_devices(self) -> List[GPUDevice]:
        """Detect and return detailed information for all GPUs from this vendor."""
        pass

    @abstractmethod
    def validate_docker_access(self) -> DockerGPUAccess:
        """Validate whether Docker can access GPU acceleration for this vendor."""
        pass

