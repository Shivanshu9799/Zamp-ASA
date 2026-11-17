"""Stage 8b – Next-action drafts (deterministic templates; nothing is ever sent automatically)."""
from __future__ import annotations

from typing import Optional

from ..models import Vendor
from ..schemas import CheckResult, Decision, ExtractedInvoice, NextAction
from ..util import fmt_inr, fmt_qty

AP_SIGN = "Regards,\nAccounts Payable\nMeridian Foods Pvt. Ltd."
BUYER_MAIL = "purchasing@meridianfoods.example"
AP_MAIL = "ap-controller@meridianfoods.example"


def _by(checks: list[CheckResult], rule: str) -> Optional[CheckResult]:
    return next((c for c in checks if c.rule_id == rule and c.status == "fail"), None)


def _inv_ref(ex: ExtractedInvoice) -> str:
    d = ex.invoice_date.strftime("%d-%b-%Y") if ex.invoice_date else "n/a"
    return f"{ex.invoice_number} dated {d} for {fmt_inr(ex.total)}"


def draft_next_action(decision: Decision, checks: list[CheckResult], ex: ExtractedInvoice,
                      vendor: Optional[Vendor]) -> NextAction:
    vname = vendor.name if vendor else (ex.vendor_name or "the vendor")
    vmail = vendor.email if vendor else None

    if decision.decision == "APPROVE":
        return NextAction(type="post_for_payment", title="Post for payment", channel="none",
                          body="Nothing further is needed. The invoice can be posted for payment in the next payment run.",
                          note="APPROVE is a recommendation to post for payment — the system never releases money itself.")

    r06 = _by(checks, "R06")
    if r06:
        ev = r06.evidence
        old, new = ev["on_file"], ev["on_invoice"]
        phone = ev.get("vendor_phone_on_file") or "the number in the vendor master"
        body = (
            f"HOLD – do not pay invoice {ex.invoice_number} ({fmt_inr(ex.total)}) until the new bank details are verified.\n\n"
            f"What changed\n  On file : {old['bank_name']}, A/c {old['account_number']}, IFSC {old['ifsc']}\n"
            f"  Invoice : {new['bank_name']}, A/c {new['account_number']}, IFSC {new['ifsc']}\n"
            + (f"  Vendor note on invoice: \"{ev['vendor_note']}\"\n" if ev.get("vendor_note") else "") +
            f"\nCall script\n  1. Phone {vname} on {phone} — the number ALREADY ON FILE, not any contact printed on the invoice or in an email.\n"
            "  2. Ask for a named finance contact and confirm they issued invoice "
            f"{ex.invoice_number} and are changing bank accounts.\n"
            "  3. Read back the new account number and IFSC and have them confirmed in writing from a known address.\n"
            "  4. Record who you spoke to and when, then ask the vendor-master owner to update the bank details "
            "(dual approval) before releasing this invoice.\n")
        return NextAction(type="security_verification", title="Verify the new bank details by phone", channel="phone",
                          to=f"{vname} — {phone}", subject=f"Security hold: bank change on {ex.invoice_number}", body=body,
                          note=f"Verify with the vendor via the phone number on file ({phone}), not the contact on the invoice.")

    dup = _by(checks, "R07") or _by(checks, "R08")
    if dup and decision.decision == "REJECT":
        run = dup.evidence.get("duplicate_of_run")
        return NextAction(type="close_duplicate", title="Close as duplicate", channel="none",
                          body=f"No payment. This invoice duplicates run #{run}. Optionally tell {vname} that "
                               f"invoice {ex.invoice_number} was received twice and only the first will be paid.",
                          note="The original invoice keeps its own status; nothing here changes it.")

    if _by(checks, "R05") and decision.decision == "REJECT":
        return NextAction(type="vendor_not_found", title="Unknown vendor – do not pay", channel="email", to=AP_MAIL,
                          subject=f"Unknown vendor on invoice {ex.invoice_number}",
                          body=f"Hello,\n\nWe received an invoice from \"{ex.vendor_name}\" (GSTIN "
                               f"{ex.vendor_gstin or 'not printed'}) that does not match any vendor in the master. "
                               "Please check whether this supplier should be onboarded through the normal vendor-creation "
                               f"process (KYC, GST and bank verification). Until then the invoice ({_inv_ref(ex)}) will not be paid.\n\n{AP_SIGN}")

    r10 = _by(checks, "R10")
    if r10:
        cands = r10.evidence.get("candidates", [])
        sug = r10.evidence.get("suggested_po")
        lines = "\n".join(f"  • {c['po_id']} – score {c['score']:.0%} ({c['reasons'][0]})" for c in cands) or "  (none found)"
        if sug:
            body = (f"Hello,\n\nInvoice {_inv_ref(ex)} from {vname} carries no PO number"
                    + (f" (it says: \"{ex.po_reference_text}\")" if ex.po_reference_text else "") +
                    f".\n\nThe closest open POs for this vendor are:\n{lines}\n\nCould you confirm that {sug} is the right one "
                    "(reply \"confirmed\") or tell us the correct PO? Once confirmed, we will run the 3-way match and release it.\n\n" + AP_SIGN)
            return NextAction(type="confirm_po", title=f"Confirm suggested PO {sug}", channel="email", to=BUYER_MAIL,
                              subject=f"Please confirm PO for invoice {ex.invoice_number} ({vname})", body=body,
                              note="Or use the 'Confirm PO' button on this page to re-run matching against the suggestion.")
        body = (f"Hello,\n\nInvoice {_inv_ref(ex)} from {vname} has no PO and no open PO for this vendor resembles it. "
                "Is this an approved non-PO purchase? If so please share the budget owner's approval or raise a "
                f"retroactive PO; otherwise we will return it to the vendor.\n\n{AP_SIGN}")
        return NextAction(type="non_po_invoice", title="Treat as non-PO invoice", channel="email", to=BUYER_MAIL,
                          subject=f"Non-PO invoice {ex.invoice_number} from {vname}", body=body)

    r12, r13 = _by(checks, "R12"), _by(checks, "R13")
    if r12 or r13:
        pts = []
        extra = ""
        if r12:
            for ln in r12.evidence.get("lines", []):
                if ln.get("qty_ok") is False and ln.get("open_qty") is not None:
                    allowed = ln["open_qty"]
                    pts.append(f"It bills {fmt_qty(ln['this_qty'])} × {ln['description']}, but only {fmt_qty(allowed)} "
                               f"remain unbilled against goods received ({fmt_qty(ln['received_qty'])} received, "
                               f"{fmt_qty(ln['previously_invoiced_qty'])} already invoiced).")
                    over = ln["qty_delta"]
                    extra = (f"\nPlease send a revised invoice for no more than {fmt_qty(allowed)} unit(s) "
                             f"({fmt_inr(allowed * ln['inv_unit_price'])} before GST), or a credit note for the {fmt_qty(over)} "
                             "excess unit(s). If more units were delivered, we will first confirm receipt in our warehouse system.")
        if r13:
            e = r13.evidence
            pts.append(f"Together with earlier invoices it brings billing on {e['po_id']} to "
                       f"{fmt_inr(e['total_billed_after'])} against a PO value of {fmt_inr(e['po_amount'])} "
                       f"({fmt_inr(e['over_by'])} over).")
        body = (f"Dear {vname} team,\n\nThank you for invoice {_inv_ref(ex)}. We are unable to process it as submitted:\n"
                + "\n".join(f"  • {p}" for p in pts) + "\n" + extra + f"\n\n{AP_SIGN}")
        return NextAction(type="vendor_email", title="Ask the vendor for a corrected invoice / credit note",
                          channel="email", to=vmail, subject=f"Invoice {ex.invoice_number} – exceeds open PO balance", body=body,
                          note="Copy the buyer if you think the PO itself needs to be increased.")

    r11 = _by(checks, "R11")
    if r11:
        body = (f"Dear {vname} team,\n\nInvoice {_inv_ref(ex)} does not match our purchase order: {r11.message}\n\n"
                f"Please confirm the agreed price or send a corrected invoice.\n\n{AP_SIGN}")
        return NextAction(type="vendor_email", title="Query the price with the vendor", channel="email", to=vmail,
                          subject=f"Invoice {ex.invoice_number} – price differs from PO", body=body)

    r05 = _by(checks, "R05")
    if r05:
        return NextAction(type="vendor_review", title="Confirm the vendor identity", channel="email", to=AP_MAIL,
                          subject=f"Confirm vendor for invoice {ex.invoice_number}",
                          body=f"Hello,\n\n{r05.message}\nPlease confirm the vendor in the master (or correct the invoice) and re-run.\n\n{AP_SIGN}")

    fixes = [c.message for c in checks if c.status == "fail" and c.rule_id in ("R01", "R02", "R03", "R04", "R14", "R15")]
    if fixes:
        body = (f"Dear {vname} team,\n\nWe could not process invoice {ex.invoice_number or '(no number)'}:\n"
                + "\n".join(f"  • {f}" for f in fixes) + f"\n\nPlease send a corrected or clearer copy.\n\n{AP_SIGN}")
        return NextAction(type="vendor_email", title="Ask the vendor for a corrected invoice", channel="email",
                          to=vmail, subject=f"Invoice {ex.invoice_number or ''} – correction needed", body=body)

    sys_err = next((c for c in checks if c.rule_id == "SYS"), None)
    return NextAction(type="manual_review", title="Manual review", channel="none",
                      body=(sys_err.message if sys_err else "A person should review the failed checks, then approve, "
                                                            "reject or re-run."))
