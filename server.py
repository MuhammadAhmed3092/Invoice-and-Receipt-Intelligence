"""server.py — Local development server only. HF Spaces uses Dockerfile CMD."""
import os, sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

groq_key = os.getenv("GROQ_API_KEY", "")
if not groq_key or "your_key" in groq_key:
    print("\n  ERROR: GROQ_API_KEY not set in .env")
    print("  Get your free key at https://console.groq.com\n")
    sys.exit(1)

import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    env  = os.getenv("APP_ENV", "development")
    print(f"\n  Invoice Intelligence API ({env})")
    print(f"  API:  http://localhost:{port}")
    print(f"  Docs: http://localhost:{port}/docs\n")
    uvicorn.run(
        "api.app:app",
        host="0.0.0.0",
        port=port,
        reload=(env == "development"),
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )