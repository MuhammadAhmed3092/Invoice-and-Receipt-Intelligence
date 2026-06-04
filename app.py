## app.py — Hugging Face Spaces entry point
## HF Spaces looks for app.py in the root and runs it directly

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

# On HF Spaces, secrets are injected as env vars — no .env needed
# But load_dotenv is harmless if .env doesn't exist

from api.app import app  # noqa: F401 — uvicorn needs this import
