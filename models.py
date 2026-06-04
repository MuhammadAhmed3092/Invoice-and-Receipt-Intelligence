"""
models.py — All Pydantic data models for the invoice pipeline.

Hierarchy:
  LineItem          → one row in the invoice table
  InvoiceHeader     → vendor, buyer, dates, invoice number
  InvoiceTotals     → subtotal, tax, discount, grand total
  ExtractedInvoice  → full extraction result (header + items + totals)
  ValidationResult  → math checks + confidence score
  ProcessedInvoice  → final output combining extraction + validation
  BatchResult       → result of processing multiple invoices at once
"""

from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field
import uuid


# ── Enums ─────────────────────────────────────────────────────────────────────

class InvoiceStatus(str, Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    APPROVED   = "approved"    # confidence >= 0.90, math checks pass
    REVIEW     = "review"      # confidence < 0.75 or math mismatch
    DONE       = "done"
    ERROR      = "error"


class DocumentType(str, Enum):
    INVOICE    = "invoice"
    RECEIPT    = "receipt"
    CREDIT_NOTE = "credit_note"
    PURCHASE_ORDER = "purchase_order"
    UNKNOWN    = "unknown"


class ValidationFlag(str, Enum):
    MATH_ERROR         = "math_error"         # line items don't sum to subtotal
    TAX_MISMATCH       = "tax_mismatch"       # tax % doesn't match extracted tax
    MISSING_VENDOR     = "missing_vendor"     # vendor name not found
    MISSING_TOTAL      = "missing_total"      # grand total not found
    MISSING_DATE       = "missing_date"       # invoice date not found
    MISSING_NUMBER     = "missing_number"     # invoice number not found
    DUPLICATE_POSSIBLE = "duplicate_possible" # same vendor+amount+date seen before
    LOW_CONFIDENCE     = "low_confidence"     # vision model uncertain


# ── Core extraction models ─────────────────────────────────────────────────────

class LineItem(BaseModel):
    """One line item row from the invoice table."""
    description: str  = ""
    quantity:    float = 1.0
    unit:        str  = ""        # "pcs", "hrs", "kg", etc.
    unit_price:  float = 0.0
    total:       float = 0.0
    confidence:  float = 1.0      # per-item confidence from vision model


class InvoiceHeader(BaseModel):
    """Top section of the invoice — vendor, buyer, reference numbers."""
    # Vendor (seller)
    vendor_name:    str = ""
    vendor_address: str = ""
    vendor_tax_id:  str = ""      # VAT/TRN number (important for UAE/KSA)
    vendor_email:   str = ""
    vendor_phone:   str = ""

    # Buyer
    buyer_name:     str = ""
    buyer_address:  str = ""
    buyer_tax_id:   str = ""

    # Invoice reference
    invoice_number: str = ""
    invoice_date:   str = ""      # ISO format where possible: YYYY-MM-DD
    due_date:       str = ""
    po_number:      str = ""      # purchase order reference

    # Document classification
    document_type:  DocumentType = DocumentType.INVOICE
    currency:       str = "USD"   # USD, AED, SAR, GBP, etc.
    language:       str = "en"    # "en", "ar", "mixed"


class InvoiceTotals(BaseModel):
    """Financial totals section."""
    subtotal:       float = 0.0
    discount:       float = 0.0
    discount_pct:   float = 0.0   # percentage if shown
    tax_amount:     float = 0.0
    tax_rate:       float = 0.0   # percentage (e.g. 5.0 for UAE 5% VAT)
    tax_label:      str   = ""    # "VAT", "GST", "Sales Tax"
    shipping:       float = 0.0
    other_charges:  float = 0.0
    grand_total:    float = 0.0
    amount_paid:    float = 0.0
    amount_due:     float = 0.0


class ExtractedInvoice(BaseModel):
    """Raw extraction output from the vision model — not yet validated."""
    header:     InvoiceHeader         = Field(default_factory=InvoiceHeader)
    line_items: list[LineItem]        = Field(default_factory=list)
    totals:     InvoiceTotals         = Field(default_factory=InvoiceTotals)
    raw_text:   str                   = ""   # full OCR/extracted text
    notes:      str                   = ""   # any footer notes, payment terms
    model_used: str                   = ""


# ── Validation model ───────────────────────────────────────────────────────────

class ValidationResult(BaseModel):
    """
    Result of running math checks and completeness checks.
    This is what separates this system from simple OCR — we verify the numbers.
    """
    confidence:      float            = 0.0   # 0.0 – 1.0
    status:          InvoiceStatus    = InvoiceStatus.REVIEW
    flags:           list[ValidationFlag] = Field(default_factory=list)
    flags_detail:    dict[str, str]   = Field(default_factory=dict)

    # Math verification
    line_items_sum:  float = 0.0     # what we computed
    expected_subtotal: float = 0.0  # what the invoice says
    subtotal_match:  bool  = False
    tax_computed:    float = 0.0
    tax_match:       bool  = False
    total_match:     bool  = False

    # Completeness
    has_vendor:      bool = False
    has_total:       bool = False
    has_date:        bool = False
    has_number:      bool = False
    completeness_pct: float = 0.0   # % of key fields present

    notes: str = ""


# ── Final processed invoice ────────────────────────────────────────────────────

class ProcessedInvoice(BaseModel):
    """
    The complete output for one invoice — extraction + validation.
    This is what gets saved to SQLite and returned to the frontend.
    """
    invoice_id:  str = Field(default_factory=lambda: str(uuid.uuid4()))
    filename:    str = ""
    file_path:   str = ""
    page_count:  int = 1

    extraction:  ExtractedInvoice  = Field(default_factory=ExtractedInvoice)
    validation:  ValidationResult  = Field(default_factory=ValidationResult)

    status:      InvoiceStatus     = InvoiceStatus.PENDING
    error:       str               = ""
    created_at:  str               = ""

    def to_flat_dict(self) -> dict[str, Any]:
        """
        Flatten to a single dict for CSV/Excel export.
        One row per invoice (line items serialised as JSON string).
        """
        h = self.extraction.header
        t = self.extraction.totals
        v = self.validation
        return {
            "invoice_id":     self.invoice_id,
            "filename":       self.filename,
            "status":         self.status.value,
            "confidence":     round(v.confidence, 3),
            "flags":          ", ".join(f.value for f in v.flags),
            "vendor_name":    h.vendor_name,
            "vendor_tax_id":  h.vendor_tax_id,
            "buyer_name":     h.buyer_name,
            "invoice_number": h.invoice_number,
            "invoice_date":   h.invoice_date,
            "due_date":       h.due_date,
            "currency":       h.currency,
            "subtotal":       t.subtotal,
            "tax_rate":       t.tax_rate,
            "tax_amount":     t.tax_amount,
            "discount":       t.discount,
            "grand_total":    t.grand_total,
            "amount_due":     t.amount_due,
            "line_item_count": len(self.extraction.line_items),
            "notes":          self.extraction.notes,
        }


# ── Batch result ──────────────────────────────────────────────────────────────

class BatchResult(BaseModel):
    """Result of processing multiple invoices in one job."""
    batch_id:      str = Field(default_factory=lambda: str(uuid.uuid4()))
    total:         int = 0
    approved:      int = 0
    needs_review:  int = 0
    errors:        int = 0
    invoices:      list[ProcessedInvoice] = Field(default_factory=list)
    export_path:   str = ""    # path to the generated Excel/CSV

    @property
    def approval_rate(self) -> float:
        return round(self.approved / self.total, 3) if self.total > 0 else 0.0


# ── SSE progress event ────────────────────────────────────────────────────────

class ProgressEvent(BaseModel):
    """Streamed to the frontend during processing."""
    event:      str            # "uploading" | "extracting" | "validating" | "done" | "error"
    message:    str
    filename:   str  = ""
    current:    int  = 0       # current file number in batch
    total:      int  = 0       # total files in batch
    confidence: float = 0.0
    status:     str  = ""
    data:       dict[str, Any] = Field(default_factory=dict)
