"""Stages 4 & 6 – Vendor check and PO matching (R05, R06, R09–R14).

Everything here is deterministic. Money is Decimal throughout.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from .. import config
from ..models import GoodsReceipt, POLine, PurchaseOrder, Run, Vendor
from ..schemas import CheckResult, ExtractedInvoice
from ..util import (find_dates_in_text, fmt_inr, fmt_qty, normalise_po, parse_date, q2, to_dec)

ZERO = Decimal("0")


# ======================================================================= vendor (R05, R06)
_STOP = {"pvt", "ltd", "private", "limited", "llp", "and", "co", "company", "the"}


def clean_name(s: str) -> str:
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(t for t in s.split() if t not in _STOP)


def vendor_names(v: Vendor) -> list[str]:
    return [v.name] + [a.strip() for a in (v.aliases or "").split(";") if a.strip()]


def name_score(inv_name: str, v: Vendor) -> float:
    a = clean_name(inv_name)
    return max((fuzz.token_sort_ratio(a, clean_name(n)) for n in vendor_names(v)), default=0.0)


def mask_acct(a: Optional[str]) -> str:
    a = re.sub(r"\D", "", a or "")
    return ("•" * max(len(a) - 4, 0) + a[-4:]) if a else "—"


def check_vendor(db: Session, ex: ExtractedInvoice) -> tuple[Optional[Vendor], list[CheckResult], dict]:
    vendors = db.query(Vendor).all()
    gstin = (ex.vendor_gstin or "").strip().upper()
    ranked = sorted(((name_score(ex.vendor_name or "", v), v) for v in vendors), key=lambda t: -t[0])
    top3 = [{"vendor_id": v.id, "name": v.name, "score": round(s, 1)} for s, v in ranked[:3]]
    by_gstin = next((v for v in vendors if gstin and v.gstin.upper() == gstin), None)
    ev: dict = {"invoice_name": ex.vendor_name, "invoice_gstin": gstin or None, "candidates": top3,
                "thresholds": {"auto": config.VENDOR_FUZZY_AUTO, "review": config.VENDOR_FUZZY_REVIEW}}
    vendor: Optional[Vendor] = None
    checks: list[CheckResult] = []

    def r05(status, severity, msg, **extra):
        checks.append(CheckResult(rule_id="R05", name="Vendor is in the vendor master", stage="vendor", status=status,
                                  severity=severity, message=msg, evidence={**ev, **extra}))

    if by_gstin:
        vendor = by_gstin
        sc = round(name_score(ex.vendor_name or "", vendor), 1)
        if ex.vendor_name and sc < config.VENDOR_FUZZY_REVIEW:
            r05("fail", "pending", f"GSTIN {gstin} belongs to {vendor.name}, but the invoice is issued in the name "
                f"'{ex.vendor_name}'. Please confirm the vendor.", matched_vendor=vendor.id, match="gstin", name_score=sc)
        else:
            r05("pass", "reject", f"Vendor recognised as {vendor.name} ({vendor.id}) by GSTIN {gstin}.",
                matched_vendor=vendor.id, match="gstin", name_score=sc)
    elif ranked and ranked[0][0] >= config.VENDOR_FUZZY_AUTO and not gstin:
        vendor = ranked[0][1]
        r05("pass", "reject", f"Vendor matched to {vendor.name} ({vendor.id}) by name ({ranked[0][0]:.0f}% match; "
            "no GSTIN printed).", matched_vendor=vendor.id, match="name", name_score=round(ranked[0][0], 1))
    elif ranked and ranked[0][0] >= config.VENDOR_FUZZY_AUTO and gstin:
        vendor = ranked[0][1]
        r05("fail", "pending", f"The name matches {vendor.name}, but the GSTIN on the invoice ({gstin}) is not the one "
            f"on file ({vendor.gstin}). Please verify before paying.", matched_vendor=vendor.id, match="name",
            name_score=round(ranked[0][0], 1), gstin_on_file=vendor.gstin)
    elif ranked and ranked[0][0] >= config.VENDOR_FUZZY_REVIEW:
        vendor = ranked[0][1]
        r05("fail", "pending", f"'{ex.vendor_name}' is only a {ranked[0][0]:.0f}% match to {vendor.name}. "
            "A person should confirm it is the same vendor.", matched_vendor=vendor.id, match="name_borderline",
            name_score=round(ranked[0][0], 1))
    elif not ex.vendor_name and not gstin:
        r05("fail", "pending", "No vendor name or GSTIN could be read, so the vendor cannot be identified.")
    else:
        r05("fail", "reject", f"'{ex.vendor_name}' (GSTIN {gstin or 'not printed'}) is not in the vendor master. "
            "We do not pay unknown vendors.", match=None)

    # ---- R06 bank details
    if vendor:
        b = ex.vendor_bank
        inv_acct = re.sub(r"\D", "", b.account_number or "")
        inv_ifsc = (b.ifsc or "").strip().upper()
        master = {"bank_name": vendor.bank_name, "account_number": vendor.account_number, "ifsc": vendor.ifsc}
        ev6 = {"on_invoice": {"bank_name": b.bank_name, "account_number": b.account_number, "ifsc": b.ifsc},
               "on_file": master, "vendor_note": ex.notes, "vendor_phone_on_file": vendor.phone_on_file}
        if not inv_acct and not inv_ifsc:
            checks.append(CheckResult(rule_id="R06", name="Bank details match vendor master", stage="vendor",
                                      status="warn", severity="info", evidence=ev6,
                                      message="No bank details are printed on the invoice; payment would use the "
                                              "account on file."))
        else:
            diffs = []
            if inv_acct and inv_acct != re.sub(r"\D", "", vendor.account_number):
                diffs.append("account number")
            if inv_ifsc and inv_ifsc != vendor.ifsc.upper():
                diffs.append("IFSC")
            if diffs:
                checks.append(CheckResult(
                    rule_id="R06", name="Bank details match vendor master", stage="vendor", status="fail",
                    severity="security", evidence=ev6,
                    message=f"SECURITY HOLD – the {' and '.join(diffs)} on the invoice "
                            f"({b.bank_name or 'bank n/a'}, A/c {mask_acct(b.account_number)}) differ from the account "
                            f"on file ({vendor.bank_name}, A/c {mask_acct(vendor.account_number)}). "
                            "Changed bank details are a common fraud pattern, so this is never auto-approved."))
            else:
                checks.append(CheckResult(rule_id="R06", name="Bank details match vendor master", stage="vendor",
                                          status="pass", severity="security", evidence=ev6,
                                          message=f"Bank account matches the one on file ({vendor.bank_name}, "
                                                  f"A/c {mask_acct(vendor.account_number)})."))
    return vendor, checks, {"vendor_id": vendor.id if vendor else None, "candidates": top3}


# ======================================================================= PO helpers
def _desc(s: str) -> str:
    s = (s or "").lower().replace("×", "x").replace("→", " to ").replace("–", " ").replace("-", " ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(s.split())


def desc_sim(a: str, b: str) -> float:
    """Blend of order-insensitive similarity and token containment, so extra text on the invoice line
    (e.g. a 'Service period: ...' note the reader merged into the description) does not hide a real match."""
    x, y = _desc(a), _desc(b)
    return (fuzz.token_sort_ratio(x, y) + fuzz.token_set_ratio(x, y)) / 200.0


def po_lines(db: Session, po_id: str) -> list[POLine]:
    return db.query(POLine).filter(POLine.po_id == po_id).order_by(POLine.line_no).all()


def received_by_line(db: Session, po_id: str) -> dict[int, Decimal]:
    out: dict[int, Decimal] = {}
    for g in db.query(GoodsReceipt).filter(GoodsReceipt.po_id == po_id).all():
        out[g.line_no] = out.get(g.line_no, ZERO) + to_dec(g.qty, ZERO)
    return out


def history(db: Session, po_id: str, exclude_run: int) -> dict:
    """Approved invoices count towards invoiced-to-date; pending ones are shown as 'in review' only."""
    inv_amt, qty = ZERO, {}
    in_review = ZERO
    runs = db.query(Run).filter(Run.po_id == po_id, Run.id != exclude_run,
                                Run.status.in_(["APPROVED", "PENDING"])).all()
    approved = []
    for r in runs:
        net = to_dec(r.net_amount, ZERO)
        if r.status == "APPROVED":
            inv_amt += net
            approved.append(r.id)
            for lm in (r.line_matches or []):
                if lm.get("po_line_no") is not None:
                    qty[lm["po_line_no"]] = qty.get(lm["po_line_no"], ZERO) + to_dec(lm.get("this_qty"), ZERO)
        else:
            in_review += net
    return {"invoiced": inv_amt, "qty": qty, "in_review": in_review, "approved_runs": approved}


def tax_rate_of(ex: ExtractedInvoice) -> Decimal:
    if ex.tax_lines:
        return sum((t.rate or ZERO for t in ex.tax_lines), ZERO)
    return ZERO


def ex_tax_unit_price(ex: ExtractedInvoice, l) -> Optional[Decimal]:
    if l.unit_price is None:
        return None
    if ex.prices_tax_inclusive:
        rate = l.tax_rate if l.tax_rate else tax_rate_of(ex)
        return q2(l.unit_price / (1 + rate / 100))
    return l.unit_price


def net_amount(ex: ExtractedInvoice) -> Decimal:
    """Value billed before tax."""
    if ex.subtotal is not None:
        return ex.subtotal
    tot = sum((l.amount or ZERO for l in ex.line_items), ZERO)
    if ex.prices_tax_inclusive and tax_rate_of(ex):
        return q2(tot / (1 + tax_rate_of(ex) / 100))
    return tot


def map_lines(ex: ExtractedInvoice, plines: list[POLine]) -> list[tuple[int, Optional[POLine], float]]:
    """One-to-one best-first mapping of invoice lines to PO lines (SKU first, then description similarity)."""
    pairs = []
    for i, l in enumerate(ex.line_items):
        for p in plines:
            s = 1.0 if (l.sku and p.sku and l.sku.strip().lower() == p.sku.strip().lower()) else desc_sim(
                l.description, p.description)
            pairs.append((s, i, p))
    pairs.sort(key=lambda t: -t[0])
    used_i, used_p, out = set(), set(), {}
    for s, i, p in pairs:
        if s < 0.6 or i in used_i or p.line_no in used_p:
            continue
        used_i.add(i)
        used_p.add(p.line_no)
        out[i] = (p, s)
    return [(i, *(out[i] if i in out else (None, 0.0))) for i in range(len(ex.line_items))]


# ======================================================================= PO inference (R10)
def score_po(ex: ExtractedInvoice, po: PurchaseOrder, plines: list[POLine], ref_dates: list) -> dict:
    W = config.PO_INFERENCE_WEIGHTS
    mapping = map_lines(ex, plines)
    n = max(len(ex.line_items), 1)
    desc_scores, qp_scores = [], []
    for i, l in enumerate(ex.line_items):
        best = max(plines, key=lambda p: desc_sim(l.description, p.description), default=None)
        ds = desc_sim(l.description, best.description) if best else 0.0
        desc_scores.append(ds)
        if best and l.quantity is not None:
            up = ex_tax_unit_price(ex, l)
            pp, pq = to_dec(best.unit_price, ZERO), to_dec(best.qty, ZERO)
            price_s = 0.0
            if up is not None and pp:
                diff = abs(up - pp) / pp
                price_s = 1.0 if diff * 100 <= config.PRICE_TOLERANCE_PCT else max(0.0, 1 - float(diff))
            qty_s = float(min(l.quantity, pq) / max(l.quantity, pq)) if pq and l.quantity else 0.0
            qp_scores.append(0.5 * price_s + 0.5 * qty_s)
        else:
            qp_scores.append(0.0)
    desc_s = sum(desc_scores) / n
    qp_s = sum(qp_scores) / n
    sub, po_amt = net_amount(ex), to_dec(po.amount, ZERO)
    if sub and po_amt:
        rel = abs(sub - po_amt) / max(sub, po_amt)
        amt_s = 1.0 if rel <= Decimal("0.005") else max(0.0, 1 - float(rel))
    else:
        amt_s = 0.0
    pdate = parse_date(po.date)
    if ref_dates and pdate:
        days = min(abs((d - pdate).days) for d in ref_dates)
        date_s = max(0.0, 1 - days / 30)
        date_note = (f"PO dated {pdate.strftime('%d-%b-%Y')} — the date quoted on the invoice"
                     if days == 0 else f"PO dated {pdate.strftime('%d-%b-%Y')}, {days} day(s) from the date quoted")
    else:
        late = ex.invoice_date and pdate and ex.invoice_date < pdate
        date_s = 0.0 if late else 0.5
        date_note = "PO is dated after the invoice" if late else "No order date quoted on the invoice"
    score = W["description"] * desc_s + W["qty_price"] * qp_s + W["amount"] * amt_s + W["date"] * date_s
    reasons = []
    if desc_s >= 0.85:
        reasons.append(f"Item descriptions match ({desc_s:.0%})")
    elif desc_s >= 0.5:
        reasons.append(f"Item descriptions partly match ({desc_s:.0%})")
    else:
        reasons.append(f"Item descriptions differ ({desc_s:.0%})")
    reasons.append("Quantities and unit prices agree with the PO" if qp_s >= 0.95 else
                   f"Quantity/price agreement is {qp_s:.0%}")
    reasons.append(f"Invoice value {fmt_inr(sub)} vs PO {fmt_inr(po_amt)}" + (" — equal" if amt_s >= 0.99 else ""))
    reasons.append(date_note)
    return {"po_id": po.id, "po_date": po.date, "po_amount": str(po_amt), "type": po.type,
            "score": round(score, 3),
            "parts": {"description": round(desc_s, 3), "qty_price": round(qp_s, 3), "amount": round(amt_s, 3),
                      "date": round(date_s, 3)}, "reasons": reasons}


def infer_po(db: Session, ex: ExtractedInvoice, vendor: Vendor, exclude_run: int) -> dict:
    ref_dates = find_dates_in_text(ex.po_reference_text or "")
    cands = []
    for po in db.query(PurchaseOrder).filter(PurchaseOrder.vendor_id == vendor.id).all():
        h = history(db, po.id, exclude_run)
        if h["invoiced"] >= to_dec(po.amount, ZERO):
            continue  # fully billed: not an open PO
        cands.append(score_po(ex, po, po_lines(db, po.id), ref_dates))
    cands.sort(key=lambda c: -c["score"])
    # same-value POs of OTHER vendors: shown as excluded decoys, never scored
    excluded = []
    sub = net_amount(ex)
    for po in db.query(PurchaseOrder).filter(PurchaseOrder.vendor_id != vendor.id).all():
        pa = to_dec(po.amount, ZERO)
        if sub and pa and abs(sub - pa) / max(sub, pa) <= Decimal("0.01"):
            excluded.append({"po_id": po.id, "vendor_id": po.vendor_id, "score": 0.0, "po_amount": str(pa),
                             "reasons": [f"Same value ({fmt_inr(pa)}) but a different vendor — "
                                         "amount alone is never enough"], "excluded": True})
    return {"candidates": cands[:3], "excluded": excluded, "reference_dates": [d.isoformat() for d in ref_dates]}


# ======================================================================= the PO-match stage
@dataclass
class POResult:
    checks: list[CheckResult] = field(default_factory=list)
    po: Optional[PurchaseOrder] = None
    line_matches: list[dict] = field(default_factory=list)
    po_balance: Optional[dict] = None
    candidates: Optional[dict] = None
    details: dict = field(default_factory=dict)


def _c(rule, name, status, severity, msg, ev):
    return CheckResult(rule_id=rule, name=name, stage="po_match", status=status, severity=severity,
                       message=msg, evidence=ev)


def _skipped(rule: str, name: str, dup_run: int) -> CheckResult:
    return _c(rule, name, "skipped", "info", f"Not evaluated – invoice is a duplicate of run #{dup_run}",
              {"duplicate_of_run": dup_run})


SKIPPABLE = [("R11", "Unit price within tolerance of PO"),
             ("R12", "3-way match: billed ≤ received − already billed"),
             ("R13", "Cumulative billing within PO value"), ("R14", "Currency matches PO")]


def run_po_match(db: Session, ex: ExtractedInvoice, vendor: Optional[Vendor], run_id: int,
                 po_override: Optional[str] = None, duplicate_of: Optional[int] = None) -> POResult:
    """`duplicate_of`: the invoice was rejected as a duplicate (R07 / high-confidence R08). The PO is still
    resolved (R09) but the matching checks R10-R14 are marked skipped: a duplicate's price/quantity/balance
    would only restate the original invoice's numbers, and its quantities must not be billed again anyway."""
    res = POResult()
    if vendor is None:
        res.checks.append(_c("R09", "PO exists and belongs to the vendor", "warn", "info",
                             "Skipped: the vendor is unknown, so no PO can be matched.", {}))
        return res

    po: Optional[PurchaseOrder] = None
    wrong_vendor_po: Optional[PurchaseOrder] = None
    if po_override:
        po = db.get(PurchaseOrder, po_override)
        if po and po.vendor_id != vendor.id:
            po = None
    elif ex.po_number:
        key = normalise_po(ex.po_number)
        found = next((p for p in db.query(PurchaseOrder).all() if normalise_po(p.id) == key), None)
        if found and found.vendor_id == vendor.id:
            po = found
        elif found:
            wrong_vendor_po = found

    # ---------- R09 / R10
    if po:
        how = "confirmed by a finance user" if po_override else "printed on the invoice"
        res.checks.append(_c("R09", "PO exists and belongs to the vendor", "pass", "pending",
                             f"{po.id} ({how}) exists and belongs to {vendor.name}.",
                             {"po_id": po.id, "po_on_invoice": ex.po_number, "override": bool(po_override),
                              "po_date": po.date, "po_amount": po.amount, "po_type": po.type}))
    else:
        if wrong_vendor_po:
            msg = (f"PO {ex.po_number} exists but belongs to a different vendor ({wrong_vendor_po.vendor_id}), "
                   f"not {vendor.name}. Trying to infer the right PO instead.")
        elif ex.po_number:
            msg = f"PO number {ex.po_number} is not in the PO master. Trying to infer the right PO instead."
        else:
            msg = "No PO number on the invoice. Trying to infer the PO from its contents."
        res.checks.append(_c("R09", "PO exists and belongs to the vendor", "warn", "info", msg,
                             {"po_on_invoice": ex.po_number, "reference_text": ex.po_reference_text}))
    if (not po or po_override) and not duplicate_of:
        inf = infer_po(db, ex, vendor, run_id)
        res.candidates = inf
    if not po and duplicate_of:
        res.checks.append(_skipped("R10", "PO inference for invoices without a PO", duplicate_of))
        for rule, name in SKIPPABLE:
            res.checks.append(_skipped(rule, name, duplicate_of))
        res.details = {"po_id": None, "skipped_duplicate_of": duplicate_of}
        return res
    if not po:
        inf = res.candidates
        best = inf["candidates"][0] if inf["candidates"] else None
        ev = {"candidates": inf["candidates"], "excluded": inf["excluded"], "threshold": config.PO_INFERENCE_SUGGEST,
              "reference_text": ex.po_reference_text}
        if best and best["score"] >= config.PO_INFERENCE_SUGGEST:
            res.checks.append(_c("R10", "PO inference for invoices without a PO", "fail", "pending",
                                 f"No usable PO number. Best match is {best['po_id']} (score {best['score']:.0%}): "
                                 + "; ".join(best["reasons"][:3]) + ". A person must confirm it before this can be paid.",
                                 {**ev, "suggested_po": best["po_id"]}))
        else:
            res.checks.append(_c("R10", "PO inference for invoices without a PO", "fail", "pending",
                                 "No open PO for this vendor looks like this invoice, so it is treated as a non-PO "
                                 "invoice. Route it to the budget owner for approval or a retroactive PO.",
                                 {**ev, "suggested_po": None}))
        res.details = {"po_id": None}
        return res

    res.po = po
    if duplicate_of:
        for rule, name in SKIPPABLE:
            res.checks.append(_skipped(rule, name, duplicate_of))
        res.details = {"po_id": po.id, "po_type": po.type, "skipped_duplicate_of": duplicate_of}
        return res
    plines = po_lines(db, po.id)
    h = history(db, po.id, run_id)
    po_amount = to_dec(po.amount, ZERO)
    goods = po.type == "goods"
    recv = received_by_line(db, po.id) if goods else {}

    # ---------- R14 currency
    ok_cur = (ex.currency or "INR") == (po.currency or "INR")
    res.checks.append(_c("R14", "Currency matches PO", "pass" if ok_cur else "fail", "pending",
                         f"Invoice and PO are both in {po.currency}." if ok_cur else
                         f"Invoice is in {ex.currency} but the PO is in {po.currency}.",
                         {"invoice_currency": ex.currency, "po_currency": po.currency}))

    # ---------- line matching + R11 price
    mapping = map_lines(ex, plines)
    rows, price_issues, unmatched = [], [], []
    for i, (idx, p, sim) in enumerate(mapping):
        l = ex.line_items[idx]
        row = {"line": idx + 1, "description": l.description, "match_score": round(sim, 2),
               "this_qty": l.quantity, "inv_unit_price": ex_tax_unit_price(ex, l), "inv_amount": l.amount,
               "po_line_no": None, "po_description": None, "ordered_qty": None, "po_unit_price": None,
               "received_qty": None, "previously_invoiced_qty": None, "open_qty": None, "qty_delta": None,
               "price_delta_pct": None, "price_ok": None, "qty_ok": None}
        if p is None:
            unmatched.append(l.description)
            row.update(price_ok=False, qty_ok=False)
        else:
            pp = to_dec(p.unit_price, ZERO)
            row.update(po_line_no=p.line_no, po_description=p.description, ordered_qty=to_dec(p.qty), po_unit_price=pp,
                       uom=p.uom)
            up = row["inv_unit_price"]
            if up is not None and pp:
                pct = (up - pp) / pp * 100
                row["price_delta_pct"] = q2(pct)
                row["price_ok"] = abs(pct) <= config.PRICE_TOLERANCE_PCT
                if not row["price_ok"]:
                    price_issues.append(f"'{l.description}': invoice {fmt_inr(up)} vs PO {fmt_inr(pp)} "
                                        f"({'+' if pct > 0 else ''}{q2(pct)}%)")
            else:
                row["price_ok"] = False
                price_issues.append(f"'{l.description}': no unit price to compare")
            if goods:
                recvd = recv.get(p.line_no, ZERO)
                prev = h["qty"].get(p.line_no, ZERO)
                open_q = recvd - prev
                row.update(received_qty=recvd, previously_invoiced_qty=prev, open_qty=open_q)
                if l.quantity is not None:
                    row["qty_delta"] = l.quantity - open_q
                    row["qty_ok"] = l.quantity <= open_q + config.QTY_TOLERANCE
                else:
                    row["qty_ok"] = False
            else:
                prev = h["qty"].get(p.line_no, ZERO)
                row.update(previously_invoiced_qty=prev, open_qty=to_dec(p.qty, ZERO) - prev)
                row["qty_ok"] = True if l.quantity is None else (l.quantity <= to_dec(p.qty, ZERO) - prev + config.QTY_TOLERANCE)
        rows.append(row)
    res.line_matches = rows

    if unmatched or price_issues:
        parts = []
        if unmatched:
            parts.append("not on the PO: " + ", ".join(f"'{u}'" for u in unmatched))
        parts += price_issues
        res.checks.append(_c("R11", "Unit price within tolerance of PO", "fail", "pending",
                             "Price check failed — " + "; ".join(parts) + f". Tolerance is ±{config.PRICE_TOLERANCE_PCT}%.",
                             {"lines": rows, "tolerance_pct": config.PRICE_TOLERANCE_PCT}))
    else:
        res.checks.append(_c("R11", "Unit price within tolerance of PO", "pass", "pending",
                             "Unit prices match the PO on every line"
                             + (" (GST stripped from tax-inclusive rates before comparing)." if ex.prices_tax_inclusive else "."),
                             {"lines": rows, "tolerance_pct": config.PRICE_TOLERANCE_PCT}))

    # ---------- R12 3-way match (goods only)
    if goods:
        over = [r for r in rows if r["po_line_no"] is not None and r["qty_ok"] is False]
        if over:
            msgs = []
            for r in over:
                d = r["qty_delta"]
                msgs.append(f"'{r['description']}': invoice bills {fmt_qty(r['this_qty'])} but only "
                            f"{fmt_qty(r['open_qty'])} are received and not yet billed "
                            f"({fmt_qty(r['received_qty'])} received − {fmt_qty(r['previously_invoiced_qty'])} already "
                            f"billed)" + (f" → {fmt_qty(d)} unit(s) over" if d is not None else ""))
            res.checks.append(_c("R12", "3-way match: billed ≤ received − already billed", "fail", "pending",
                                 "Billing more than the warehouse has received: " + "; ".join(msgs) + ".",
                                 {"lines": rows}))
        else:
            res.checks.append(_c("R12", "3-way match: billed ≤ received − already billed", "pass", "pending",
                                 "Billed quantities are covered by goods receipts (received minus already billed).",
                                 {"lines": rows}))
    else:
        res.checks.append(_c("R12", "3-way match: billed ≤ received − already billed", "pass", "info",
                             "Service PO: 2-way match (invoice vs PO). No goods receipt is needed.", {"lines": rows}))

    # ---------- R13 cumulative
    this_net = net_amount(ex)
    total_after = h["invoiced"] + this_net
    remaining_before = po_amount - h["invoiced"]
    over_by = total_after - po_amount
    res.po_balance = {"po_id": po.id, "po_amount": po_amount, "invoiced_to_date": h["invoiced"],
                      "this_invoice": this_net, "remaining_before": remaining_before,
                      "remaining_after": po_amount - total_after, "in_review": h["in_review"],
                      "over_by": over_by if over_by > 0 else ZERO}
    ev13 = {**res.po_balance, "total_billed_after": total_after, "approved_runs": h["approved_runs"],
            "rounding_tolerance": config.TOTAL_ROUNDING_ABS}
    if over_by > config.TOTAL_ROUNDING_ABS:
        res.checks.append(_c("R13", "Cumulative billing within PO value", "fail", "pending",
                             f"PO {po.id} is worth {fmt_inr(po_amount)}; {fmt_inr(h['invoiced'])} is already billed and "
                             f"this invoice adds {fmt_inr(this_net)}, which exceeds the PO by {fmt_inr(over_by)}.", ev13))
    else:
        res.checks.append(_c("R13", "Cumulative billing within PO value", "pass", "pending",
                             f"{fmt_inr(h['invoiced'])} billed to date + {fmt_inr(this_net)} this invoice stays within "
                             f"the PO value of {fmt_inr(po_amount)} ({fmt_inr(po_amount - total_after)} left).", ev13))
    res.details = {"po_id": po.id, "po_type": po.type}
    return res
