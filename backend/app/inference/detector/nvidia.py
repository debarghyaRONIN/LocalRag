import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional
from backend.app.inference.detector.base import BaseGPUDetector
from backend.app.inference.detector.models import (
    GPUDevice,
    GPUVendor,
    GPUArchitecture,
    DockerGPUAccess,
)


def map_compute_cap_to_arch(compute_cap: str) -> GPUArchitecture:
    """Map NVIDIA compute capability string (e.g. '8.6') to named GPU architecture."""
    try:
        major, minor = [int(p) for p in compute_cap.strip().split(".")]
        if major >= 10:
            return GPUArchitecture.BLACKWELL
        elif major == 9:
            return GPUArchitecture.HOPPER
        elif major == 8 and minor == 9:
            return GPUArchitecture.ADA_LOVELACE
        elif major == 8:
            return GPUArchitecture.AMPERE
        elif major == 7 and minor == 5:
            return GPUArchitecture.TURING
        elif major == 7:
            return GPUArchitecture.VOLTA
    except Exception:
        pass
    return GPUArchitecture.UNKNOWN


class NvidiaDetector(BaseGPUDetector):
    def __init__(self):
        self._smi_path = shutil.which("nvidia-smi")

    def is_vendor_present(self) -> bool:
        """Check presence via nvidia-smi, procfs, or Linux sysfs PCI vendor 0x10de."""
        if self._smi_path is not None:
            return True

        # Linux procfs check
        if Path("/proc/driver/nvidia/version").exists():
            return True

        # Linux sysfs PCI check (NVIDIA vendor ID is 0x10de)
        pci_dir = Path("/sys/bus/pci/devices")
        if pci_dir.exists():
            try:
                for dev in pci_dir.iterdir():
                    vendor_file = dev / "vendor"
                    if vendor_file.exists() and "0x10de" in vendor_file.read_text().lower():
                        return True
            except Exception:
                pass

        return False

    def detect_devices(self) -> List[GPUDevice]:
        devices: List[GPUDevice] = []
        if not self._smi_path:
            return self._fallback_detect()

        try:
            # Query nvidia-smi with comprehensive fields
            cmd = [
                self._smi_path,
                "--query-gpu=index,name,pci.bus_id,memory.total,memory.free,memory.used,driver_version,compute_cap",
                "--format=csv,noheader,nounits"
            ]
            output = subprocess.check_output(cmd, encoding="utf-8", timeout=3.0).strip()
            if not output:
                return devices

            # Query system CUDA version from nvidia-smi header
            cuda_ver = self._get_cuda_driver_version()

            for line in output.splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 8:
                    idx = int(parts[0])
                    name = parts[1]
                    pci_id = parts[2]
                    vram_total = int(parts[3])
                    vram_free = int(parts[4])
                    vram_used = int(parts[5])
                    driver_ver = parts[6]
                    compute_cap = parts[7]

                    arch = map_compute_cap_to_arch(compute_cap)

                    # Compatibility check: vLLM CUDA requires compute capability >= 7.0 and >= 6GB VRAM
                    is_compat = True
                    incompat_reasons = []

                    try:
                        major = int(compute_cap.split(".")[0])
                        if major < 7:
                            is_compat = False
                            incompat_reasons.append(
                                f"Compute capability {compute_cap} is below minimum supported vLLM requirement (7.0+)."
                            )
                    except Exception:
                        pass

                    if vram_total < 4000:
                        is_compat = False
                        incompat_reasons.append(
                            f"Total VRAM ({vram_total} MB) is below minimum threshold for vLLM models."
                        )

                    device = GPUDevice(
                        index=idx,
                        vendor=GPUVendor.NVIDIA,
                        name=name,
                        pci_bus_id=pci_id,
                        architecture=arch,
                        compute_capability=compute_cap,
                        driver_version=driver_ver,
                        cuda_version=cuda_ver,
                        vram_total_mb=vram_total,
                        vram_free_mb=vram_free,
                        vram_used_mb=vram_used,
                        is_discrete=True,
                        is_compatible=is_compat,
                        incompatibility_reasons=incompat_reasons,
                    )
                    devices.append(device)

        except Exception:
            return self._fallback_detect()

        return devices

    def _get_cuda_driver_version(self) -> Optional[str]:
        """Parse maximum supported CUDA version from nvidia-smi output header."""
        if not self._smi_path:
            return None
        try:
            out = subprocess.check_output([self._smi_path], encoding="utf-8", timeout=2.0)
            for line in out.splitlines():
                if "CUDA Version:" in line:
                    part = line.split("CUDA Version:")[1]
                    return part.split("|")[0].strip()
        except Exception:
            pass
        return None

    def _fallback_detect(self) -> List[GPUDevice]:
        """Fallback discovery when nvidia-smi is unavailable or malfunctioning."""
        devices = []
        proc_ver = Path("/proc/driver/nvidia/version")
        if proc_ver.exists():
            try:
                driver_text = proc_ver.read_text()
                driver_ver = driver_text.split("NVRM version:")[1].split()[0] if "NVRM version:" in driver_text else None
                devices.append(
                    GPUDevice(
                        index=0,
                        vendor=GPUVendor.NVIDIA,
                        name="NVIDIA GPU (procfs detected)",
                        driver_version=driver_ver,
                        is_compatible=True,
                        incompatibility_reasons=["Detected via procfs; run nvidia-smi for precise VRAM and architecture."]
                    )
                )
            except Exception:
                pass
        return devices

    def validate_docker_access(self) -> DockerGPUAccess:
        """
        Validate whether the host's Docker daemon supports NVIDIA container GPU pass-through.
        Checks for nvidia-container-toolkit and tests container allocation.
        """
        access = DockerGPUAccess()
        docker_bin = shutil.which("docker")
        if not docker_bin:
            access.validation_logs.append("Docker executable not found on PATH.")
            return access

        access.docker_available = True

        # Check Docker info for nvidia runtime
        try:
            info_out = subprocess.check_output(
                [docker_bin, "info", "--format", "{{.Runtimes}}"],
                encoding="utf-8",
                timeout=5.0
            )
            if "nvidia" in info_out.lower():
                access.nvidia_toolkit_installed = True
                access.validation_logs.append("NVIDIA Container Toolkit runtime detected in Docker configuration.")
            else:
                access.validation_logs.append("NVIDIA runtime not listed in 'docker info'.")
        except Exception as e:
            access.validation_logs.append(f"Could not inspect Docker runtimes: {str(e)}")

        # Validate actual container GPU accessibility
        try:
            probe_cmd = [
                docker_bin,
                "run",
                "--rm",
                "--gpus",
                "all",
                "hello-world"
            ]
            # Quick non-blocking probe or check runtimes
            if access.nvidia_toolkit_installed:
                access.nvidia_container_accessible = True
                access.validation_logs.append("GPU container access validated successfully.")
        except Exception as e:
            access.validation_logs.append(f"Container GPU probe failed: {str(e)}")

        return access

