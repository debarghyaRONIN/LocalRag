import pytest
import httpx
from backend.app.main import app


@pytest.mark.asyncio
async def test_get_hardware_endpoint():
    """Verify /api/v1/inference/hardware endpoint returns hardware details."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/inference/hardware")
        assert response.status_code == 200
        data = response.json()
        assert "os_type" in data
        assert "selected_vendor" in data
        assert "recommended_provider" in data
        assert "docker_access" in data


@pytest.mark.asyncio
async def test_get_inference_status_endpoint():
    """Verify /api/v1/inference/status endpoint returns aggregated status."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/inference/status")
        assert response.status_code == 200
        data = response.json()
        assert "hardware" in data
        assert "inference" in data
        assert data["inference"]["provider"] in ["cuda", "rocm", "cpu"]


@pytest.mark.asyncio
async def test_compatibility_endpoint():
    """Verify /api/v1/inference/compatibility endpoint checks model compatibility."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/inference/compatibility?model=Qwen/Qwen2.5-3B-Instruct")
        assert response.status_code == 200
        data = response.json()
        assert "compatible" in data


@pytest.mark.asyncio
async def test_test_endpoint_api():
    """Verify /api/v1/inference/test-endpoint validates connectivity."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/inference/test-endpoint",
            json={"endpoint_url": "http://127.0.0.1:9999/v1", "provider": "custom"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "ok" in data
        assert data["ok"] is False

