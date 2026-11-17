"""Stage 3 – Validate: required fields, arithmetic, GST structure. Pure code, no LLM."""
from __future__ import annotations

from decimal import Decimal

from .. import config
from ..schemas import CheckResult, ExtractedInvoice
from ..util import fmt_inr, q2

ZERO = Decimal("0")
TOL = config.TOTAL_ROUNDING_ABS


def _chk(rule, name, status, severity, message, evidence):
    return CheckResult(rule_id=rule, name=name, stage="validate", status=status, severity=severity,
                       message=message, evidence=evidence)


def check_required(ex: ExtractedInvoice) -> CheckResult:
    missing = []
    if not ex.vendor_name:
        missing.append("vendor name")
    if not ex.invoice_number:
        missing.append("invoice number")
    if ex.invoice_date is None:
        missing.append("invoice date")
    if ex.total is None:
        missing.append("total")
    ev = {"missing": missing, "unparsed": ex.unparsed}
    if missing:
        return _chk("R01", "Required fields present", "fail", "pending",
                    "Could not read: " + ", ".join(missing) + ". A person needs to look at the document.", ev)
    return _chk("R01", "Required fields present", "pass", "pending",
                "Vendor, invoice number, date and total are all present.", ev)


def check_total_positive(ex: ExtractedInvoice) -> CheckResult | None:
    if ex.total is None:
        return None
    if ex.total <= 0:
        return _chk("R15", "Total is positive", "fail", "reject",
                    f"The invoice total is {fmt_inr(ex.total)}. Zero or negative totals are not payable invoices.",
                    {"total": str(ex.total)})
    return _chk("R15", "Total is positive", "pass", "reject", f"Invoice total is {fmt_inr(ex.total)}.",
                {"total": str(ex.total)})


def check_math(ex: ExtractedInvoice) -> CheckResult:
    issues: list[str] = []
    ev: dict = {"lines": [], "prices_tax_inclusive": ex.prices_tax_inclusive}
    sum_lines = ZERO
    all_amounts = True
    for i, l in enumerate(ex.line_items, 1):
        row = {"line": i, "description": l.description, "qty": l.quantity, "unit_price": l.unit_price,
               "amount": l.amount}
        if l.quantity is not None and l.unit_price is not None and l.amount is not None:
            expected = q2(l.quantity * l.unit_price)
            row["expected_amount"] = expected
            if abs(expected - l.amount) > TOL:
                issues.append(f"line {i} ({l.description}): {l.quantity} × {fmt_inr(l.unit_price)} = "
                              f"{fmt_inr(expected)}, but the invoice shows {fmt_inr(l.amount)}")
        if l.amount is None:
            all_amounts = False
        else:
            sum_lines += l.amount
        ev["lines"].append(row)
    if not ex.line_items:
        issues.append("no line items could be read")
    ev["sum_of_lines"] = sum_lines if all_amounts else None
    other = ex.other_charges or ZERO
    if ex.prices_tax_inclusive:
        if ex.total is not None and all_amounts and abs(sum_lines + other - ex.total) > TOL:
            issues.append(f"lines add up to {fmt_inr(sum_lines)} but the total (GST-inclusive) is {fmt_inr(ex.total)}")
        if ex.subtotal is not None and ex.tax_total is not None and ex.total is not None:
            if abs(ex.subtotal + ex.tax_total + other - ex.total) > TOL:
                issues.append(f"taxable value {fmt_inr(ex.subtotal)} + GST {fmt_inr(ex.tax_total)} "
                              f"≠ total {fmt_inr(ex.total)}")
    else:
        if ex.subtotal is not None and all_amounts and abs(sum_lines - ex.subtotal) > TOL:
            issues.append(f"lines add up to {fmt_inr(sum_lines)} but the subtotal says {fmt_inr(ex.subtotal)}")
        if ex.subtotal is not None and ex.tax_total is not None and ex.total is not None:
            expected_total = ex.subtotal + ex.tax_total + other
            ev["expected_total"] = expected_total
            if abs(expected_total - ex.total) > TOL:
                issues.append(f"subtotal {fmt_inr(ex.subtotal)} + tax {fmt_inr(ex.tax_total)} = "
                              f"{fmt_inr(expected_total)}, but the invoice total is {fmt_inr(ex.total)}")
        elif ex.total is not None and ex.subtotal is None and all_amounts:
            ev["note"] = "No subtotal printed; compared lines with total only"
    ev.update(subtotal=ex.subtotal, tax_total=ex.tax_total, other_charges=other, total=ex.total,
              rounding_tolerance=TOL)
    if issues:
        return _chk("R03", "Line math & totals reconcile", "fail", "pending",
                    "The arithmetic on this invoice does not add up: " + "; ".join(issues) + ".", ev)
    return _chk("R03", "Line math & totals reconcile", "pass", "pending",
                f"Line amounts, subtotal, tax and total all reconcile (total {fmt_inr(ex.total)}).", ev)


def check_gst(ex: ExtractedInvoice) -> CheckResult:
    types = [t.type for t in ex.tax_lines]
    ev: dict = {"tax_lines": [{"type": t.type, "rate": t.rate, "amount": t.amount} for t in ex.tax_lines]}
    issues: list[str] = []
    base = ex.subtotal
    vendor_state = ex.vendor_gstin[:2] if ex.vendor_gstin and len(ex.vendor_gstin) >= 2 else None
    ev.update(vendor_state=vendor_state, buyer_state=config.BUYER_STATE_CODE, taxable_value=base)

    if not ex.tax_lines:
        if ex.tax_total and ex.tax_total > 0:
            issues.append("a tax total is shown without a CGST/SGST/IGST breakup")
        else:
            return _chk("R04", "GST structure valid", "warn", "info",
                        "No GST is charged on this invoice (zero-rated or exempt supply).", ev)
    has_igst, has_c, has_s = "IGST" in types, "CGST" in types, "SGST" in types
    if has_igst and (has_c or has_s):
        issues.append("IGST cannot be charged together with CGST/SGST")
    if has_c != has_s:
        issues.append("CGST and SGST must come as a pair")
    if has_c and has_s:
        c = next(t for t in ex.tax_lines if t.type == "CGST")
        s = next(t for t in ex.tax_lines if t.type == "SGST")
        if c.rate != s.rate or (c.amount is not None and s.amount is not None and abs(c.amount - s.amount) > Decimal("0.02")):
            issues.append(f"CGST ({fmt_inr(c.amount)} @ {c.rate}%) and SGST ({fmt_inr(s.amount)} @ {s.rate}%) differ")
    if base is not None:
        for t in ex.tax_lines:
            if t.rate is not None and t.amount is not None:
                expected = q2(base * t.rate / 100)
                if abs(expected - t.amount) > TOL:
                    issues.append(f"{t.type} @ {t.rate}% of {fmt_inr(base)} should be {fmt_inr(expected)}, "
                                  f"invoice shows {fmt_inr(t.amount)}")
    if vendor_state:
        intra = vendor_state == config.BUYER_STATE_CODE
        ev["supply"] = "intra-state" if intra else "inter-state"
        if intra and has_igst:
            issues.append("vendor and buyer are both in Maharashtra, so CGST+SGST applies, not IGST")
        if not intra and (has_c or has_s):
            issues.append(f"vendor is in state {vendor_state} (inter-state supply), so IGST applies, not CGST+SGST")
    if issues:
        return _chk("R04", "GST structure valid", "fail", "pending",
                    "GST looks wrong: " + "; ".join(issues) + ".", ev)
    kind = "IGST (inter-state)" if has_igst else "CGST + SGST (intra-state)"
    return _chk("R04", "GST structure valid", "pass", "pending",
                f"GST is structured correctly as {kind}; tax equals rate × taxable value.", ev)


def run_validate(ex: ExtractedInvoice) -> list[CheckResult]:
    out = [check_required(ex)]
    r15 = check_total_positive(ex)
    out += [check_math(ex), check_gst(ex)]
    if r15:
        out.append(r15)
    return out
