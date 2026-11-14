import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from backend.app.inference.detector.base import BaseGPUDetector
from backend.app.inference.detector.models import (
    GPUDevice,
    GPUVendor,
    GPUArchitecture,
    DockerGPUAccess,
)


def map_rocm_gfx_to_arch(gfx_target: str) -> Tuple[GPUArchitecture, Optional[str]]:
    """
    Map ROCm gfx architecture string to named architecture and optional HSA_OVERRIDE_GFX_VERSION.
    vLLM ROCm natively targets CDNA, but consumer RDNA2/RDNA3 cards function reliably with HSA overrides.
    """
    clean = gfx_target.lower().strip()
    if "gfx94" in clean:
        return GPUArchitecture.CDNA_3, None
    elif "gfx90a" in clean:
        return GPUArchitecture.CDNA_2, None
    elif "gfx908" in clean or "gfx906" in clean:
        return GPUArchitecture.CDNA_1, None
    elif "gfx11" in clean:
        # RDNA 3 requires HSA override for vLLM PyTorch kernels
        return GPUArchitecture.RDNA_3, "11.0.0"
    elif "gfx1030" in clean:
        # RDNA 2 requires HSA override
        return GPUArchitecture.RDNA_2, "10.3.0"

    return GPUArchitecture.UNKNOWN, None


class AMDDetector(BaseGPUDetector):
    def __init__(self):
        self._rocminfo_bin = shutil.which("rocminfo")
        self._rocm_smi_bin = shutil.which("rocm-smi")

    def is_vendor_present(self) -> bool:
        """Check presence of AMD hardware via rocminfo, kernel nodes, or sysfs PCI vendor 0x1002."""
        if self._rocminfo_bin or self._rocm_smi_bin:
            return True

        if Path("/dev/kfd").exists():
            return True

        # Linux sysfs PCI check (AMD vendor ID is 0x1002)
        pci_dir = Path("/sys/bus/pci/devices")
        if pci_dir.exists():
            try:
                for dev in pci_dir.iterdir():
                    vendor_file = dev / "vendor"
                    if vendor_file.exists() and "0x1002" in vendor_file.read_text().lower():
                        return True
            except Exception:
                pass

        return False

    def detect_devices(self) -> List[GPUDevice]:
        devices: List[GPUDevice] = []

        # Strategy 1: rocminfo query
        if self._rocminfo_bin:
            devices = self._detect_via_rocminfo()
            if devices:
                return devices

        # Strategy 2: rocm-smi query
        if self._rocm_smi_bin:
            devices = self._detect_via_rocm_smi()
            if devices:
                return devices

        # Strategy 3: sysfs kernel fallback
        return self._detect_via_sysfs()

    def _detect_via_rocminfo(self) -> List[GPUDevice]:
        devices = []
        try:
            out = subprocess.check_output([self._rocminfo_bin], encoding="utf-8", timeout=4.0)
            agents = out.split("Agent ")

            idx = 0
            for agent in agents[1:]:
                if "Device Type:           GPU" in agent:
                    name_match = re.search(r"Marketing Name:\s*(.+)", agent)
                    gfx_match = re.search(r"Name:\s*(gfx[0-9a-f]+)", agent)

                    name = name_match.group(1).strip() if name_match else "AMD Radeon / Instinct GPU"
                    gfx = gfx_match.group(1).strip() if gfx_match else "unknown"

                    arch, hsa_override = map_rocm_gfx_to_arch(gfx)

                    # vLLM ROCm compatibility check
                    is_compat = True
                    incompat_reasons = []

                    if arch == GPUArchitecture.UNKNOWN:
                        is_compat = False
                        incompat_reasons.append(f"ROCm target '{gfx}' is not recognized as a vLLM-compatible architecture.")

                    devices.append(
                        GPUDevice(
                            index=idx,
                            vendor=GPUVendor.AMD,
                            name=name,
                            architecture=arch,
                            compute_capability=gfx,
                            is_discrete=True,
                            is_compatible=is_compat,
                            incompatibility_reasons=incompat_reasons,
                            hsa_override_gfx_version=hsa_override,
                        )
                    )
                    idx += 1
        except Exception:
            pass
        return devices

    def _detect_via_rocm_smi(self) -> List[GPUDevice]:
        devices = []
        try:
            cmd = [self._rocm_smi_bin, "--showproductname", "--showdriverversion", "--showmeminfo", "vram", "--csv"]
            out = subprocess.check_output(cmd, encoding="utf-8", timeout=3.0)
            lines = out.strip().splitlines()
            if len(lines) > 1:
                for idx, line in enumerate(lines[1:]):
                    parts = line.split(",")
                    name = parts[1].strip() if len(parts) > 1 else "AMD GPU"
                    devices.append(
                        GPUDevice(
                            index=idx,
                            vendor=GPUVendor.AMD,
                            name=name,
                            architecture=GPUArchitecture.RDNA_3,  # Best heuristic guess
                            is_discrete=True,
                            is_compatible=True,
                            hsa_override_gfx_version="11.0.0",
                        )
                    )
        except Exception:
            pass
        return devices

    def _detect_via_sysfs(self) -> List[GPUDevice]:
        """Fallback detection by inspecting Linux sysfs DRM subsystem."""
        devices = []
        kfd_path = Path("/dev/kfd")
        if not kfd_path.exists():
            return devices

        drm_dir = Path("/sys/class/drm")
        if drm_dir.exists():
            try:
                for card in drm_dir.glob("card[0-9]"):
                    device_path = card / "device"
                    vendor_path = device_path / "vendor"
                    if vendor_path.exists() and "0x1002" in vendor_path.read_text().lower():
                        devices.append(
                            GPUDevice(
                                index=len(devices),
                                vendor=GPUVendor.AMD,
                                name="AMD GPU (sysfs kfd detected)",
                                architecture=GPUArchitecture.UNKNOWN,
                                is_compatible=True,
                                incompatibility_reasons=["Detected via kernel node; rocm-smi needed for architecture verification."]
                            )
                        )
            except Exception:
                pass
        return devices

    def validate_docker_access(self) -> DockerGPUAccess:
        """
        Validate whether Docker container can access AMD GPU acceleration:
        1. /dev/kfd exists and current user has read/write permissions.
        2. /dev/dri render nodes exist.
        3. Docker daemon accessibility.
        """
        access = DockerGPUAccess()
        docker_bin = shutil.which("docker")
        if not docker_bin:
            access.validation_logs.append("Docker executable not found on PATH.")
            return access

        access.docker_available = True

        # Check /dev/kfd node
        kfd_node = Path("/dev/kfd")
        if kfd_node.exists():
            access.rocm_kfd_accessible = os.access(kfd_node, os.R_OK | os.W_OK)
            access.validation_logs.append(f"/dev/kfd found (RW access: {access.rocm_kfd_accessible})")
        else:
            access.validation_logs.append("/dev/kfd node missing. Ensure amdgpu kernel driver is active.")

        # Check /dev/dri directory
        dri_dir = Path("/dev/dri")
        if dri_dir.exists():
            render_nodes = list(dri_dir.glob("renderD*"))
            access.rocm_dri_accessible = len(render_nodes) > 0 and all(os.access(n, os.R_OK | os.W_OK) for n in render_nodes)
            access.validation_logs.append(f"/dev/dri render nodes found: {len(render_nodes)}")
        else:
            access.validation_logs.append("/dev/dri device directory missing.")

        if access.rocm_kfd_accessible and access.rocm_dri_accessible:
            access.rocm_container_accessible = True
            access.validation_logs.append("AMD ROCm container device pass-through validated successfully.")

        return access
