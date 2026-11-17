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
        # The total is ALWAYS reconciled, even when the subtotal or tax total could not be read:
        # fall back to the sum of the lines, and to the sum of the tax lines.
        tax = ex.tax_total
        if tax is None and ex.tax_lines and all(t.amount is not None for t in ex.tax_lines):
            tax = sum((t.amount for t in ex.tax_lines), ZERO)
        base_total = ex.subtotal if ex.subtotal is not None else (sum_lines if all_amounts else None)
        if ex.total is not None and base_total is not None:
            if tax is None:
                tax = ZERO
                ev["note"] = "No tax amount could be read; assumed none when reconciling the total"
            elif ex.subtotal is None or ex.tax_total is None:
                ev["note"] = "Subtotal or tax total missing; reconciled using the lines and tax lines instead"
            expected_total = base_total + tax + other
            ev["expected_total"] = expected_total
            if abs(expected_total - ex.total) > TOL:
                issues.append(f"{'subtotal' if ex.subtotal is not None else 'lines'} {fmt_inr(base_total)} + tax "
                              f"{fmt_inr(tax)} = {fmt_inr(expected_total)}, but the invoice total is {fmt_inr(ex.total)}")
        elif ex.total is not None:
            issues.append("neither a subtotal nor every line amount could be read, so the total cannot be verified")
    unverifiable = [r["line"] for r in ev["lines"] if r["amount"] is not None and "expected_amount" not in r]
    if unverifiable:
        ev["lines_without_qty_or_price"] = unverifiable  # cannot check qty × price; totals above still must reconcile
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
    from .match import net_amount  # taxable value even when no subtotal was printed / read
    base = ex.subtotal if ex.subtotal is not None else (net_amount(ex) if ex.line_items else None)
    line_rates = {l.tax_rate for l in ex.line_items if l.tax_rate is not None}
    multi_rate = len(line_rates) > 1
    vendor_state = ex.vendor_gstin[:2] if ex.vendor_gstin and len(ex.vendor_gstin) >= 2 else None
    ev.update(vendor_state=vendor_state, buyer_state=config.BUYER_STATE_CODE, taxable_value=base,
              multi_rate=multi_rate)

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
        # sum over every slab: an invoice with 2 GST slabs prints 2 CGST and 2 SGST lines
        cg = [t for t in ex.tax_lines if t.type == "CGST"]
        sg = [t for t in ex.tax_lines if t.type == "SGST"]
        c_sum = sum((t.amount for t in cg if t.amount is not None), ZERO)
        s_sum = sum((t.amount for t in sg if t.amount is not None), ZERO)
        ev.update(cgst_total=c_sum, sgst_total=s_sum)
        if sorted(t.rate for t in cg if t.rate is not None) != sorted(t.rate for t in sg if t.rate is not None) \
                or abs(c_sum - s_sum) > Decimal("0.02") * max(len(cg), len(sg)):
            issues.append(f"CGST ({fmt_inr(c_sum)}) and SGST ({fmt_inr(s_sum)}) differ")
    if multi_rate:
        # several GST slabs: a single "rate x whole subtotal" is meaningless, so compare the TOTAL tax with the
        # sum of (line taxable value x that line's rate)
        if any(l.tax_rate is None or l.amount is None for l in ex.line_items):
            ev["note"] = "Several GST rates but not every line states its rate; tax amount not re-computed"
        else:
            expected_tax = ZERO
            for l in ex.line_items:
                line_base = q2(l.amount / (1 + l.tax_rate / 100)) if ex.prices_tax_inclusive else l.amount
                expected_tax += q2(line_base * l.tax_rate / 100)
            actual = sum((t.amount for t in ex.tax_lines if t.amount is not None), ZERO)
            ev.update(expected_total_tax=expected_tax, actual_total_tax=actual)
            if abs(expected_tax - actual) > TOL * max(1, len(ex.line_items)):
                issues.append(f"with line rates {sorted(str(r) for r in line_rates)} the GST should total "
                              f"{fmt_inr(expected_tax)}, but the invoice shows {fmt_inr(actual)}")
    elif base is not None:
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


def check_bill_to(ex: ExtractedInvoice) -> CheckResult:
    """R16: the invoice must be addressed to the buyer entity (a PO number alone does not prove that)."""
    from rapidfuzz import fuzz
    from .match import clean_name
    if not ex.bill_to_name:
        return _chk("R16", "Invoice is addressed to the buyer", "warn", "info",
                    "No bill-to name could be read from the invoice, so the addressee was not verified.",
                    {"bill_to": None, "buyer": config.BUYER_NAME})
    score = round(fuzz.token_sort_ratio(clean_name(ex.bill_to_name), clean_name(config.BUYER_NAME)), 1)
    ev = {"bill_to": ex.bill_to_name, "buyer": config.BUYER_NAME, "similarity": score, "threshold": 80}
    if score < 80:
        return _chk("R16", "Invoice is addressed to the buyer", "fail", "pending",
                    f"The invoice is addressed to '{ex.bill_to_name}', not {config.BUYER_NAME}. It may belong to a "
                    "different entity, so a person must confirm before it is paid.", ev)
    return _chk("R16", "Invoice is addressed to the buyer", "pass", "pending",
                f"The invoice is addressed to {ex.bill_to_name}.", ev)


def run_validate(ex: ExtractedInvoice) -> list[CheckResult]:
    out = [check_required(ex)]
    r15 = check_total_positive(ex)
    out += [check_math(ex), check_gst(ex), check_bill_to(ex)]
    if r15:
        out.append(r15)
    return out
