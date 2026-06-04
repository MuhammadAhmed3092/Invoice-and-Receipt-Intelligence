"""
agents/pipeline.py — Orchestrates the full invoice processing pipeline.

For each file:
  1. document_processor → page images + text
  2. extractor          → vision LLM → structured JSON
  3. duplicate check    → against SQLite ledger
  4. validator          → math checks + confidence score
  5. ledger.save        → persist to SQLite
  6. return ProcessedInvoice

For batches, runs each file sequentially and emits SSE progress events.
"""

from __future__ import annotations
import uuid
from datetime import datetime, timezone
from pathlib import Path
from loguru import logger

from models import (
    ProcessedInvoice, BatchResult,
    InvoiceStatus, ValidationFlag, ProgressEvent,
)
from agents.document_processor import process_document
from agents.extractor import extract_invoice
from agents.validator import validate_invoice
from agents.ledger import save_invoice, is_duplicate, init_db
from agents.exporter import export_batch
from config import settings


def process_single(file_path: str | Path) -> ProcessedInvoice:
    """Process one invoice file end-to-end. Returns a ProcessedInvoice."""
    path = Path(file_path)
    inv  = ProcessedInvoice(
        invoice_id = str(uuid.uuid4()),
        filename   = path.name,
        file_path  = str(path),
        created_at = datetime.now(timezone.utc).isoformat(),
        status     = InvoiceStatus.PROCESSING,
    )

    try:
        # Step 1 — document processor
        logger.info(f"[Pipeline] Processing: {path.name}")
        doc = process_document(path)
        inv.page_count = len(doc.pages)

        # Step 2 — vision extraction
        inv.extraction = extract_invoice(doc)

        # Step 3 — duplicate check
        h = inv.extraction.header
        t = inv.extraction.totals
        if is_duplicate(h.vendor_name, t.grand_total, h.invoice_date):
            inv.validation.flags.append(ValidationFlag.DUPLICATE_POSSIBLE)
            logger.warning(f"[Pipeline] Possible duplicate: {h.vendor_name} {t.grand_total}")

        # Step 4 — validate
        inv.validation = validate_invoice(inv.extraction)

        # Re-check duplicate flag (validator may have cleared flags)
        if ValidationFlag.DUPLICATE_POSSIBLE not in inv.validation.flags and \
           is_duplicate(h.vendor_name, t.grand_total, h.invoice_date):
            inv.validation.flags.append(ValidationFlag.DUPLICATE_POSSIBLE)
            inv.validation.confidence = round(
                max(0.0, inv.validation.confidence - 0.10), 3
            )

        inv.status = inv.validation.status

        # Step 5 — persist
        save_invoice(inv)
        logger.info(
            f"[Pipeline] Done: {path.name} | "
            f"status={inv.status.value} | "
            f"confidence={inv.validation.confidence:.0%}"
        )

    except Exception as e:
        logger.error(f"[Pipeline] Error on {path.name}: {e}")
        inv.status = InvoiceStatus.ERROR
        inv.error  = str(e)

    return inv


def process_batch(
    file_paths: list[str | Path],
    export_fmt: str = "excel",
    progress_callback=None,    # optional: callable(ProgressEvent)
) -> BatchResult:
    """
    Process a list of invoice files as a batch.

    progress_callback: called after each file with a ProgressEvent.
    Returns a BatchResult with all invoices + export path.
    """
    init_db()
    batch = BatchResult(
        batch_id = str(uuid.uuid4()),
        total    = len(file_paths),
    )

    for i, fp in enumerate(file_paths, 1):
        filename = Path(fp).name

        # Emit start event
        if progress_callback:
            progress_callback(ProgressEvent(
                event   = "extracting",
                message = f"Processing {filename}",
                filename = filename,
                current = i,
                total   = batch.total,
            ))

        inv = process_single(fp)
        batch.invoices.append(inv)

        if inv.status == InvoiceStatus.ERROR:
            batch.errors += 1
        elif inv.status == InvoiceStatus.REVIEW:
            batch.needs_review += 1
        else:
            batch.approved += 1

        # Emit per-file completion event
        if progress_callback:
            progress_callback(ProgressEvent(
                event      = "done" if i == batch.total else "extracting",
                message    = f"{'Done' if i == batch.total else 'Processed'}: {filename}",
                filename   = filename,
                current    = i,
                total      = batch.total,
                confidence = inv.validation.confidence,
                status     = inv.status.value,
                data       = {"invoice_id": inv.invoice_id},
            ))

    # Export results
    if batch.invoices:
        batch.export_path = export_batch(batch, fmt=export_fmt)

    logger.info(
        f"[Pipeline] Batch done: {batch.total} files | "
        f"approved={batch.approved} | review={batch.needs_review} | "
        f"errors={batch.errors} | export={batch.export_path}"
    )
    return batch
