"""api/app.py — FastAPI application factory."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Works locally (.env file) and on HF Spaces (env vars injected directly)
load_dotenv(Path(__file__).parent.parent / ".env", override=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router
from agents.ledger import init_db


def create_app() -> FastAPI:
    app = FastAPI(
        title="Invoice Intelligence API",
        description="AI-powered invoice extraction, validation & export",
        version="1.0.0",
    )

    # Allow your Vercel frontend domain
    frontend_url = os.getenv("FRONTEND_URL", "*")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],   # tighten to frontend_url after deploy
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def startup():
        init_db()
        os.makedirs(os.getenv("EXPORT_DIR", "./exports"), exist_ok=True)
        os.makedirs("/tmp/invoice_uploads", exist_ok=True)

    app.include_router(router, prefix="/api")
    return app


app = create_app()