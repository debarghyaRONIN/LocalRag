from typing import Optional, Dict, Any
from fastapi import APIRouter, Query, Body, HTTPException
from pydantic import BaseModel

from backend.app.inference.manager import inference_manager

router = APIRouter(prefix="/inference", tags=["Inference Management"])


class StartInferenceRequest(BaseModel):
    model_name: Optional[str] = None


class TestEndpointRequest(BaseModel):
    endpoint_url: str
    provider: Optional[str] = "custom"


@router.post("/test-endpoint")
async def test_inference_endpoint(req: TestEndpointRequest):
    """
    Test connectivity to a local or LAN inference endpoint from the backend (avoiding browser CORS).
    """
    import httpx
    target = req.endpoint_url.strip().rstrip("/")
    if not target:
        raise HTTPException(status_code=400, detail="Endpoint URL cannot be empty.")

    detected_models = []

    async with httpx.AsyncClient(timeout=3.5) as client:
        # First attempt: target/models (OpenAI / vLLM / Ollama v1 endpoint)
        try:
            r = await client.get(f"{target}/models")
            if r.status_code == 200:
                data = r.json()
                detected_models = [m.get("id") for m in data.get("data", []) if m.get("id")]
                return {
                    "ok": True,
                    "status_code": 200,
                    "models": detected_models,
                    "message": f"Connected! Detected {len(detected_models)} model(s): {', '.join(detected_models[:5])}" if detected_models else "Connected to endpoint successfully."
                }
        except Exception:
            pass

        # Second attempt: If Ollama, try base URL without /v1 + /api/tags
        if "11434" in target or req.provider == "ollama":
            base_ollama = target.replace("/v1", "")
            try:
                r = await client.get(f"{base_ollama}/api/tags")
                if r.status_code == 200:
                    data = r.json()
                    detected_models = [m.get("name") for m in data.get("models", []) if m.get("name")]
                    return {
                        "ok": True,
                        "status_code": 200,
                        "models": detected_models,
                        "message": f"Connected to Ollama! Available models: {', '.join(detected_models)}" if detected_models else "Connected to Ollama! (No models pulled yet - run 'ollama run llama3.2' to download a model)."
                    }
            except Exception:
                pass

        # Third attempt: root probe
        try:
            r = await client.get(target)
            if r.status_code < 500:
                return {
                    "ok": True,
                    "status_code": r.status_code,
                    "models": [],
                    "message": f"Endpoint reachable (HTTP {r.status_code})."
                }
        except Exception as e:
            return {
                "ok": False,
                "status_code": 0,
                "models": [],
                "message": f"Could not connect to {target}: {type(e).__name__}. Ensure your local engine is running."
            }

    return {
        "ok": False,
        "status_code": 404,
        "models": [],
        "message": f"Endpoint {target} was reached but did not return a valid models catalog."
    }


@router.get("/hardware")
async def get_hardware_info(refresh: bool = Query(False, description="Force re-scan of hardware devices")):
    """
    Detect and inspect host GPU hardware (NVIDIA CUDA / AMD ROCm), driver versions,
    VRAM, architecture, and Docker container GPU access permissions.
    """
    hw = inference_manager.detect_hardware(force_refresh=refresh)
    return {
        "os_type": hw.os_type,
        "selected_vendor": hw.selected_vendor.value,
        "recommended_provider": hw.recommended_provider,
        "is_vllm_supported": hw.is_vllm_supported,
        "status_summary": hw.status_summary,
        "docker_access": {
            "docker_available": hw.docker_access.docker_available,
            "nvidia_container_accessible": hw.docker_access.nvidia_container_accessible,
            "rocm_container_accessible": hw.docker_access.rocm_container_accessible,
            "rocm_kfd_accessible": hw.docker_access.rocm_kfd_accessible,
            "rocm_dri_accessible": hw.docker_access.rocm_dri_accessible,
            "details": hw.docker_access.validation_logs,
        },
        "devices": [
            {
                "index": d.index,
                "vendor": d.vendor.value,
                "name": d.name,
                "architecture": d.architecture.value,
                "compute_capability": d.compute_capability,
                "vram_total_mb": d.vram_total_mb,
                "vram_free_mb": d.vram_free_mb,
                "driver_version": d.driver_version,
                "pci_bus_id": d.pci_bus_id,
                "is_compatible": d.is_compatible,
            }
            for d in hw.detected_devices
        ],
        "selected_device": {
            "index": hw.selected_device.index,
            "vendor": hw.selected_device.vendor.value,
            "name": hw.selected_device.name,
            "architecture": hw.selected_device.architecture.value,
            "compute_capability": hw.selected_device.compute_capability,
            "vram_total_mb": hw.selected_device.vram_total_mb,
            "vram_free_mb": hw.selected_device.vram_free_mb,
            "driver_version": hw.selected_device.driver_version,
            "pci_bus_id": hw.selected_device.pci_bus_id,
            "is_compatible": hw.selected_device.is_compatible,
        } if hw.selected_device else None,
    }


@router.get("/status")
async def get_inference_status():
    """
    Get aggregated real-time status of the inference engine, provider, and container health.
    """
    return await inference_manager.get_system_status()


@router.get("/models")
async def list_available_models():
    """
    List detected local models available for inference across Ollama and vLLM.
    """
    from backend.app.services.generation.llm_client import VLLMClient
    client = VLLMClient()
    models = await client.get_available_models()
    return {
        "active_model": client.model,
        "available_models": models,
    }


@router.get("/compatibility")
async def check_model_compatibility(model: Optional[str] = Query(None, description="Hugging Face model ID to verify")):
    """
    Validate whether the detected hardware can run the requested model in vLLM.
    """
    return inference_manager.check_compatibility(model_name=model)


@router.post("/start")
async def start_inference_container(request: Optional[StartInferenceRequest] = None):
    """
    Start and supervise the hardware-aware vLLM container (CUDA or ROCm) for the selected model.
    """
    model_name = request.model_name if request else None
    result = await inference_manager.start(model_name=model_name)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to start inference container."))
    return result


@router.post("/stop")
async def stop_inference_container():
    """
    Stop and remove the active vLLM inference container.
    """
    return await inference_manager.stop()


@router.get("/logs")
async def get_inference_logs(tail: int = Query(100, ge=10, le=1000, description="Number of log lines to retrieve")):
    """
    Fetch recent stdout/stderr logs from the vLLM container for diagnostics.
    """
    logs = await inference_manager.logs(tail=tail)
    return {"tail": tail, "logs": logs}
