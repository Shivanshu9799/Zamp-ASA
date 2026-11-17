"""Unit tests: no PDFs, no database (except where a tiny fixture is needed)."""
from datetime import date
from decimal import Decimal

import pytest

import conftest  # noqa: F401  (sets the test environment)
from app import config
from app.pipeline import decide as decide_mod, duplicate, explain, extract, validate
from app.pipeline.match import clean_name, desc_sim
from app.schemas import CheckResult, ExtractedInvoice, LineItem, TaxLine
from app.util import (find_dates_in_text, fmt_inr, normalise_invoice_no, parse_amount, parse_date, q2)

D = Decimal


# ---------------------------------------------------------------- normalisation
@pytest.mark.parametrize("raw,norm", [
    ("INV-SGI-0418", "INVSGI418"), ("INVSGI418", "INVSGI418"), ("inv sgi 0418", "INVSGI418"),
    ("NCS/26-27/0091", "NCS262791"), ("APX-1101", "APX1101"), ("000123", "123"), ("", ""), (None, "")])
def test_invoice_number_normalisation(raw, norm):
    assert normalise_invoice_no(raw) == norm


def test_amounts_parse_to_decimal_never_float():
    assert parse_amount("1,00,300.00") == D("100300.00")
    assert parse_amount("Rs. 71,980.00") == D("71980.00")
    assert parse_amount("₹ 5,490") == D("5490")
    assert parse_amount("(1,200.50)") == D("-1200.50")
    assert parse_amount("n/a") is None
    assert isinstance(parse_amount("10.10"), Decimal)


def test_decimal_rounding_is_half_up_and_exact():
    assert q2(D("2.675")) == D("2.68")           # float would give 2.67
    assert q2(D("1000") * D("9") / D("100")) == D("90.00")
    assert D("0.1") + D("0.2") == D("0.3")
    assert fmt_inr(D("100300")) == "₹1,00,300.00"
    assert fmt_inr("61000") == "₹61,000.00"


def test_dates():
    assert parse_date("14-Oct-2026") == date(2026, 10, 14)
    assert parse_date("14/10/2026") == date(2026, 10, 14)      # day-first (India)
    assert parse_date("2026-10-14") == date(2026, 10, 14)
    assert parse_date("garbage") is None
    assert find_dates_in_text("Supplied against your order dated 02-Oct-2026") == [date(2026, 10, 2)]


def test_vendor_name_cleaning_ignores_legal_suffixes():
    assert clean_name("Orbit Logistics Pvt. Ltd.") == clean_name("ORBIT LOGISTICS")
    assert desc_sim("5-Ply Corrugated Box 18x12x12 in", "5-ply corrugated box 18×12×12 in") == 1.0


def test_description_match_survives_extra_text_merged_by_the_reader():
    """Real model output (Gemini) merged a service-period note into the line description."""
    inv = "Managed cloud hosting - Nov 2026\nService period: 01-Nov-2026 to 30-Nov-2026"
    assert desc_sim(inv, "Managed cloud hosting – Nov 2026") >= 0.6
    assert desc_sim("Bubble wrap roll 1m×100m", "5-ply corrugated box 18×12×12 in") < 0.4   # still discriminates


# ---------------------------------------------------------------- fuzzy duplicate
def _inv(no, total, d):
    return ExtractedInvoice(vendor_name="V", invoice_number=no, invoice_number_normalised=normalise_invoice_no(no),
                            total=D(total), invoice_date=d)


def test_fuzzy_duplicate_high_when_number_total_and_date_agree():
    sig = duplicate.fuzzy_signals(_inv("INVSGI418", "71980", date(2026, 10, 16)), "INV-SGI-0418", D("71980.00"),
                                  date(2026, 10, 14), False)
    assert sig["level"] == "high" and sig["invoice_no_similarity"] == 100


def test_fuzzy_duplicate_same_file_is_always_high():
    sig = duplicate.fuzzy_signals(_inv("X1", "10", date(2026, 1, 1)), "Y9", D("999"), date(2026, 6, 1), True)
    assert sig["level"] == "high"


def test_sequential_invoice_numbers_with_different_totals_are_not_duplicates():
    sig = duplicate.fuzzy_signals(_inv("APX-1102", "24780", date(2026, 10, 24)), "APX-1101", D("28320"),
                                  date(2026, 10, 16), False)
    assert sig["invoice_no_similarity"] >= 85 and sig["level"] == "none"


def test_same_total_and_date_but_different_number_is_medium():
    sig = duplicate.fuzzy_signals(_inv("ZZZ-9", "5000", date(2026, 10, 16)), "AAA-1", D("5000"), date(2026, 10, 18), False)
    assert sig["level"] == "medium"


def test_date_outside_window_is_not_high():
    sig = duplicate.fuzzy_signals(_inv("INV-1", "5000", date(2026, 12, 1)), "INV-1", D("5000"), date(2026, 10, 1), False)
    assert sig["level"] == "medium"


# ---------------------------------------------------------------- GST / math validation
def _gst_invoice(types, state="27", base="1000", rate="9", amounts=("90", "90")):
    return ExtractedInvoice(vendor_gstin=f"{state}AABCS1234F1Z5", subtotal=D(base),
                            tax_lines=[TaxLine(type=t, rate=D(rate), amount=D(a)) for t, a in zip(types, amounts)])


def test_gst_intra_state_cgst_sgst_ok():
    assert validate.check_gst(_gst_invoice(["CGST", "SGST"])).status == "pass"


def test_gst_igst_alone_ok_for_inter_state():
    inv = _gst_invoice(["IGST"], state="29", rate="18", amounts=("180",))
    assert validate.check_gst(inv).status == "pass"


def test_gst_igst_on_intra_state_fails():
    inv = _gst_invoice(["IGST"], state="27", rate="18", amounts=("180",))
    assert validate.check_gst(inv).status == "fail"


def test_gst_cgst_without_sgst_fails():
    assert validate.check_gst(_gst_invoice(["CGST"], amounts=("90",))).status == "fail"


def test_gst_unequal_split_fails():
    assert validate.check_gst(_gst_invoice(["CGST", "SGST"], amounts=("90", "70"))).status == "fail"


def test_gst_wrong_amount_fails():
    assert validate.check_gst(_gst_invoice(["CGST", "SGST"], amounts=("95", "95"))).status == "fail"


def test_math_rounding_within_a_rupee_passes_beyond_fails():
    line = LineItem(description="x", quantity=D("3"), unit_price=D("33.33"), amount=D("99.99"))
    ok = ExtractedInvoice(line_items=[line], subtotal=D("99.99"), tax_total=D("18.00"), total=D("118.50"))
    assert validate.check_math(ok).status == "pass"                      # 0.51 off: inside the ₹1 tolerance
    bad = ExtractedInvoice(line_items=[line], subtotal=D("99.99"), tax_total=D("18.00"), total=D("125.00"))
    assert validate.check_math(bad).status == "fail"


def test_math_flags_bad_line_amount():
    line = LineItem(description="x", quantity=D("10"), unit_price=D("100"), amount=D("900"))
    inv = ExtractedInvoice(line_items=[line], subtotal=D("900"), tax_total=D("0"), total=D("900"))
    assert validate.check_math(inv).status == "fail"


def test_zero_total_rejects():
    r15 = validate.check_total_positive(ExtractedInvoice(total=D("0")))
    assert r15.status == "fail" and r15.severity == "reject"


# ---------------------------------------------------------------- decision precedence (synthetic)
def C(rule, status, severity):
    return CheckResult(rule_id=rule, name=rule, stage="x", status=status, severity=severity, message=f"{rule} {status}")


def test_decide_all_pass_is_approve():
    d = decide_mod.decide([C("R03", "pass", "pending"), C("R05", "pass", "reject")])
    assert d.decision == "APPROVE" and d.fired_rules == []


def test_decide_warn_does_not_block():
    assert decide_mod.decide([C("R02", "warn", "info"), C("R03", "pass", "pending")]).decision == "APPROVE"


def test_decide_pending_rule_gives_pending():
    d = decide_mod.decide([C("R12", "fail", "pending"), C("R13", "fail", "pending"), C("R03", "pass", "pending")])
    assert d.decision == "PENDING" and d.fired_rules == ["R12", "R13"] and not d.security_hold


def test_decide_security_hold_beats_pending_and_is_flagged():
    d = decide_mod.decide([C("R12", "fail", "pending"), C("R06", "fail", "security")])
    assert d.decision == "PENDING" and d.security_hold and d.fired_rules[0] == "R06"


def test_decide_reject_beats_everything_and_returns_all_rules():
    d = decide_mod.decide([C("R12", "fail", "pending"), C("R06", "fail", "security"), C("R07", "fail", "reject")])
    assert d.decision == "REJECT" and d.fired_rules == ["R07", "R06", "R12"]


def test_decide_fuzzy_duplicate_medium_is_pending_high_is_reject():
    assert decide_mod.decide([C("R08", "fail", "pending")]).decision == "PENDING"
    assert decide_mod.decide([C("R08", "fail", "reject")]).decision == "REJECT"


# ---------------------------------------------------------------- explanation guard-rail
def test_explanation_numbers_must_be_grounded():
    facts = {"invoice": {"total": "₹71,980.00"}, "failed_checks": [{"finding": "3 units over; PO worth ₹60,000.00"}]}
    assert explain.numbers_are_grounded("The invoice of ₹71,980.00 is 3 units over.", facts)
    assert not explain.numbers_are_grounded("The invoice is ₹99,999.00 over.", facts)


def test_template_explanation_only_uses_check_facts():
    ex = ExtractedInvoice(vendor_name="Acme", invoice_number="A-1", total=D("500"))
    d = decide_mod.decide([C("R12", "fail", "pending")])
    text = explain.template_explanation(d, [C("R12", "fail", "pending")], ex)
    assert "R12 fail" in text and "₹500.00" in text and "Acme" in text


# ---------------------------------------------------------------- extraction normalisation / config
def test_extraction_normalises_money_to_decimal():
    ex = extract.normalise({"invoice_number": "INV-SGI-0418", "invoice_date": "2026-10-14", "total": "71,980.00",
                            "subtotal": "61000", "currency": "Rs.", "line_items": [{"description": "x", "quantity": "100",
                            "unit_price": "450.00", "amount": "45,000.00"}]})
    assert ex.total == D("71980.00") and isinstance(ex.line_items[0].unit_price, Decimal)
    assert ex.invoice_number_normalised == "INVSGI418" and ex.currency == "INR"


def test_gemini_provider_parses_fenced_json_and_builds_a_valid_request(monkeypatch):
    """No network: stub the HTTP layer and check the request shape + response parsing."""
    import json as _json
    import httpx
    from app import llm_gemini
    seen = {}

    def fake_post(url, json=None, timeout=None, headers=None):
        seen.update(url=url, body=json, headers=headers)
        reply = {"candidates": [{"content": {"parts": [{"text": "```json\n" + _json.dumps({"invoice_number": "X-1", "total": "10.00"}) + "\n```"}]}}]}
        return httpx.Response(200, json=reply)

    monkeypatch.setattr(llm_gemini.httpx, "post", fake_post)
    monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(config, "LLM_MODEL", "gemini-test")
    out = llm_gemini.extract_json(b"%PDF-1.4 fake", "read it", extract.tool_schema()["input_schema"])
    assert out == {"invoice_number": "X-1", "total": "10.00"}
    assert seen["url"].endswith("/gemini-test:generateContent") and seen["headers"]["x-goog-api-key"] == "test-key"
    part = seen["body"]["contents"][0]["parts"][0]["inline_data"]
    assert part["mime_type"] == "application/pdf"
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"
    monkeypatch.setattr(config, "LLM_PROVIDER", "gemini")
    inv = extract._call_llm_once(b"%PDF-1.4 fake")           # goes through LLMInvoice validation
    assert inv["invoice_number"] == "X-1"


def test_gemini_http_error_is_raised_not_swallowed(monkeypatch):
    import httpx
    from app import llm_gemini
    monkeypatch.setattr(llm_gemini.httpx, "post", lambda *a, **k: httpx.Response(429, text="quota"))
    with pytest.raises(RuntimeError, match="429"):
        llm_gemini.generate_text("s", "u")


def test_tolerances_match_the_spec():
    assert config.PRICE_TOLERANCE_PCT == D("1.0") and config.TOTAL_ROUNDING_ABS == D("1.00")
    assert config.QTY_TOLERANCE == 0 and (config.VENDOR_FUZZY_AUTO, config.VENDOR_FUZZY_REVIEW) == (92, 80)
    assert config.PO_INFERENCE_SUGGEST == 0.75 and config.DUP_DATE_WINDOW_DAYS == 10
    assert abs(sum(config.PO_INFERENCE_WEIGHTS.values()) - 1.0) < 1e-9
