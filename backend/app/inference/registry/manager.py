from pathlib import Path
from typing import Dict, Any, Optional
import yaml
from backend.app.inference.detector.models import GPUDevice, GPUVendor


class CompatibilityRegistry:
    """
    Evaluates hardware detection against version-controlled compatibility registries
    to determine optimal vLLM image tags, resource budgets, and container arguments.
    """

    def __init__(self, registry_dir: Optional[Path] = None):
        self.registry_dir = registry_dir or Path(__file__).parent
        self.runtime_versions = self._load_yaml("runtime_versions.yaml")
        self.cuda_images = self._load_yaml("cuda_images.yaml")
        self.rocm_images = self._load_yaml("rocm_images.yaml")
        self.gpu_compatibility = self._load_yaml("gpu_compatibility.yaml")
        self.model_compatibility = self._load_yaml("model_compatibility.yaml")

    def _load_yaml(self, filename: str) -> Dict[str, Any]:
        path = self.registry_dir / filename
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def get_runtime_for_device(
        self,
        device: GPUDevice,
        model_name: str = "Qwen/Qwen2.5-3B-Instruct"
    ) -> Dict[str, Any]:
        """
        Determine container image, environment variables, and vLLM CLI arguments
        based on detected device architecture and model VRAM budget.
        """
        model_info = self.model_compatibility.get("models", {}).get(model_name, {})
        min_vram = model_info.get("min_vram_mb", 6000)

        # Baseline check
        if device.vram_total_mb > 0 and device.vram_total_mb < min_vram:
            return {
                "compatible": False,
                "error": f"GPU VRAM ({device.vram_total_mb} MB) is insufficient for model '{model_name}' (requires >= {min_vram} MB).",
            }

        if device.vendor == GPUVendor.NVIDIA:
            return self._build_cuda_runtime(device, model_name, model_info)
        elif device.vendor == GPUVendor.AMD:
            return self._build_rocm_runtime(device, model_name, model_info)
        else:
            return {
                "compatible": False,
                "error": "No supported GPU vendor detected. vLLM requires NVIDIA CUDA or AMD ROCm acceleration.",
            }

    def _build_cuda_runtime(self, device: GPUDevice, model_name: str, model_info: Dict[str, Any]) -> Dict[str, Any]:
        image_tag = self.cuda_images.get("default_image", "vllm/vllm-openai:latest")

        # Memory profile heuristic
        vram_util = 0.70
        enforce_eager = True
        max_model_len = model_info.get("default_max_len", 8192)

        if device.vram_total_mb >= 24000:
            vram_util = 0.85
            enforce_eager = False
            max_model_len = 16384
        elif device.vram_total_mb >= 16000:
            vram_util = 0.80

        cli_args = [
            f"--model {model_name}",
            "--port 8000",
            f"--gpu-memory-utilization {vram_util:.2f}",
            f"--max-model-len {max_model_len}",
            "--dtype auto",
        ]
        if enforce_eager:
            cli_args.append("--enforce-eager")

        return {
            "compatible": True,
            "provider": "cuda",
            "image": image_tag,
            "command": " ".join(cli_args),
            "environment": {},
            "container_config": self.cuda_images.get("container_config", {}),
            "gpu_memory_utilization": vram_util,
            "max_model_len": max_model_len,
        }

    def _build_rocm_runtime(self, device: GPUDevice, model_name: str, model_info: Dict[str, Any]) -> Dict[str, Any]:
        image_tag = self.rocm_images.get("default_image", "vllm/vllm-openai:rocm")

        vram_util = 0.75
        max_model_len = model_info.get("default_max_len", 8192)

        env = {}
        if device.hsa_override_gfx_version:
            env["HSA_OVERRIDE_GFX_VERSION"] = device.hsa_override_gfx_version

        cli_args = [
            f"--model {model_name}",
            "--port 8000",
            f"--gpu-memory-utilization {vram_util:.2f}",
            f"--max-model-len {max_model_len}",
            "--dtype auto",
            "--enforce-eager",
        ]

        return {
            "compatible": True,
            "provider": "rocm",
            "image": image_tag,
            "command": " ".join(cli_args),
            "environment": env,
            "container_config": self.rocm_images.get("container_config", {}),
            "gpu_memory_utilization": vram_util,
            "max_model_len": max_model_len,
        }

