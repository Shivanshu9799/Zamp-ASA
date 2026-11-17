"""Regression tests for the issues raised in the external code review."""
from decimal import Decimal

import pytest

import conftest  # noqa: F401
from app import config
from app.models import PurchaseOrder, Vendor
from app.pipeline import extract, match, validate
from app.schemas import BankDetails, ExtractedInvoice, LineItem, TaxLine

D = Decimal


def line(desc="Item", qty="10", price="100", amount="1000", rate=None):
    return LineItem(description=desc, quantity=D(qty) if qty else None, unit_price=D(price) if price else None,
                    amount=D(amount), tax_rate=D(rate) if rate else None)


# ------------------------------------------------------------------ R03: total is always reconciled
def test_missing_subtotal_still_reconciles_the_total():
    ok = ExtractedInvoice(line_items=[line()], tax_total=D("180"), total=D("1180"))
    assert validate.check_math(ok).status == "pass"
    bad = ExtractedInvoice(line_items=[line()], tax_total=D("180"), total=D("1500"))      # used to slip through
    r = validate.check_math(bad)
    assert r.status == "fail" and "1,500.00" in r.message


def test_missing_subtotal_and_tax_total_uses_the_tax_lines():
    ex = ExtractedInvoice(line_items=[line()], tax_lines=[TaxLine(type="IGST", rate=D("18"), amount=D("180"))],
                          total=D("1180"))
    assert validate.check_math(ex).status == "pass"
    ex.total = D("1999")
    assert validate.check_math(ex).status == "fail"


def test_line_without_qty_or_price_is_noted_but_the_totals_still_decide():
    ex = ExtractedInvoice(line_items=[line(qty=None, price=None)], subtotal=D("1000"), tax_total=D("180"), total=D("1180"))
    r = validate.check_math(ex)
    assert r.status == "pass" and r.evidence["lines_without_qty_or_price"] == [1]
    ex.total = D("1300")
    assert validate.check_math(ex).status == "fail"


def test_totals_that_cannot_be_verified_fail_closed():
    ex = ExtractedInvoice(line_items=[LineItem(description="x", amount=None)], total=D("500"))
    assert validate.check_math(ex).status == "fail"


# ------------------------------------------------------------------ R04: several GST slabs
def _multi_rate(total_tax_each="240"):
    return ExtractedInvoice(
        vendor_gstin="27AABCS1234F1Z5", subtotal=D("3000"),
        line_items=[line("A", "10", "100", "1000", "12"), line("B", "10", "200", "2000", "18")],
        tax_lines=[TaxLine(type="CGST", rate=D("6"), amount=D("60")), TaxLine(type="CGST", rate=D("9"), amount=D("180")),
                   TaxLine(type="SGST", rate=D("6"), amount=D("60")), TaxLine(type="SGST", rate=D(str("9")), amount=D(total_tax_each) - D("60"))])


def test_two_gst_slabs_are_not_a_false_failure():
    r = validate.check_gst(_multi_rate())
    assert r.status == "pass", r.message           # 12% and 18% slabs: total tax 480 = 120 + 360
    assert r.evidence["multi_rate"] is True and r.evidence["expected_total_tax"] == D("480.00")


def test_two_gst_slabs_with_a_wrong_total_still_fail():
    ex = _multi_rate()
    ex.tax_lines[0].amount = D("90")                 # CGST now 270 vs SGST 240 and total 510 vs expected 480
    assert validate.check_gst(ex).status == "fail"


def test_gst_falls_back_to_the_lines_when_no_subtotal_was_read():
    ex = ExtractedInvoice(vendor_gstin="27AABCS1234F1Z5", line_items=[line()],
                          tax_lines=[TaxLine(type="CGST", rate=D("9"), amount=D("90")), TaxLine(type="SGST", rate=D("9"), amount=D("90"))])
    assert validate.check_gst(ex).status == "pass"
    ex.tax_lines[0].amount = ex.tax_lines[1].amount = D("50")        # wrong amounts: used to be skipped (base was None)
    assert validate.check_gst(ex).status == "fail"


# ------------------------------------------------------------------ R02
def test_missing_confidence_for_a_critical_field_is_not_a_silent_pass():
    ex = ExtractedInvoice(vendor_name="V", invoice_number="1", total=D("5"), field_confidence={"vendor_name": 0.99})
    r = extract.check_extraction(ex, {"crosscheck": {"available": False, "fields": {}}})[0]
    assert r.status == "fail"
    assert set(r.evidence["confidence_not_reported"]) == {"invoice_number", "invoice_date", "total"}


def test_crosscheck_finds_whole_rupee_amounts_without_decimals(monkeypatch):
    monkeypatch.setattr(extract, "pdf_text", lambda _b: "Tax Invoice INV-9\nTotal Rs. 61,000/-\nSubtotal 51,695\nGSTIN 27AABCS1234F1Z5")
    ex = ExtractedInvoice(invoice_number="INV-9", total=D("61000.00"), subtotal=D("51695.00"), vendor_gstin="27AABCS1234F1Z5")
    cc = extract.crosscheck(b"", ex, True)
    assert cc["agreed"] is True, cc
    ex.total = D("61001.00")
    assert extract.crosscheck(b"", ex, True)["fields"]["total"]["found_in_text"] is False


# ------------------------------------------------------------------ R16: addressee
def test_invoice_addressed_to_another_company_is_flagged():
    assert validate.check_bill_to(ExtractedInvoice(bill_to_name="Meridian Foods Pvt. Ltd.")).status == "pass"
    assert validate.check_bill_to(ExtractedInvoice(bill_to_name="MERIDIAN FOODS PRIVATE LIMITED")).status == "pass"
    bad = validate.check_bill_to(ExtractedInvoice(bill_to_name="Sunrise Beverages Pvt. Ltd."))
    assert bad.status == "fail" and bad.severity == "pending" and "Sunrise" in bad.message
    assert validate.check_bill_to(ExtractedInvoice(bill_to_name=None)).status == "warn"


def test_r16_decides_pending_even_with_a_valid_po(demo):
    from app.pipeline.decide import decide
    db, runs = demo
    ex = ExtractedInvoice.model_validate(runs["01_happy_sgi_0418.pdf"].extracted)
    ex.bill_to_name = "Some Other Buyer Ltd"
    assert decide(validate.run_validate(ex)).decision == "PENDING"


# ------------------------------------------------------------------ line mapping: one PO line billed on two invoice lines
def _apex_two_lots(q1, q2):
    return ExtractedInvoice(vendor_name="Apex", currency="INR", subtotal=D("500") * (D(q1) + D(q2)),
                            line_items=[line("LED floodlight 200W", q1, "500", str(500 * int(q1))),
                                        line("LED floodlight 200W", q2, "500", str(500 * int(q2)))])


def test_two_invoice_lines_on_one_po_line_are_summed_for_the_3_way_match(demo):
    db, _ = demo
    vendor = db.get(Vendor, "V004")
    # PO-2026-1002: 120 received, 90 already billed (03a + 03b approved) -> 30 open
    ok = match.run_po_match(db, _apex_two_lots("10", "10"), vendor, 999, po_override="PO-2026-1002")
    by = {c.rule_id: c for c in ok.checks}
    assert by["R11"].status == "pass", by["R11"].message          # the 2nd lot is NOT "not on the PO"
    assert by["R12"].status == "pass" and [r["po_line_no"] for r in ok.line_matches] == [1, 1]
    over = match.run_po_match(db, _apex_two_lots("20", "15"), vendor, 999, po_override="PO-2026-1002")
    by = {c.rule_id: c for c in over.checks}
    assert by["R12"].status == "fail", "each lot alone fits in 30 but together (35) they do not"
    assert "35 in total" in by["R12"].message and over.line_matches[0]["qty_delta"] == D("5")


def test_a_genuinely_different_second_line_is_still_unmatched(demo):
    db, _ = demo
    ex = _apex_two_lots("5", "5")
    ex.line_items[1].description = "Industrial welding robot"
    res = match.run_po_match(db, ex, db.get(Vendor, "V004"), 999, po_override="PO-2026-1002")
    assert {c.rule_id: c.status for c in res.checks}["R11"] == "fail"
    assert res.line_matches[1]["po_line_no"] is None


# ------------------------------------------------------------------ concurrency
def test_the_same_invoice_uploaded_twice_at_once_is_approved_only_once(monkeypatch):
    from app import bootstrap
    from app.db import SessionLocal
    from app.models import Run
    from app.pipeline import runner
    bootstrap.reset_demo()
    monkeypatch.setattr(config, "STAGE_DELAY_MS", 40)          # make the two runs genuinely overlap
    db = SessionLocal()
    data = (config.SAMPLES_DIR / "01_happy_sgi_0418.pdf").read_bytes()
    ids = [runner.create_run(db, f"dup{i}.pdf", data, "upload").id for i in range(2)]
    threads = [runner.start_background(i) for i in ids]
    for t in threads:
        t.join(30)
    db.expire_all()
    statuses = sorted(db.get(Run, i).status for i in ids)
    db.close()
    assert statuses == ["APPROVED", "REJECTED"], statuses


def test_two_invoices_that_only_fit_the_po_one_at_a_time(monkeypatch):
    """03b (42 units) and a second 42-unit copy of different number would both fit alone; PO-1001 allows one."""
    from app import bootstrap
    from app.db import SessionLocal
    from app.models import Run
    from app.pipeline import runner
    bootstrap.reset_demo()
    monkeypatch.setattr(config, "STAGE_DELAY_MS", 40)
    db = SessionLocal()
    # 01 and 05 are the same goods against PO-2026-1001; billing both would exceed the PO and the receipts
    ids = [runner.create_run(db, n, (config.SAMPLES_DIR / n).read_bytes(), "upload").id
           for n in ("01_happy_sgi_0418.pdf", "05_dup_sgi_0418_scan.pdf")]
    for t in [runner.start_background(i) for i in ids]:
        t.join(30)
    db.expire_all()
    approved = [db.get(Run, i) for i in ids if db.get(Run, i).status == "APPROVED"]
    db.close()
    assert len(approved) == 1, "PO-2026-1001 must not be approved twice"


def test_reset_waits_for_running_pipelines_instead_of_dropping_tables_under_them(monkeypatch):
    import time
    from app import bootstrap
    from app.db import SessionLocal
    from app.pipeline import runner
    bootstrap.reset_demo()
    monkeypatch.setattr(config, "STAGE_DELAY_MS", 60)
    db = SessionLocal()
    run = runner.create_run(db, "x.pdf", (config.SAMPLES_DIR / "02_happy_nimbus_0091.pdf").read_bytes(), "upload")
    t = runner.start_background(run.id)
    time.sleep(0.15)                                  # the run is mid-pipeline
    bootstrap.reset_demo()                            # must wait for it
    assert not t.is_alive() and runner._active == 0
    db.close()
