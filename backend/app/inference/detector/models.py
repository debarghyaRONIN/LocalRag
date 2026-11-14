from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class GPUVendor(str, Enum):
    NVIDIA = "NVIDIA"
    AMD = "AMD"
    INTEL = "INTEL"
    CPU_ONLY = "CPU_ONLY"
    UNKNOWN = "UNKNOWN"


class GPUArchitecture(str, Enum):
    # NVIDIA Architectures
    BLACKWELL = "Blackwell"       # sm_100, sm_120
    HOPPER = "Hopper"             # sm_90
    ADA_LOVELACE = "Ada Lovelace" # sm_89
    AMPERE = "Ampere"             # sm_80, sm_86
    TURING = "Turing"             # sm_75
    VOLTA = "Volta"               # sm_70

    # AMD CDNA Data Center / Accelerator Architectures
    CDNA_3 = "CDNA 3"             # gfx940, gfx942 (MI300 series)
    CDNA_2 = "CDNA 2"             # gfx90a (MI200 series)
    CDNA_1 = "CDNA 1"             # gfx908 (MI100)

    # AMD RDNA Consumer / Workstation Architectures
    RDNA_3 = "RDNA 3"             # gfx1100, gfx1101, gfx1102 (RX 7000 series)
    RDNA_2 = "RDNA 2"             # gfx1030 (RX 6000 series)

    UNKNOWN = "Unknown"


class GPUDevice(BaseModel):
    index: int = 0
    vendor: GPUVendor
    name: str
    pci_bus_id: Optional[str] = None
    architecture: GPUArchitecture = GPUArchitecture.UNKNOWN
    compute_capability: Optional[str] = None  # e.g. "8.6" (CUDA) or "gfx1100" (ROCm)
    driver_version: Optional[str] = None
    cuda_version: Optional[str] = None
    rocm_version: Optional[str] = None
    vram_total_mb: int = 0
    vram_free_mb: int = 0
    vram_used_mb: int = 0
    is_discrete: bool = True
    is_compatible: bool = False
    incompatibility_reasons: List[str] = Field(default_factory=list)
    hsa_override_gfx_version: Optional[str] = None  # Needed for AMD RDNA consumer cards


class DockerGPUAccess(BaseModel):
    docker_available: bool = False
    docker_version: Optional[str] = None
    nvidia_toolkit_installed: bool = False
    nvidia_container_accessible: bool = False
    rocm_kfd_accessible: bool = False      # /dev/kfd exists & user has permissions
    rocm_dri_accessible: bool = False      # /dev/dri/renderD* exists & user has permissions
    rocm_container_accessible: bool = False
    validation_logs: List[str] = Field(default_factory=list)


class HardwareDetectionResult(BaseModel):
    os_type: str = "linux"  # linux or windows
    kernel_version: Optional[str] = None
    detected_devices: List[GPUDevice] = Field(default_factory=list)
    selected_device: Optional[GPUDevice] = None
    selected_vendor: GPUVendor = GPUVendor.UNKNOWN
    docker_access: DockerGPUAccess = Field(default_factory=DockerGPUAccess)
    recommended_provider: str = "cpu"  # "cuda", "rocm", or "cpu"
    is_vllm_supported: bool = False
    status_summary: str = ""
    error_details: Optional[str] = None

