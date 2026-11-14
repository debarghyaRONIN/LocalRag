import platform
from typing import List, Optional
from backend.app.inference.detector.models import (
    GPUDevice,
    GPUVendor,
    HardwareDetectionResult,
    DockerGPUAccess,
)
from backend.app.inference.detector.nvidia import NvidiaDetector
from backend.app.inference.detector.amd import AMDDetector


class SystemGPUDetector:
    """
    Unified cross-platform GPU detection engine with Linux distribution specialization.
    Detects NVIDIA (CUDA) and AMD (ROCm), determines primary inference device,
    and validates container runtime accessibility.
    """

    def __init__(self):
        self.nvidia_detector = NvidiaDetector()
        self.amd_detector = AMDDetector()

    def select_primary_device(self, detected_devices: List[GPUDevice]) -> Optional[GPUDevice]:
        """Prioritize compatible discrete devices with maximum VRAM."""
        if not detected_devices:
            return None
        sorted_devs = sorted(
            detected_devices,
            key=lambda d: (d.is_compatible, d.is_discrete, d.vram_total_mb),
            reverse=True
        )
        return sorted_devs[0]

    def detect(self) -> HardwareDetectionResult:
        os_name = platform.system().lower()
        kernel_ver = platform.release()

        detected_devices: List[GPUDevice] = []
        logs: List[str] = []

        # 1. Probe NVIDIA hardware
        if self.nvidia_detector.is_vendor_present():
            nv_devs = self.nvidia_detector.detect_devices()
            detected_devices.extend(nv_devs)
            logs.append(f"Detected {len(nv_devs)} NVIDIA GPU(s).")

        # 2. Probe AMD hardware
        if self.amd_detector.is_vendor_present():
            amd_devs = self.amd_detector.detect_devices()
            detected_devices.extend(amd_devs)
            logs.append(f"Detected {len(amd_devs)} AMD GPU(s).")

        # 3. Select primary inference device (Prioritize discrete GPUs with largest VRAM)
        selected_device: Optional[GPUDevice] = self.select_primary_device(detected_devices)
        selected_vendor: GPUVendor = GPUVendor.CPU_ONLY
        recommended_provider: str = "cpu"
        is_vllm_supported: bool = False

        if selected_device:
            selected_vendor = selected_device.vendor
            if selected_device.is_compatible:
                is_vllm_supported = True
                if selected_vendor == GPUVendor.NVIDIA:
                    recommended_provider = "cuda"
                elif selected_vendor == GPUVendor.AMD:
                    recommended_provider = "rocm"

        # 4. Validate Docker GPU access for selected vendor
        docker_access = DockerGPUAccess()
        if selected_vendor == GPUVendor.NVIDIA:
            docker_access = self.nvidia_detector.validate_docker_access()
        elif selected_vendor == GPUVendor.AMD:
            docker_access = self.amd_detector.validate_docker_access()

        # Build summary string
        if selected_device:
            status_summary = (
                f"Selected {selected_device.vendor.value} GPU: {selected_device.name} "
                f"({selected_device.architecture.value}, {selected_device.vram_total_mb} MB VRAM). "
                f"Recommended runtime: {recommended_provider.upper()}."
            )
        else:
            status_summary = "No compatible GPU acceleration found. Host restricted to CPU execution."

        return HardwareDetectionResult(
            os_type=os_name,
            kernel_version=kernel_ver,
            detected_devices=detected_devices,
            selected_device=selected_device,
            selected_vendor=selected_vendor,
            docker_access=docker_access,
            recommended_provider=recommended_provider,
            is_vllm_supported=is_vllm_supported,
            status_summary=status_summary,
        )
