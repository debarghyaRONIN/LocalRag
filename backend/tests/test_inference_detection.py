import pytest
from backend.app.inference.detector.models import (
    GPUVendor,
    GPUArchitecture,
    GPUDevice,
    DockerGPUAccess,
    HardwareDetectionResult,
)
from backend.app.inference.detector.nvidia import NvidiaDetector, map_compute_cap_to_arch
from backend.app.inference.detector.amd import AMDDetector, map_rocm_gfx_to_arch
from backend.app.inference.detector.linux import SystemGPUDetector


def test_nvidia_compute_capability_mapping():
    """Verify compute capability to architecture mapping."""
    assert map_compute_cap_to_arch("7.0") == GPUArchitecture.VOLTA
    assert map_compute_cap_to_arch("7.5") == GPUArchitecture.TURING
    assert map_compute_cap_to_arch("8.0") == GPUArchitecture.AMPERE
    assert map_compute_cap_to_arch("8.6") == GPUArchitecture.AMPERE
    assert map_compute_cap_to_arch("8.9") == GPUArchitecture.ADA_LOVELACE
    assert map_compute_cap_to_arch("9.0") == GPUArchitecture.HOPPER
    assert map_compute_cap_to_arch("10.0") == GPUArchitecture.BLACKWELL
    assert map_compute_cap_to_arch("unknown") == GPUArchitecture.UNKNOWN


def test_amd_gfx_mapping():
    """Verify AMD gfx target to architecture and HSA override mapping."""
    arch, hsa = map_rocm_gfx_to_arch("gfx940")
    assert arch == GPUArchitecture.CDNA_3
    assert hsa is None

    arch, hsa = map_rocm_gfx_to_arch("gfx90a")
    assert arch == GPUArchitecture.CDNA_2
    assert hsa is None

    arch, hsa = map_rocm_gfx_to_arch("gfx1100")
    assert arch == GPUArchitecture.RDNA_3
    assert hsa == "11.0.0"

    arch, hsa = map_rocm_gfx_to_arch("gfx1030")
    assert arch == GPUArchitecture.RDNA_2
    assert hsa == "10.3.0"


def test_nvidia_detector_resilience(monkeypatch):
    """Test NvidiaDetector behavior when nvidia-smi is unavailable."""
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    detector = NvidiaDetector()
    assert not detector.is_vendor_present()
    devices = detector.detect_devices()
    assert len(devices) == 0


def test_amd_detector_resilience(monkeypatch):
    """Test AMDDetector behavior when rocminfo is unavailable."""
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    monkeypatch.setattr("os.path.exists", lambda path: False)
    detector = AMDDetector()
    assert not detector.is_vendor_present()
    devices = detector.detect_devices()
    assert len(devices) == 0


def test_system_detector_selection():
    """Test unified detector selects device with maximum VRAM."""
    dev_small = GPUDevice(
        index=0,
        vendor=GPUVendor.NVIDIA,
        name="GTX 1650",
        architecture=GPUArchitecture.TURING,
        compute_capability="7.5",
        vram_total_mb=4096,
        is_compatible=False,
    )
    dev_large = GPUDevice(
        index=1,
        vendor=GPUVendor.NVIDIA,
        name="RTX 3060",
        architecture=GPUArchitecture.AMPERE,
        compute_capability="8.6",
        vram_total_mb=12288,
        is_compatible=True,
    )

    sys_detector = SystemGPUDetector()
    selected = sys_detector.select_primary_device([dev_small, dev_large])
    assert selected is not None
    assert selected.name == "RTX 3060"
    assert selected.vram_total_mb == 12288

