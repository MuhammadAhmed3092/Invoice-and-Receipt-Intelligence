"""
agents/exporter.py — Exports processed invoices to CSV, Excel, and JSON.
Excel output includes two sheets: Summary + Line Items.
"""

from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone
from loguru import logger
from models import ProcessedInvoice, BatchResult
from config import settings


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def export_to_json(invoices: list[ProcessedInvoice]) -> str:
    out_dir = Path(settings.export_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"invoices_{_timestamp()}.json"
    data = [inv.model_dump() for inv in invoices]
    path.write_text(json.dumps(data, indent=2, default=str))
    logger.info(f"[Exporter] JSON → {path}")
    return str(path)


def export_to_csv(invoices: list[ProcessedInvoice]) -> str:
    import pandas as pd
    out_dir = Path(settings.export_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"invoices_{_timestamp()}.csv"
    rows = [inv.to_flat_dict() for inv in invoices]
    pd.DataFrame(rows).to_csv(path, index=False)
    logger.info(f"[Exporter] CSV → {path} ({len(rows)} rows)")
    return str(path)


def export_to_excel(invoices: list[ProcessedInvoice]) -> str:
    """
    Two-sheet Excel workbook:
      Sheet 1 — Summary (one row per invoice)
      Sheet 2 — Line Items (one row per line item, with invoice_id FK)
    """
    import pandas as pd
    out_dir = Path(settings.export_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"invoices_{_timestamp()}.xlsx"

    summary_rows = [inv.to_flat_dict() for inv in invoices]

    line_item_rows = []
    for inv in invoices:
        for item in inv.extraction.line_items:
            line_item_rows.append({
                "invoice_id":   inv.invoice_id,
                "vendor_name":  inv.extraction.header.vendor_name,
                "invoice_date": inv.extraction.header.invoice_date,
                "description":  item.description,
                "quantity":     item.quantity,
                "unit":         item.unit,
                "unit_price":   item.unit_price,
                "total":        item.total,
                "confidence":   round(item.confidence, 3),
            })

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(summary_rows).to_excel(
            writer, sheet_name="Invoice Summary", index=False
        )
        if line_item_rows:
            pd.DataFrame(line_item_rows).to_excel(
                writer, sheet_name="Line Items", index=False
            )

    logger.info(f"[Exporter] Excel → {path} ({len(summary_rows)} invoices)")
    return str(path)


def export_batch(batch: BatchResult, fmt: str = "excel") -> str:
    """Export a full batch result. fmt: 'excel' | 'csv' | 'json'"""
    invoices = [inv for inv in batch.invoices if inv.status.value != "error"]
    if fmt == "csv":
        return export_to_csv(invoices)
    elif fmt == "json":
        return export_to_json(invoices)
    else:
        return export_to_excel(invoices)
