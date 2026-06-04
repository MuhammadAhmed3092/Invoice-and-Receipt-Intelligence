"""
agents/ledger.py — SQLite ledger for all processed invoices.

Stores every invoice with its extraction + validation results.
Used for duplicate detection, history, and batch export.
"""

from __future__ import annotations
import sqlite3
import json
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone
from loguru import logger
from config import settings
from models import ProcessedInvoice, InvoiceStatus


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn():
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS invoices (
            invoice_id     TEXT PRIMARY KEY,
            filename       TEXT NOT NULL,
            status         TEXT NOT NULL,
            confidence     REAL DEFAULT 0,
            vendor_name    TEXT DEFAULT '',
            invoice_number TEXT DEFAULT '',
            invoice_date   TEXT DEFAULT '',
            currency       TEXT DEFAULT 'USD',
            grand_total    REAL DEFAULT 0,
            flags          TEXT DEFAULT '',
            extraction_json TEXT NOT NULL,
            validation_json TEXT NOT NULL,
            created_at     TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_vendor
            ON invoices(vendor_name);
        CREATE INDEX IF NOT EXISTS idx_date
            ON invoices(invoice_date);
        CREATE INDEX IF NOT EXISTS idx_status
            ON invoices(status);
        """)
    logger.info(f"[Ledger] DB ready at {settings.db_path}")


def save_invoice(inv: ProcessedInvoice) -> None:
    h = inv.extraction.header
    v = inv.validation
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO invoices
               (invoice_id, filename, status, confidence, vendor_name,
                invoice_number, invoice_date, currency, grand_total,
                flags, extraction_json, validation_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                inv.invoice_id,
                inv.filename,
                inv.status.value,
                v.confidence,
                h.vendor_name,
                h.invoice_number,
                h.invoice_date,
                h.currency,
                inv.extraction.totals.grand_total,
                json.dumps([f.value for f in v.flags]),
                inv.extraction.model_dump_json(),
                v.model_dump_json(),
                inv.created_at or utcnow(),
            )
        )


def is_duplicate(vendor: str, total: float, date: str) -> bool:
    """Check if we've seen this vendor + amount + date before."""
    if not vendor or total <= 0:
        return False
    with get_conn() as conn:
        row = conn.execute(
            """SELECT invoice_id FROM invoices
               WHERE vendor_name = ? AND grand_total = ? AND invoice_date = ?
               LIMIT 1""",
            (vendor, total, date)
        ).fetchone()
    return row is not None


def get_all_invoices(limit: int = 200) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM invoices ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    with get_conn() as conn:
        total    = conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]
        approved = conn.execute(
            "SELECT COUNT(*) FROM invoices WHERE status='approved'"
        ).fetchone()[0]
        review   = conn.execute(
            "SELECT COUNT(*) FROM invoices WHERE status='review'"
        ).fetchone()[0]
        total_val = conn.execute(
            "SELECT SUM(grand_total) FROM invoices WHERE status='approved'"
        ).fetchone()[0] or 0
    return {
        "total_invoices": total,
        "approved":       approved,
        "needs_review":   review,
        "total_value":    round(total_val, 2),
        "approval_rate":  round(approved / total, 3) if total > 0 else 0,
    }
