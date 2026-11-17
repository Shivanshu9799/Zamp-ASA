"""Pydantic schemas.

Two views of an invoice:
  * LLMInvoice       – what the model returns (all amounts are strings; this is also the tool schema)
  * ExtractedInvoice – the normalised version used by the rules (Decimal money, real dates)
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---------------- LLM-facing (raw) ----------------
class BankDetails(BaseModel):
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    ifsc: Optional[str] = None


class RawLine(BaseModel):
    description: str = ""
    sku: Optional[str] = None
    hsn: Optional[str] = Field(None, description="HSN/SAC code if printed")
    quantity: Optional[str] = None
    uom: Optional[str] = None
    unit_price: Optional[str] = None
    amount: Optional[str] = None
    tax_rate: Optional[str] = Field(None, description="GST rate in percent, e.g. '18'")


class RawTaxLine(BaseModel):
    type: Literal["CGST", "SGST", "IGST", "OTHER"]
    rate: Optional[str] = Field(None, description="Rate in percent, e.g. '9'")
    amount: Optional[str] = None


class LLMInvoice(BaseModel):
    vendor_name: Optional[str] = None
    vendor_gstin: Optional[str] = None
    vendor_address: Optional[str] = None
    vendor_bank: BankDetails = Field(default_factory=BankDetails)
    bill_to_name: Optional[str] = None
    invoice_number: Optional[str] = Field(None, description="Exactly as printed, do not reformat")
    invoice_date: Optional[str] = Field(None, description="ISO 8601 YYYY-MM-DD")
    due_date: Optional[str] = Field(None, description="ISO 8601 YYYY-MM-DD")
    payment_terms: Optional[str] = None
    po_number: Optional[str] = Field(None, description="Only if a PO number is printed; else null")
    po_reference_text: Optional[str] = Field(
        None, description="Free text that refers to an order without a number, e.g. 'your order dated 02-Oct-2026'")
    currency: Optional[str] = Field(None, description="ISO code, e.g. INR")
    line_items: list[RawLine] = Field(default_factory=list)
    subtotal: Optional[str] = Field(None, description="Taxable value before tax")
    tax_lines: list[RawTaxLine] = Field(default_factory=list)
    tax_total: Optional[str] = None
    other_charges: Optional[str] = None
    total: Optional[str] = Field(None, description="Grand total payable")
    prices_tax_inclusive: bool = Field(False, description="True if line rates already include GST")
    field_confidence: dict[str, float] = Field(
        default_factory=dict, description="0..1 confidence per top-level field name")
    notes: Optional[str] = Field(None, description="Anything unusual, e.g. 'Please note our new bank details'")


# ---------------- normalised ----------------
class LineItem(BaseModel):
    description: str = ""
    sku: Optional[str] = None
    hsn: Optional[str] = None
    quantity: Optional[Decimal] = None
    uom: Optional[str] = None
    unit_price: Optional[Decimal] = None
    amount: Optional[Decimal] = None
    tax_rate: Optional[Decimal] = None


class TaxLine(BaseModel):
    type: str
    rate: Optional[Decimal] = None
    amount: Optional[Decimal] = None


class ExtractedInvoice(BaseModel):
    vendor_name: Optional[str] = None
    vendor_gstin: Optional[str] = None
    vendor_address: Optional[str] = None
    vendor_bank: BankDetails = Field(default_factory=BankDetails)
    bill_to_name: Optional[str] = None
    invoice_number: Optional[str] = None              # raw, as printed
    invoice_number_normalised: Optional[str] = None
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    payment_terms: Optional[str] = None
    po_number: Optional[str] = None
    po_reference_text: Optional[str] = None
    currency: str = "INR"
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: Optional[Decimal] = None
    tax_lines: list[TaxLine] = Field(default_factory=list)
    tax_total: Optional[Decimal] = None
    other_charges: Decimal = Decimal("0")
    total: Optional[Decimal] = None
    prices_tax_inclusive: bool = False
    field_confidence: dict[str, float] = Field(default_factory=dict)
    notes: Optional[str] = None
    unparsed: list[str] = Field(default_factory=list, description="fields the normaliser could not parse")


# ---------------- checks & decision ----------------
class CheckResult(BaseModel):
    rule_id: str
    name: str
    stage: str
    status: Literal["pass", "warn", "fail", "skipped"]
    # what a *fail* leads to: reject | security | pending ; "info" for non-blocking checks
    severity: Literal["reject", "security", "pending", "info"] = "pending"
    evidence: dict[str, Any] = Field(default_factory=dict)
    message: str = ""


class Decision(BaseModel):
    decision: Literal["APPROVE", "PENDING", "REJECT"]
    security_hold: bool = False
    primary_reason: str = ""
    fired_rules: list[str] = Field(default_factory=list)   # rule ids that failed (drive the decision)
    warning_rules: list[str] = Field(default_factory=list)
    passed_rules: list[str] = Field(default_factory=list)


class NextAction(BaseModel):
    type: str                    # post_for_payment | security_verification | confirm_po | vendor_email | ...
    title: str
    channel: str = "email"       # email | phone | none
    to: Optional[str] = None
    subject: Optional[str] = None
    body: str = ""
    note: Optional[str] = None


class ActionRequest(BaseModel):
    type: Literal["approve", "reject", "confirm_po", "rerun"]
    po_id: Optional[str] = None
    reason: Optional[str] = None
    actor: str = "finance.user"
