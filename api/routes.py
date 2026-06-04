"""
api/routes.py — FastAPI routes for the invoice intelligence system.

Endpoints:
  POST /upload          — upload one or more invoice files
  POST /process         — process uploaded files, stream SSE progress
  POST /process-single  — process one file, return JSON directly
  GET  /invoices        — list all processed invoices
  GET  /stats           — dashboard stats
  POST /export          — download export file
  GET  /health          — health check
  GET  /admin/invoices  — admin: all invoices (protected)
  GET  /admin/stats     — admin: stats (protected)
"""

from __future__ import annotations
import uuid, json, asyncio, os
from pathlib import Path
from typing import AsyncGenerator

from fastapi import APIRouter, UploadFile, File, HTTPException, Header
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from loguru import logger

from config import settings
from models import ProcessedInvoice, InvoiceStatus
from agents.ledger import init_db, get_all_invoices, get_stats
from agents.pipeline import process_single
from agents.exporter import export_to_excel, export_to_csv, export_to_json

router = APIRouter()


def get_upload_dir() -> Path:
    for candidate in [Path("/tmp/invoice_uploads"), Path("./uploads")]:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except Exception:
            continue
    return Path("/tmp")


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health")
async def health():
    return {"status": "ok", "service": "Invoice Intelligence API"}


# ── Upload ────────────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_invoices(files: list[UploadFile] = File(...)):
    upload_dir = get_upload_dir()
    saved = []
    for file in files:
        ext = Path(file.filename).suffix.lower()
        if ext not in {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"}:
            raise HTTPException(400, f"Unsupported file type: {ext}")
        safe_name = f"{uuid.uuid4()}{ext}"
        path = upload_dir / safe_name
        path.write_bytes(await file.read())
        saved.append({"original": file.filename, "saved_as": safe_name})
        logger.info(f"[Upload] {file.filename} → {path}")
    return {"uploaded": saved, "count": len(saved)}


# ── SSE streaming process ─────────────────────────────────────────────────────

class ProcessRequest(BaseModel):
    filenames: list[str]
    export_fmt: str = "excel"


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/process")
async def process_invoices(req: ProcessRequest):
    upload_dir = get_upload_dir()
    file_paths = []
    for fname in req.filenames:
        p = upload_dir / fname
        if p.exists():
            file_paths.append(str(p))
        else:
            logger.warning(f"[Process] File not found: {p}")

    if not file_paths:
        raise HTTPException(400, "No valid files found. Upload files first.")

    async def stream() -> AsyncGenerator[str, None]:
        yield sse("start", {
            "total": len(file_paths),
            "message": f"Processing {len(file_paths)} invoice(s)…",
        })

        results: list[ProcessedInvoice] = []
        approved = needs_review = errors = 0

        for i, fp in enumerate(file_paths, 1):
            filename = Path(fp).name

            yield sse("progress", {
                "current": i, "total": len(file_paths),
                "filename": filename,
                "message": f"Extracting {filename}…",
                "stage": "extracting",
            })
            await asyncio.sleep(0)

            import concurrent.futures
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as pool:
                inv = await loop.run_in_executor(pool, process_single, fp)

            results.append(inv)

            if inv.status == InvoiceStatus.ERROR:
                errors += 1
            elif inv.status == InvoiceStatus.REVIEW:
                needs_review += 1
            else:
                approved += 1

            h = inv.extraction.header
            t = inv.extraction.totals
            v = inv.validation
            yield sse("result", {
                "invoice_id":      inv.invoice_id,
                "filename":        inv.filename,
                "current":         i,
                "total":           len(file_paths),
                "status":          inv.status.value,
                "confidence":      round(v.confidence, 3),
                "flags":           [f.value for f in v.flags],
                "vendor_name":     h.vendor_name,
                "invoice_number":  h.invoice_number,
                "invoice_date":    h.invoice_date,
                "currency":        h.currency,
                "grand_total":     t.grand_total,
                "line_item_count": len(inv.extraction.line_items),
                "error":           inv.error,
            })
            await asyncio.sleep(0)

        export_path = ""
        try:
            if req.export_fmt == "csv":
                export_path = export_to_csv(results)
            elif req.export_fmt == "json":
                export_path = export_to_json(results)
            else:
                export_path = export_to_excel(results)
        except Exception as e:
            logger.error(f"[Process] Export failed: {e}")

        yield sse("complete", {
            "total":        len(results),
            "approved":     approved,
            "needs_review": needs_review,
            "errors":       errors,
            "export_path":  export_path,
            "export_fmt":   req.export_fmt,
            "message":      f"Done! {approved} approved, {needs_review} need review.",
        })

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Single invoice (non-streaming) ────────────────────────────────────────────

@router.post("/process-single")
async def process_single_endpoint(files: list[UploadFile] = File(...)):
    upload_dir = get_upload_dir()
    file = files[0]
    ext  = Path(file.filename).suffix.lower()
    safe = f"{uuid.uuid4()}{ext}"
    path = upload_dir / safe
    path.write_bytes(await file.read())

    import concurrent.futures
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        inv = await loop.run_in_executor(pool, process_single, str(path))

    return inv.model_dump()


# ── Invoice history ───────────────────────────────────────────────────────────

@router.get("/invoices")
async def list_invoices(limit: int = 100):
    return get_all_invoices(limit)


@router.get("/stats")
async def dashboard_stats():
    return get_stats()


# ── Export download ───────────────────────────────────────────────────────────

class ExportRequest(BaseModel):
    invoice_ids: list[str] = []
    fmt: str = "excel"


@router.post("/export")
async def export_invoices(req: ExportRequest):
    from models import ExtractedInvoice, ValidationResult

    rows     = get_all_invoices(200)
    invoices = []
    for row in rows:
        if req.invoice_ids and row["invoice_id"] not in req.invoice_ids:
            continue
        try:
            inv = ProcessedInvoice(
                invoice_id = row["invoice_id"],
                filename   = row["filename"],
                status     = InvoiceStatus(row["status"]),
                created_at = row["created_at"],
                extraction = ExtractedInvoice.model_validate_json(row["extraction_json"]),
                validation = ValidationResult.model_validate_json(row["validation_json"]),
            )
            invoices.append(inv)
        except Exception as e:
            logger.warning(f"[Export] Skip {row['invoice_id']}: {e}")

    if not invoices:
        raise HTTPException(404, "No invoices found to export.")

    if req.fmt == "csv":
        path       = export_to_csv(invoices)
        media_type = "text/csv"
    elif req.fmt == "json":
        path       = export_to_json(invoices)
        media_type = "application/json"
    else:
        path       = export_to_excel(invoices)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    return FileResponse(path, media_type=media_type, filename=Path(path).name)


# ── Admin ─────────────────────────────────────────────────────────────────────

def _check_admin(key: str):
    if key != os.getenv("ADMIN_KEY", "changeme"):
        raise HTTPException(403, "Invalid admin key.")


@router.get("/admin/invoices")
async def admin_invoices(limit: int = 200, x_admin_key: str = Header(default="")):
    _check_admin(x_admin_key)
    return get_all_invoices(limit)


@router.get("/admin/stats")
async def admin_stats(x_admin_key: str = Header(default="")):
    _check_admin(x_admin_key)
    return get_stats()