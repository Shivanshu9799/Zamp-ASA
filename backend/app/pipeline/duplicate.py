"""Stage 5 – Duplicate check (R07 exact, R08 probable).

Compares against earlier invoices from the same vendor that were not rejected.
Sequential invoice numbers (APX-1101 / APX-1102) are NOT duplicates: every non-hash signal needs the same total.
"""
from __future__ import annotations

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from .. import config
from ..models import Run, Vendor
from ..schemas import CheckResult, ExtractedInvoice
from ..util import fmt_inr, normalise_invoice_no


def fuzzy_signals(ex: ExtractedInvoice, prior_no: str | None, prior_total, prior_date, hash_equal: bool) -> dict:
    mine = ex.invoice_number_normalised or normalise_invoice_no(ex.invoice_number)
    theirs = normalise_invoice_no(prior_no)
    sim = round(fuzz.ratio(mine, theirs), 1) if mine and theirs else 0.0
    total_equal = (ex.total is not None and prior_total is not None
                   and abs(ex.total - prior_total) <= config.TOTAL_ROUNDING_ABS)
    days = None
    if ex.invoice_date and prior_date:
        days = abs((ex.invoice_date - prior_date).days)
    date_close = days is not None and days <= config.DUP_DATE_WINDOW_DAYS
    sim_hit = sim >= config.DUP_INVOICE_NO_SIMILARITY
    if hash_equal or (sim_hit and total_equal and date_close):
        level = "high"
    elif total_equal and (sim_hit or date_close):
        level = "medium"
    else:
        level = "none"
    return {"level": level, "invoice_no_similarity": sim, "same_total": total_equal, "days_apart": days,
            "date_within_window": date_close, "same_file": hash_equal}


def check_duplicates(db: Session, ex: ExtractedInvoice, vendor: Vendor | None, run_id: int,
                     file_sha: str) -> tuple[list[CheckResult], dict]:
    if vendor is None:
        skip = [CheckResult(rule_id=r, name=n, stage="duplicate", status="warn", severity="info",
                            message="Skipped: the vendor could not be identified, so earlier invoices cannot be compared.")
                for r, n in (("R07", "Exact duplicate"), ("R08", "Probable duplicate"))]
        return skip, {}
    priors = (db.query(Run).filter(Run.vendor_id == vendor.id, Run.id != run_id,
                                   Run.status.in_(["APPROVED", "PENDING"])).all())
    raw_no = (ex.invoice_number or "").strip().casefold()
    exact = next((p for p in priors if raw_no and (p.invoice_number or "").strip().casefold() == raw_no), None)
    checks: list[CheckResult] = []
    details: dict = {"compared_with": len(priors)}
    if exact:
        details["duplicate_of"] = exact.id
        checks.append(CheckResult(
            rule_id="R07", name="Exact duplicate invoice", stage="duplicate", status="fail", severity="reject",
            message=f"Invoice {exact.invoice_number} from {vendor.name} was already processed as run #{exact.id} "
                    f"({exact.status.title()}).",
            evidence={"duplicate_of_run": exact.id, "invoice_number": ex.invoice_number,
                      "prior_status": exact.status, "prior_total": exact.total}))
    else:
        checks.append(CheckResult(rule_id="R07", name="Exact duplicate invoice", stage="duplicate", status="pass",
                                  severity="reject",
                                  message=f"No earlier invoice {ex.invoice_number} from this vendor "
                                          f"({len(priors)} earlier invoice(s) compared).",
                                  evidence={"compared_with": len(priors)}))
    best = None
    for p in priors:
        sig = fuzzy_signals(ex, p.invoice_number, _dec(p.total), _date(p.invoice_date), bool(p.file_sha) and p.file_sha == file_sha)
        rank = {"high": 2, "medium": 1, "none": 0}[sig["level"]]
        if rank and (best is None or (rank, sig["invoice_no_similarity"]) > (best[0], best[1]["invoice_no_similarity"])):
            best = (rank, sig, p)
    if best:
        _, sig, p = best
        details.setdefault("duplicate_of", p.id)
        why = []
        if sig["same_file"]:
            why.append("it is the identical file")
        if sig["invoice_no_similarity"] >= config.DUP_INVOICE_NO_SIMILARITY:
            why.append(f"invoice numbers {ex.invoice_number} and {p.invoice_number} are {sig['invoice_no_similarity']:.0f}% alike")
        if sig["same_total"]:
            why.append(f"same total {fmt_inr(ex.total)}")
        if sig["date_within_window"]:
            why.append(f"dated {sig['days_apart']} day(s) apart")
        high = sig["level"] == "high"
        checks.append(CheckResult(
            rule_id="R08", name="Probable duplicate (fuzzy)", stage="duplicate", status="fail",
            severity="reject" if high else "pending",
            message=("Looks like a duplicate of run #%d (%s): " % (p.id, p.invoice_number)) + "; ".join(why) +
                    (". Rejected as a duplicate." if high else ". Please confirm whether it is a re-submission."),
            evidence={"duplicate_of_run": p.id, "confidence": sig["level"], **sig,
                      "this_invoice": ex.invoice_number, "prior_invoice": p.invoice_number,
                      "this_total": ex.total, "prior_total": p.total}))
    else:
        checks.append(CheckResult(rule_id="R08", name="Probable duplicate (fuzzy)", stage="duplicate", status="pass",
                                  severity="reject",
                                  message="No earlier invoice from this vendor has a similar number, total and date.",
                                  evidence={"compared_with": len(priors)}))
    return checks, details


def _dec(s):
    from ..util import to_dec
    return to_dec(s)


def _date(s):
    from ..util import parse_date
    return parse_date(s)
