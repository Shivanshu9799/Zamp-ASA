"""Single source of truth for tolerances, rule metadata and environment settings."""
from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
REPO_ROOT = BASE_DIR.parent
SEED_DIR = BASE_DIR / "seed"
CACHE_DIR = Path(os.getenv("LLM_CACHE_DIR", BASE_DIR / "llm_cache"))
SAMPLES_DIR = Path(os.getenv("SAMPLES_DIR", REPO_ROOT / "samples"))
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", REPO_ROOT / "frontend" / "dist"))

# ---- environment ---------------------------------------------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
# Provider: set LLM_PROVIDER=anthropic|gemini, otherwise it follows whichever key is present (Anthropic wins a tie).
LLM_PROVIDER = (os.getenv("LLM_PROVIDER") or ("gemini" if GEMINI_API_KEY and not ANTHROPIC_API_KEY else "anthropic")).lower()
LLM_API_KEY = GEMINI_API_KEY if LLM_PROVIDER == "gemini" else ANTHROPIC_API_KEY
LLM_MODEL = os.getenv("LLM_MODEL") or ("gemini-3.5-flash-lite" if LLM_PROVIDER == "gemini" else "claude-sonnet-5-5")
LLM_MODE = os.getenv("LLM_MODE", "cached").lower()  # "live" | "cached"
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(BASE_DIR / 'data' / 'app.db').as_posix()}")
# Cosmetic pause between stages so the live stepper is watchable (set 0 in tests).
STAGE_DELAY_MS = int(os.getenv("STAGE_DELAY_MS", "450"))

# ---- the buyer -----------------------------------------------------------
BUYER_NAME = "Meridian Foods Pvt. Ltd."
BUYER_STATE_CODE = "27"  # Maharashtra
BUYER_GSTIN = "27AABCM4455R1Z9"

# ---- tolerances ----------------------------------------------------------
PRICE_TOLERANCE_PCT = Decimal("1.0")      # unit price vs PO, percent
TOTAL_ROUNDING_ABS = Decimal("1.00")      # INR, arithmetic rounding
QTY_TOLERANCE = Decimal("0")              # no over-billing on quantity
VENDOR_FUZZY_AUTO = 92                    # rapidfuzz score: auto-accept
VENDOR_FUZZY_REVIEW = 80                  # rapidfuzz score: send to a human
PO_INFERENCE_SUGGEST = 0.75               # candidate-PO score needed to suggest
DUP_DATE_WINDOW_DAYS = 10
DUP_INVOICE_NO_SIMILARITY = 85
EXTRACTION_MIN_CONFIDENCE = 0.80
CRITICAL_FIELDS = ["vendor_name", "invoice_number", "invoice_date", "total"]

# weights for PO inference (they sum to 1.0); vendor match is a hard gate, not a weight
PO_INFERENCE_WEIGHTS = {"description": 0.35, "qty_price": 0.25, "amount": 0.20, "date": 0.20}


def tolerances() -> dict:
    return {
        "PRICE_TOLERANCE_PCT": str(PRICE_TOLERANCE_PCT),
        "TOTAL_ROUNDING_ABS": str(TOTAL_ROUNDING_ABS),
        "QTY_TOLERANCE": str(QTY_TOLERANCE),
        "VENDOR_FUZZY_AUTO": VENDOR_FUZZY_AUTO,
        "VENDOR_FUZZY_REVIEW": VENDOR_FUZZY_REVIEW,
        "PO_INFERENCE_SUGGEST": PO_INFERENCE_SUGGEST,
        "DUP_DATE_WINDOW_DAYS": DUP_DATE_WINDOW_DAYS,
        "DUP_INVOICE_NO_SIMILARITY": DUP_INVOICE_NO_SIMILARITY,
        "EXTRACTION_MIN_CONFIDENCE": EXTRACTION_MIN_CONFIDENCE,
    }


# ---- rule catalogue (shown on the Rules page) ------------------------------
# on_fail: REJECT | SECURITY (pending, never auto-approved) | PENDING
RULES = [
    {"id": "R01", "stage": "validate", "name": "Required fields present", "on_fail": "PENDING",
     "plain": "Vendor, invoice number, invoice date and total must all be readable."},
    {"id": "R02", "stage": "extract", "name": "Extraction confidence & text cross-check", "on_fail": "PENDING",
     "plain": "Key fields must be read with ≥ 80% confidence and agree with the PDF's own text layer."},
    {"id": "R03", "stage": "validate", "name": "Line math & totals reconcile", "on_fail": "PENDING",
     "plain": "qty × price = amount, lines add up to the subtotal, subtotal + tax = total (within ₹1 rounding)."},
    {"id": "R04", "stage": "validate", "name": "GST structure valid", "on_fail": "PENDING",
     "plain": "CGST = SGST (intra-state) or IGST alone (inter-state), and tax = rate × taxable value."},
    {"id": "R05", "stage": "vendor", "name": "Vendor is in the vendor master", "on_fail": "REJECT / PENDING",
     "plain": "GSTIN exact match, or a very close name match. Unknown vendor → reject; borderline name → review."},
    {"id": "R06", "stage": "vendor", "name": "Bank details match vendor master", "on_fail": "SECURITY HOLD",
     "plain": "A changed bank account is a classic fraud signal, so it is never auto-approved."},
    {"id": "R07", "stage": "duplicate", "name": "Exact duplicate invoice", "on_fail": "REJECT",
     "plain": "Same vendor and same invoice number already processed."},
    {"id": "R08", "stage": "duplicate", "name": "Probable duplicate (fuzzy)", "on_fail": "REJECT / PENDING",
     "plain": "Same vendor, same total, close date and near-identical invoice number — or the very same file."},
    {"id": "R09", "stage": "po_match", "name": "PO exists and belongs to the vendor", "on_fail": "→ R10",
     "plain": "If the PO is missing or wrong we try to infer it instead of guessing."},
    {"id": "R10", "stage": "po_match", "name": "PO inference for invoices without a PO", "on_fail": "PENDING",
     "plain": "Scores the vendor's open POs; a human confirms the suggestion — we never auto-pick."},
    {"id": "R11", "stage": "po_match", "name": "Unit price within tolerance of PO", "on_fail": "PENDING",
     "plain": "Invoice price per unit must be within 1% of the PO price."},
    {"id": "R12", "stage": "po_match", "name": "3-way match: billed ≤ received − already billed", "on_fail": "PENDING",
     "plain": "For goods, we only pay for what the warehouse has actually received and not yet billed."},
    {"id": "R13", "stage": "po_match", "name": "Cumulative billing within PO value", "on_fail": "PENDING",
     "plain": "Approved invoices to date + this invoice cannot exceed the PO amount."},
    {"id": "R14", "stage": "po_match", "name": "Currency matches PO", "on_fail": "PENDING",
     "plain": "Invoice currency must equal the PO currency."},
    {"id": "R15", "stage": "validate", "name": "Total is positive", "on_fail": "REJECT",
     "plain": "Zero or negative totals are rejected (credit notes are out of scope)."},
    {"id": "R16", "stage": "validate", "name": "Invoice is addressed to the buyer", "on_fail": "PENDING",
     "plain": "The bill-to name must match Meridian Foods Pvt. Ltd. (≥ 80%): a valid PO number is not proof of addressee."},
]

STAGES = [
    ("intake", "Intake"),
    ("extract", "Extract"),
    ("validate", "Validate"),
    ("vendor", "Vendor"),
    ("duplicate", "Duplicate"),
    ("po_match", "PO match"),
    ("decision", "Decision"),
    ("explain", "Next action"),
]
STAGE_KEYS = [k for k, _ in STAGES]
