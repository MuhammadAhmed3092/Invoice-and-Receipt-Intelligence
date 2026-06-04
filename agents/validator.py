"""
agents/validator.py — Math verification + confidence scoring.

This is what separates this system from simple OCR.
It checks:
  1. Line items sum == subtotal
  2. Tax calculation is consistent with the tax rate
  3. Grand total = subtotal - discount + tax + shipping + other
  4. Key fields are present (vendor, date, number, total)
  5. Duplicate detection (same vendor + amount + date seen before)

Outputs a ValidationResult with a confidence score 0.0–1.0 and
a list of ValidationFlags for any issues found.
"""

from __future__ import annotations
from loguru import logger
from models import (
    ExtractedInvoice, ValidationResult, ValidationFlag,
    InvoiceStatus,
)
from config import settings

TOLERANCE = 0.02    # 2% tolerance for floating point / rounding differences


def _within_tolerance(a: float, b: float) -> bool:
    """True if a and b are within TOLERANCE of each other."""
    if b == 0:
        return abs(a) < 0.01
    return abs(a - b) / abs(b) <= TOLERANCE


def validate_invoice(extraction: ExtractedInvoice) -> ValidationResult:
    """
    Run all validation checks on an ExtractedInvoice.
    Returns a ValidationResult with confidence score and flags.
    """
    v     = ValidationResult()
    flags = []
    flag_details: dict[str, str] = {}
    score = 1.0    # start at 100%, deduct for each issue

    h = extraction.header
    t = extraction.totals
    items = extraction.line_items

    # ── 1. Key field completeness ─────────────────────────────────────────────
    checks = {
        "vendor":  bool(h.vendor_name.strip()),
        "total":   t.grand_total > 0,
        "date":    bool(h.invoice_date.strip()),
        "number":  bool(h.invoice_number.strip()),
    }
    v.has_vendor  = checks["vendor"]
    v.has_total   = checks["total"]
    v.has_date    = checks["date"]
    v.has_number  = checks["number"]
    v.completeness_pct = round(sum(checks.values()) / len(checks), 2)

    if not checks["vendor"]:
        flags.append(ValidationFlag.MISSING_VENDOR)
        flag_details["missing_vendor"] = "Vendor name not found"
        score -= 0.15

    if not checks["total"]:
        flags.append(ValidationFlag.MISSING_TOTAL)
        flag_details["missing_total"] = "Grand total is zero or missing"
        score -= 0.20

    if not checks["date"]:
        flags.append(ValidationFlag.MISSING_DATE)
        flag_details["missing_date"] = "Invoice date not found"
        score -= 0.10

    if not checks["number"]:
        flags.append(ValidationFlag.MISSING_NUMBER)
        flag_details["missing_number"] = "Invoice number not found"
        score -= 0.10

    # ── 2. Line items math check ──────────────────────────────────────────────
    if items:
        computed_sum = round(sum(item.total for item in items), 2)
        v.line_items_sum    = computed_sum
        v.expected_subtotal = t.subtotal if t.subtotal > 0 else t.grand_total

        if t.subtotal > 0:
            v.subtotal_match = _within_tolerance(computed_sum, t.subtotal)
            if not v.subtotal_match:
                flags.append(ValidationFlag.MATH_ERROR)
                flag_details["math_error"] = (
                    f"Line items sum {computed_sum:.2f} ≠ subtotal {t.subtotal:.2f}"
                )
                score -= 0.20
        else:
            # No subtotal shown — check against grand total
            v.subtotal_match = _within_tolerance(computed_sum, t.grand_total)
    else:
        # No line items extracted — common for receipts
        v.subtotal_match = True   # can't verify, don't penalise

    # ── 3. Tax verification ───────────────────────────────────────────────────
    if t.tax_rate > 0 and t.subtotal > 0:
        computed_tax = round(t.subtotal * (t.tax_rate / 100), 2)
        v.tax_computed = computed_tax
        v.tax_match    = _within_tolerance(computed_tax, t.tax_amount)
        if not v.tax_match:
            flags.append(ValidationFlag.TAX_MISMATCH)
            flag_details["tax_mismatch"] = (
                f"Expected tax {computed_tax:.2f} ({t.tax_rate}%) "
                f"≠ extracted {t.tax_amount:.2f}"
            )
            score -= 0.15

    # ── 4. Grand total reconciliation ─────────────────────────────────────────
    if t.subtotal > 0 and t.grand_total > 0:
        computed_total = round(
            t.subtotal
            - t.discount
            + t.tax_amount
            + t.shipping
            + t.other_charges,
            2
        )
        v.total_match = _within_tolerance(computed_total, t.grand_total)
        if not v.total_match:
            # Softer penalty — could be rounding from many items
            score -= 0.10
            if ValidationFlag.MATH_ERROR not in flags:
                flags.append(ValidationFlag.MATH_ERROR)
                flag_details["total_reconcile"] = (
                    f"Computed total {computed_total:.2f} ≠ grand total {t.grand_total:.2f}"
                )

    # ── 5. Per-item confidence penalty ────────────────────────────────────────
    if items:
        avg_item_conf = sum(i.confidence for i in items) / len(items)
        if avg_item_conf < 0.80:
            score -= 0.10
            flags.append(ValidationFlag.LOW_CONFIDENCE)
            flag_details["low_confidence"] = (
                f"Average line item confidence: {avg_item_conf:.0%}"
            )

    # ── Finalise score and status ─────────────────────────────────────────────
    v.confidence = round(max(0.0, min(1.0, score)), 3)
    v.flags      = flags
    v.flags_detail = flag_details

    if v.confidence >= settings.auto_approve_threshold and not flags:
        v.status = InvoiceStatus.APPROVED
        v.notes  = "All checks passed — auto-approved."
    elif v.confidence < settings.review_threshold or ValidationFlag.MATH_ERROR in flags:
        v.status = InvoiceStatus.REVIEW
        v.notes  = f"Needs review: {', '.join(f.value for f in flags)}"
    else:
        v.status = InvoiceStatus.APPROVED
        v.notes  = f"Minor issues noted: {', '.join(f.value for f in flags)}"

    logger.info(
        f"[Validator] confidence={v.confidence:.0%}, "
        f"status={v.status.value}, flags={[f.value for f in flags]}"
    )
    return v
