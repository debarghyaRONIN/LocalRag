from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from prometheus_client import make_asgi_app

from backend.app.core.config import settings
from backend.app.db.session import init_db
from backend.app.api.v1.health import router as health_router
from backend.app.api.v1.documents import router as documents_router
from backend.app.api.v1.sessions import router as sessions_router
from backend.app.api.v1.query import router as query_router
from backend.app.api.v1.inference import router as inference_router
from backend.app.api.v1.feedback import router as feedback_router
from backend.app.api.v1.compliance import router as compliance_router
from backend.app.api.v1.indexing import router as indexing_router
from backend.app.api.v1.benchmarks import router as benchmarks_router
from backend.app.api.v1.openai_gateway import router as openai_gateway_router, admin_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure tables exist
    await init_db()
    # Recover any crashed indexing jobs from previous run
    try:
        from backend.app.services.indexing.job_manager import get_job_manager
        await get_job_manager().resume_crashed_jobs()
    except Exception:
        pass
    yield
    # Shutdown logic
    try:
        from backend.app.api.v1.health import vllm_client
        await vllm_client.aclose()
    except Exception:
        pass


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Production-Grade Local RAG System with Hybrid Search, ONNX Reranking, and Offline Citations",
    lifespan=lifespan,
)

# CORS configuration for local development and Tauri desktop app
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://tauri.localhost",
        "https://tauri.localhost",
        "tauri://localhost",
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
    ],
    allow_origin_regex=r"^(https?://(localhost|127\.0\.0\.1|tauri\.localhost)(:\d+)?|tauri://.*)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API v1 routes
app.include_router(health_router, prefix="/api/v1", tags=["Health"])
app.include_router(documents_router, prefix="/api/v1", tags=["Documents"])
app.include_router(sessions_router, prefix="/api/v1", tags=["Sessions"])
app.include_router(query_router, prefix="/api/v1", tags=["Query"])
app.include_router(inference_router, prefix="/api/v1", tags=["Inference"])
app.include_router(feedback_router, prefix="/api/v1", tags=["Feedback"])
app.include_router(compliance_router, prefix="/api/v1", tags=["Compliance"])
app.include_router(indexing_router, prefix="/api/v1", tags=["Indexing"])
app.include_router(benchmarks_router, prefix="/api/v1", tags=["Benchmarks"])

# Mount Standard & Sovereign Sealed API endpoints
app.include_router(openai_gateway_router, prefix="/v1", tags=["Standard & Sealed Gateway"])
app.include_router(admin_router, prefix="/admin", tags=["Admin & Egress"])

# Prometheus Metrics
if settings.ENABLE_METRICS:
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)

# Serve built React frontend if available
dist_candidates = [
    settings.BASE_DIR / "frontend" / "dist",
    Path("/app/frontend/dist"),
    Path("frontend/dist"),
    Path("./dist"),
]
dist_dir = next((p for p in dist_candidates if p.exists() and (p / "index.html").exists()), None)

if dist_dir:
    app.mount("/assets", StaticFiles(directory=dist_dir / "assets"), name="static_assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = dist_dir / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(dist_dir / "index.html")

