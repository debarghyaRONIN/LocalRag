import pytest
from backend.app.inference.providers.cuda import CUDAInferenceProvider
from backend.app.inference.providers.rocm import ROCmInferenceProvider
from backend.app.inference.providers.cpu import CPUInferenceProvider
from backend.app.inference.providers import get_inference_provider
from backend.app.inference.detector.models import (
    GPUDevice,
    GPUVendor,
    GPUArchitecture,
    DockerGPUAccess,
    HardwareDetectionResult,
)
from backend.app.inference.registry.manager import CompatibilityRegistry
from backend.app.inference.manager import InferenceManager


@pytest.fixture
def mock_registry():
    return CompatibilityRegistry()


def test_cpu_provider_fail_fast():
    """Verify CPU provider strictly blocks CPU inference and gives actionable errors."""
    cpu_p = CPUInferenceProvider()
    
    # Compatibility must report false
    compat = cpu_p.check_compatibility("Qwen/Qwen2.5-3B-Instruct")
    assert compat["compatible"] is False
    assert "not supported" in compat["error"].lower()
    assert len(compat["troubleshooting"]) > 0

    # Runtime config must fail
    cfg = cpu_p.get_runtime_config("Qwen/Qwen2.5-3B-Instruct")
    assert cfg["compatible"] is False

    # Detection must report unsupported
    det = cpu_p.detect_hardware()
    assert det.is_vllm_supported is False
    assert det.recommended_provider == "cpu"


@pytest.mark.asyncio
async def test_cpu_provider_lifecycle():
    """Verify CPU provider refuses to start container and reports unsupported health."""
    cpu_p = CPUInferenceProvider()

    res = await cpu_p.start("Qwen/Qwen2.5-3B-Instruct")
    assert res["status"] == "error"
    assert res["action"] == "blocked"

    h = await cpu_p.health()
    assert h["online"] is False
    assert h["status"] == "unsupported"

    logs = await cpu_p.logs()
    assert "Diagnostic" in logs


def test_provider_factory():
    """Verify factory returns appropriate provider based on hardware detection."""
    hw_nvidia = HardwareDetectionResult(
        os_type="linux",
        detected_devices=[],
        selected_device=None,
        selected_vendor=GPUVendor.NVIDIA,
        docker_access=DockerGPUAccess(),
        recommended_provider="cuda",
        is_vllm_supported=True,
    )
    p_cuda = get_inference_provider(hw_nvidia)
    assert isinstance(p_cuda, CUDAInferenceProvider)

    hw_amd = HardwareDetectionResult(
        os_type="linux",
        detected_devices=[],
        selected_device=None,
        selected_vendor=GPUVendor.AMD,
        docker_access=DockerGPUAccess(),
        recommended_provider="rocm",
        is_vllm_supported=True,
    )
    p_rocm = get_inference_provider(hw_amd)
    assert isinstance(p_rocm, ROCmInferenceProvider)

    hw_none = HardwareDetectionResult(
        os_type="linux",
        detected_devices=[],
        selected_device=None,
        selected_vendor=GPUVendor.CPU_ONLY,
        docker_access=DockerGPUAccess(),
        recommended_provider="cpu",
        is_vllm_supported=False,
    )
    p_cpu = get_inference_provider(hw_none)
    assert isinstance(p_cpu, CPUInferenceProvider)


def test_rocm_device_configuration(mock_registry):
    """Test ROCm provider evaluates AMD device with appropriate image and overrides."""
    rocm_p = ROCmInferenceProvider(registry=mock_registry)
    amd_dev = GPUDevice(
        index=0,
        vendor=GPUVendor.AMD,
        name="AMD Instinct MI250X",
        architecture=GPUArchitecture.CDNA_2,
        compute_capability="gfx90a",
        vram_total_mb=65536,
        is_compatible=True,
    )
    res = mock_registry.get_runtime_for_device(amd_dev, "Qwen/Qwen2.5-7B-Instruct")
    assert res["compatible"] is True
    assert res["provider"] == "rocm"
    assert "rocm" in res["image"]
    assert res["container_config"]["devices"] == ["/dev/kfd", "/dev/dri"]


def test_cuda_device_configuration(mock_registry):
    """Test CUDA provider evaluates NVIDIA RTX 3060 with appropriate memory utilization."""
    cuda_p = CUDAInferenceProvider(registry=mock_registry)
    nv_dev = GPUDevice(
        index=0,
        vendor=GPUVendor.NVIDIA,
        name="NVIDIA GeForce RTX 3060",
        architecture=GPUArchitecture.AMPERE,
        compute_capability="8.6",
        vram_total_mb=12288,
        is_compatible=True,
    )
    res = mock_registry.get_runtime_for_device(nv_dev, "Qwen/Qwen2.5-3B-Instruct")
    assert res["compatible"] is True
    assert res["provider"] == "cuda"
    assert res["gpu_memory_utilization"] == 0.70
    assert res["max_model_len"] == 8192


@pytest.mark.asyncio
async def test_inference_manager_system_status():
    """Verify InferenceManager status aggregation."""
    manager = InferenceManager()
    status = await manager.get_system_status()
    assert "hardware" in status
    assert "inference" in status
    assert "vendor" in status["hardware"]
    assert "docker_access" in status["hardware"]
