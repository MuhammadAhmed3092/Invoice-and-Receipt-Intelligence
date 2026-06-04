"""api/app.py — FastAPI serves both the API and the React frontend."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from api.routes import router
from agents.ledger import init_db


def create_app() -> FastAPI:
    app = FastAPI(
        title="Invoice Intelligence API",
        description="AI-powered invoice extraction, validation & export",
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def startup():
        init_db()
        os.makedirs(os.getenv("EXPORT_DIR", "./exports"), exist_ok=True)
        os.makedirs("/tmp/invoice_uploads", exist_ok=True)

    # API routes
    app.include_router(router, prefix="/api")

    # Serve React frontend static files if the build exists
    frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")

        @app.get("/")
        async def serve_frontend():
            return FileResponse(str(frontend_dist / "index.html"))

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            """Serve index.html for all non-API routes (SPA routing)."""
            file_path = frontend_dist / full_path
            if file_path.exists() and file_path.is_file():
                return FileResponse(str(file_path))
            return FileResponse(str(frontend_dist / "index.html"))

    return app


app = create_app()