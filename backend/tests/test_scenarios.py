"""One test per scenario in the brief: asserts the decision AND the rule IDs that fired."""
from decimal import Decimal

from app.models import AuditLog, Run, RunStage
from app.schemas import ActionRequest
from app.services import ActionError, apply_action

from conftest import fired


def test_01_happy_path_goods_three_way(demo):
    _, runs = demo
    r = runs["01_happy_sgi_0418.pdf"]
    assert r.decision == "APPROVE" and r.status == "APPROVED"
    assert fired(r) == set()
    assert r.po_id == "PO-2026-1001" and r.vendor_id == "V001"
    assert r.total == "71980.00"
    assert {"R03", "R04", "R05", "R06", "R11", "R12", "R13"} <= set(r.decision_detail["passed_rules"])


def test_02_happy_service_igst(demo):
    _, runs = demo
    r = runs["02_happy_nimbus_0091.pdf"]
    assert r.decision == "APPROVE" and fired(r) == set()
    assert r.po_id == "PO-2026-1004" and r.total == "100300.00"
    assert r.extracted["tax_lines"][0]["type"] == "IGST"


def test_03a_03b_split_po_within_balance(demo):
    _, runs = demo
    a, b = runs["03a_split_apex_1101.pdf"], runs["03b_split_apex_1102.pdf"]
    assert a.decision == "APPROVE" and b.decision == "APPROVE"
    assert Decimal(b.po_balance["invoiced_to_date"]) == Decimal("24000.00")      # only 03a counted before 03b
    assert Decimal(b.line_matches[0]["previously_invoiced_qty"]) == 48


def test_03c_over_billed_fires_r12_and_r13(demo):
    _, runs = demo
    r = runs["03c_split_apex_1103.pdf"]
    assert r.decision == "PENDING"
    assert {"R12", "R13"} <= fired(r)
    lm = r.line_matches[0]
    assert Decimal(lm["open_qty"]) == 30 and Decimal(lm["qty_delta"]) == 3
    assert Decimal(r.po_balance["over_by"]) == Decimal("1500.00")
    assert Decimal(r.po_balance["invoiced_to_date"]) == Decimal("45000.00")


def test_04_implied_po_suggests_1003_not_the_decoy(demo):
    _, runs = demo
    r = runs["04_implied_po_kaveri_2231.pdf"]
    assert r.decision == "PENDING" and "R10" in fired(r)
    cands = r.po_candidates["candidates"]
    assert cands[0]["po_id"] == "PO-2026-1003" and cands[0]["score"] >= 0.75
    assert "PO-2026-1009" not in [c["po_id"] for c in cands[:1]]
    assert "PO-2026-1009" in [e["po_id"] for e in r.po_candidates["excluded"]]   # shown as an excluded decoy
    assert cands[1]["po_id"] == "PO-2026-1007" and cands[1]["score"] < 0.6


def test_04_confirm_po_then_approve(demo):
    db, runs = demo
    r = runs["04_implied_po_kaveri_2231.pdf"]
    apply_action(db, r.id, ActionRequest(type="confirm_po", po_id="PO-2026-1003", reason="Buyer confirmed by phone"),
                 background=False)
    db.expire_all()
    r = db.get(Run, r.id)
    assert r.decision == "APPROVE" and r.status == "APPROVED" and r.po_id == "PO-2026-1003"
    assert db.query(AuditLog).filter_by(run_id=r.id, action="confirm_po").count() == 1
    # stages 1-5 were kept, 6-8 re-run
    assert db.query(RunStage).filter_by(run_id=r.id).count() == 8


def test_05_scanned_duplicate_rejected_by_r08(demo):
    _, runs = demo
    r = runs["05_dup_sgi_0418_scan.pdf"]
    first = runs["01_happy_sgi_0418.pdf"]
    assert r.file_meta["has_text_layer"] is False
    assert r.file_sha != first.file_sha                      # the hash differs...
    assert r.decision == "REJECT" and fired(r) == {"R08"}    # ...the fuzzy rule alone catches it (R07 literal match fails)
    assert r.explanation and f"#{first.id}" in r.explanation
    # PO matching is skipped for a duplicate: R10-R14 are 'skipped', never fired, never in the explanation
    db, _ = demo
    stage = db.query(RunStage).filter_by(run_id=r.id, stage="po_match").one()
    by_rule = {c["rule_id"]: c for c in stage.details["checks"]}
    for rule in ("R10", "R11", "R12", "R13", "R14"):
        if rule == "R10" and by_rule["R09"]["status"] == "pass":
            continue                                          # R10 only exists when the PO is unresolved
        assert by_rule[rule]["status"] == "skipped", rule
        assert by_rule[rule]["message"] == f"Not evaluated – invoice is a duplicate of run #{first.id}"
    assert not {"R11", "R12", "R13", "R14"} & set(r.decision_detail["passed_rules"] + r.decision_detail["warning_rules"])
    assert stage.status == "skipped" and r.line_matches is None and r.po_balance is None
    assert not any(x in r.explanation for x in ("received", "PO value", "billed"))


def test_06_bank_change_is_a_security_hold(demo):
    _, runs = demo
    r = runs["06_bankchange_orbit_7782.pdf"]
    assert r.decision == "PENDING" and fired(r) == {"R06"}
    assert r.decision_detail["security_hold"] is True
    assert r.next_action["type"] == "security_verification"
    assert "phone number on file" in r.next_action["note"]
    assert "+91 22 6677 3300" in r.next_action["body"]


def test_manual_override_needs_reason_and_is_audited(demo):
    db, runs = demo
    r = runs["06_bankchange_orbit_7782.pdf"]
    try:
        apply_action(db, r.id, ActionRequest(type="approve", reason=""))
        assert False, "expected ActionError"
    except ActionError:
        pass
    apply_action(db, r.id, ActionRequest(type="reject", reason="Vendor could not confirm the change"))
    db.expire_all()
    r = db.get(Run, r.id)
    assert r.status == "REJECTED" and r.decision == "PENDING"     # system decision is preserved
    log = db.query(AuditLog).filter_by(run_id=r.id, action="reject_override").one()
    assert log.reason and log.actor


def test_exact_duplicate_r07_also_skips_po_matching(demo):
    """Re-uploading the very same file: R07 + R08(same file) reject, and R11-R14 are not evaluated."""
    from conftest import run_sample
    db, runs = demo
    first = runs["02_happy_nimbus_0091.pdf"]          # APPROVED, so it counts as a non-rejected prior
    again = run_sample(db, "02_happy_nimbus_0091.pdf")
    assert again.decision == "REJECT" and {"R07", "R08"} <= fired(again)
    stage = db.query(RunStage).filter_by(run_id=again.id, stage="po_match").one()
    skipped = {c["rule_id"] for c in stage.details["checks"] if c["status"] == "skipped"}
    assert {"R11", "R12", "R13", "R14"} <= skipped
    assert not {"R11", "R12", "R13", "R14"} & fired(again)
    assert f"#{first.id}" in again.explanation


def test_pending_level_duplicate_still_runs_po_matching(demo):
    """Only a REJECT-level duplicate skips matching. A medium-confidence R08 (severity pending) must not."""
    from app.models import Vendor
    from app.pipeline import match
    from app.schemas import ExtractedInvoice
    db, runs = demo
    ex = ExtractedInvoice.model_validate(runs["06_bankchange_orbit_7782.pdf"].extracted)
    vendor = db.get(Vendor, "V005")
    with_skip = match.run_po_match(db, ex, vendor, 999, duplicate_of=1)
    without = match.run_po_match(db, ex, vendor, 999, duplicate_of=None)
    assert {c.rule_id: c.status for c in with_skip.checks if c.rule_id in ("R11", "R12", "R13", "R14")} == \
        {r: "skipped" for r in ("R11", "R12", "R13", "R14")}
    assert all(c.status in ("pass", "fail") for c in without.checks if c.rule_id in ("R11", "R12", "R13", "R14"))
    assert without.line_matches and without.po_balance          # evaluated for real


def test_bad_inputs_never_crash_a_run(demo):
    """A non-PDF and a PDF the model has never seen (no API key) both end in PENDING with a reason."""
    from app import config
    from app.pipeline import runner
    db, _ = demo
    # a valid PDF whose SHA-256 is not in the cache: a known sample plus a trailing comment
    unseen = (config.SAMPLES_DIR / "01_happy_sgi_0418.pdf").read_bytes() + b"\n% never seen before\n"
    for name, data, stage in (("junk.pdf", b"this is not a pdf", "intake"), ("unknown.pdf", unseen, "extract")):
        r = runner.create_run(db, name, data, source="upload")
        runner.process_run(r.id)
        db.expire_all()
        r = db.get(Run, r.id)
        assert r.status == "PENDING" and r.decision == "PENDING"
        assert "Processing error at stage " + stage in (r.error or "")
        rows = {s.stage: s.status for s in db.query(RunStage).filter_by(run_id=r.id)}
        assert rows[stage] == "failed" and rows["decision"] == "warning" and len(rows) == 8
        assert r.next_action is not None


def test_explanations_only_contain_numbers_from_the_checks(demo):
    """M6 checkpoint: no invented numbers in any explanation or next-action draft."""
    import json
    from app.pipeline.explain import _numbers
    from app.models import RunStage
    db, runs = demo
    for name, r in runs.items():
        stages = db.query(RunStage).filter_by(run_id=r.id).all()
        facts = json.dumps([s.details.get("checks", []) for s in stages]) + json.dumps(r.extracted) + str(r.total)
        allowed = _numbers(facts)
        allowed |= {a.split(".")[0] for a in allowed}
        # scores stored as 0.44 are shown as "44%": same fact, different formatting
        allowed |= {str(round(float(a) * 100)) for a in list(allowed) if "." in a and 0 <= float(a) <= 1}
        # masked account numbers show only their last four digits
        allowed |= {a[-4:] for a in list(allowed) if len(a) >= 8}
        # numbers are also written in Indian grouping / without decimals in prose
        for text in (r.explanation, (r.next_action or {}).get("body", "")):
            for n in _numbers(text or ""):
                assert n in allowed or n.split(".")[0] in allowed or n in {"1", "2", "3", "4"}, \
                    f"{name}: '{n}' is not backed by any check result"


def test_history_is_seeded_and_counts_towards_dashboard(demo):
    db, _ = demo
    seeded = db.query(Run).filter_by(source="seed").all()
    assert len(seeded) == 3 and all(s.decision == "APPROVE" for s in seeded)
