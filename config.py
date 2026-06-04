"""
config.py — All settings. Only GROQ_API_KEY is required.
Get your free key at https://console.groq.com
"""

import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Groq (free) ───────────────────────────────
    groq_api_key: str = ""
    # llama-4-scout: vision model, sees invoice images
    vision_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    # llama-3.1-8b: fast text model for validation notes
    text_model:   str = "llama-3.1-8b-instant"

    # ── Document processing ───────────────────────
    page_image_dpi:   int  = 150     # PDF render DPI
    max_image_size:   int  = 1024    # resize before sending to vision model
    ocr_enabled:      bool = True    # pytesseract fallback for scanned docs

    # ── Storage ───────────────────────────────────
    upload_dir: str = "/tmp/invoice_uploads"
    export_dir: str = "./exports"
    db_path:    str = "./invoices.db"

    # ── App ───────────────────────────────────────
    app_env:      str = "development"
    log_level:    str = "DEBUG"
    admin_key:    str = "changeme"
    prompt_limit: int = 20           # higher limit — this is a B2B tool

    # ── Confidence thresholds ─────────────────────
    auto_approve_threshold: float = 0.90  # >= this → auto-approved
    review_threshold:       float = 0.75  # < this → needs human review


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
