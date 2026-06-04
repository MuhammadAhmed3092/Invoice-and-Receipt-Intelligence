"""
agents/extractor.py — Vision extraction engine.

Sends the invoice page image + OCR text to Groq's vision model and
returns a fully structured ExtractedInvoice Pydantic object.

Key design decisions:
- Sends image AND text together → model cross-references both
- Asks for JSON output with a strict schema → no parsing guesswork
- Single prompt covers header + line items + totals in one call
  (saves Groq API quota vs separate calls)
- Strips markdown fences from response before JSON parsing
"""

from __future__ import annotations
import json
import re
from loguru import logger
from groq import Groq

from config import settings
from models import (
    ExtractedInvoice, InvoiceHeader, InvoiceTotals,
    LineItem, DocumentType,
)
from agents.document_processor import DocumentResult


# ── Prompt ────────────────────────────────────────────────────────────────────

EXTRACTION_SYSTEM = """You are an expert invoice data extraction system.
You will receive an invoice image and any available OCR text.
Extract ALL fields and return ONLY valid JSON — no explanation, no markdown fences.

Return this exact JSON structure:
{
  "document_type": "invoice|receipt|credit_note|purchase_order|unknown",
  "language": "en|ar|mixed",
  "header": {
    "vendor_name": "",
    "vendor_address": "",
    "vendor_tax_id": "",
    "vendor_email": "",
    "vendor_phone": "",
    "buyer_name": "",
    "buyer_address": "",
    "buyer_tax_id": "",
    "invoice_number": "",
    "invoice_date": "",
    "due_date": "",
    "po_number": "",
    "currency": "USD"
  },
  "line_items": [
    {
      "description": "",
      "quantity": 1.0,
      "unit": "",
      "unit_price": 0.0,
      "total": 0.0,
      "confidence": 1.0
    }
  ],
  "totals": {
    "subtotal": 0.0,
    "discount": 0.0,
    "discount_pct": 0.0,
    "tax_amount": 0.0,
    "tax_rate": 0.0,
    "tax_label": "VAT",
    "shipping": 0.0,
    "other_charges": 0.0,
    "grand_total": 0.0,
    "amount_paid": 0.0,
    "amount_due": 0.0
  },
  "notes": ""
}

Rules:
- All monetary values must be numbers (not strings). Use 0.0 if not found.
- invoice_date and due_date: use YYYY-MM-DD format where possible.
- currency: use ISO 4217 codes (USD, AED, SAR, GBP, EUR, PKR etc.)
- For Arabic invoices, still return field names in English, values as-is.
- If a field is genuinely absent, use empty string "" or 0.0.
- Never invent data. If unclear, use empty string.
- Return ONLY the JSON object. No other text."""


def _build_user_message(doc: DocumentResult) -> list[dict]:
    """
    Build the Groq vision API message — image + text combined.
    For multi-page invoices, sends the first page image (usually has
    all header info) plus full text from all pages.
    """
    parts: list[dict] = []

    # Add the first page image (primary visual signal)
    if doc.first_page_b64:
        parts.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{doc.first_page_b64}"
            }
        })

    # Add OCR/text as supporting context
    text_context = f"OCR/extracted text from document:\n{doc.all_text[:3000]}" if doc.all_text.strip() else "No text layer available — extract from image only."
    parts.append({"type": "text", "text": text_context})

    return parts


def _parse_response(raw: str) -> dict:
    """Strip markdown fences and parse JSON safely."""
    # Remove ```json ... ``` or ``` ... ```
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    raw = raw.strip()

    # Find the JSON object if surrounded by other text
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        raw = match.group(0)

    return json.loads(raw)


def extract_invoice(doc: DocumentResult) -> ExtractedInvoice:
    """
    Main entry point — runs the vision model on a processed document
    and returns a structured ExtractedInvoice.
    """
    logger.info(f"[Extractor] Processing: {doc.filename}")

    client = Groq(api_key=settings.groq_api_key)

    try:
        response = client.chat.completions.create(
            model=settings.vision_model,
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM},
                {"role": "user",   "content": _build_user_message(doc)},
            ],
            temperature=0.0,    # deterministic extraction
            max_tokens=2048,
        )

        raw  = response.choices[0].message.content
        data = _parse_response(raw)

        # Build Pydantic models from parsed JSON
        header_data = data.get("header", {})
        header = InvoiceHeader(
            vendor_name    = header_data.get("vendor_name", ""),
            vendor_address = header_data.get("vendor_address", ""),
            vendor_tax_id  = header_data.get("vendor_tax_id", ""),
            vendor_email   = header_data.get("vendor_email", ""),
            vendor_phone   = header_data.get("vendor_phone", ""),
            buyer_name     = header_data.get("buyer_name", ""),
            buyer_address  = header_data.get("buyer_address", ""),
            buyer_tax_id   = header_data.get("buyer_tax_id", ""),
            invoice_number = header_data.get("invoice_number", ""),
            invoice_date   = header_data.get("invoice_date", ""),
            due_date       = header_data.get("due_date", ""),
            po_number      = header_data.get("po_number", ""),
            document_type  = DocumentType(data.get("document_type", "invoice")),
            currency       = header_data.get("currency", "USD"),
            language       = data.get("language", "en"),
        )

        line_items = [
            LineItem(
                description = item.get("description", ""),
                quantity    = float(item.get("quantity", 1.0)),
                unit        = item.get("unit", ""),
                unit_price  = float(item.get("unit_price", 0.0)),
                total       = float(item.get("total", 0.0)),
                confidence  = float(item.get("confidence", 1.0)),
            )
            for item in data.get("line_items", [])
        ]

        totals_data = data.get("totals", {})
        totals = InvoiceTotals(
            subtotal      = float(totals_data.get("subtotal", 0.0)),
            discount      = float(totals_data.get("discount", 0.0)),
            discount_pct  = float(totals_data.get("discount_pct", 0.0)),
            tax_amount    = float(totals_data.get("tax_amount", 0.0)),
            tax_rate      = float(totals_data.get("tax_rate", 0.0)),
            tax_label     = totals_data.get("tax_label", ""),
            shipping      = float(totals_data.get("shipping", 0.0)),
            other_charges = float(totals_data.get("other_charges", 0.0)),
            grand_total   = float(totals_data.get("grand_total", 0.0)),
            amount_paid   = float(totals_data.get("amount_paid", 0.0)),
            amount_due    = float(totals_data.get("amount_due", 0.0)),
        )

        result = ExtractedInvoice(
            header     = header,
            line_items = line_items,
            totals     = totals,
            raw_text   = doc.full_text[:2000],
            notes      = data.get("notes", ""),
            model_used = settings.vision_model,
        )

        logger.info(
            f"[Extractor] Done: vendor='{header.vendor_name}', "
            f"total={totals.grand_total} {header.currency}, "
            f"items={len(line_items)}"
        )
        return result

    except Exception as e:
        logger.error(f"[Extractor] Failed for {doc.filename}: {e}")
        return ExtractedInvoice(
            raw_text   = doc.full_text[:500],
            model_used = settings.vision_model,
        )
