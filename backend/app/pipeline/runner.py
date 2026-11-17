"""Orchestrates the 8 stages, persists every stage row (the SSE stream reads them) and never crashes a run."""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

from sqlalchemy.orm import Session

from .. import config
from ..db import SessionLocal
from ..models import AuditLog, Run, RunFile, RunStage, Vendor, utcnow
from ..schemas import CheckResult, Decision, ExtractedInvoice
from ..util import fmt_inr, jsonable
from . import actions, decide as decide_mod, duplicate, explain, extract, intake, match, validate


@dataclass
class StageOut:
    summary: str
    checks: list[CheckResult] = field(default_factory=list)
    details: dict = field(default_factory=dict)
    status: Optional[str] = None  # override the status derived from the checks


@dataclass
class Ctx:
    db: Session
    run: Run
    pdf: bytes
    po_override: Optional[str] = None
    ex: Optional[ExtractedInvoice] = None
    ex_info: dict = field(default_factory=dict)
    vendor: Optional[Vendor] = None
    stage_checks: dict[str, list[CheckResult]] = field(default_factory=dict)
    decision: Optional[Decision] = None

    def all_checks(self) -> list[CheckResult]:
        out: list[CheckResult] = []
        for k in config.STAGE_KEYS:
            out += self.stage_checks.get(k, [])
        return out


class StageSkipped(Exception):
    pass


def stage_status(checks: list[CheckResult]) -> str:
    if any(c.status == "fail" and c.severity == "reject" for c in checks):
        return "failed"
    if any(c.status == "fail" for c in checks) or any(c.status == "warn" for c in checks):
        return "warning"
    if any(c.status == "skipped" for c in checks):
        return "skipped"  # part of the stage was deliberately not evaluated (e.g. duplicate invoice)
    return "passed"


def _count_summary(checks: list[CheckResult]) -> str:
    p = sum(c.status == "pass" for c in checks)
    w = sum(c.status == "warn" for c in checks)
    f = sum(c.status == "fail" for c in checks)
    s = sum(c.status == "skipped" for c in checks)
    bits = [f"{p} passed"] + ([f"{w} warning"] if w else []) + ([f"{f} failed"] if f else []) + \
           ([f"{s} not evaluated"] if s else [])
    return ", ".join(bits)


# ============================================================ stage implementations
def st_intake(ctx: Ctx) -> StageOut:
    meta = intake.run_intake(ctx.pdf, ctx.run.file_name)
    ctx.run.file_meta = meta
    ctx.run.file_sha = meta["sha256"]
    kb = max(1, meta["size_bytes"] // 1024)
    return StageOut(f"{meta['kind']} · {meta['pages']} page · {kb} KB · SHA-256 {meta['sha256'][:10]}…",
                    details={"file_meta": meta},
                    status="passed")


def st_extract(ctx: Ctx) -> StageOut:
    meta = ctx.run.file_meta
    ex, info = extract.run_extract(ctx.pdf, meta["sha256"], meta["has_text_layer"], ctx.run.file_name)
    ctx.ex, ctx.ex_info = ex, info
    r = ctx.run
    r.extracted = jsonable(ex)
    r.extraction_info = jsonable(info)
    r.vendor_name, r.invoice_number = ex.vendor_name, ex.invoice_number
    r.invoice_number_norm = ex.invoice_number_normalised
    r.invoice_date = ex.invoice_date.isoformat() if ex.invoice_date else None
    r.total = str(ex.total) if ex.total is not None else None
    r.net_amount = str(match.net_amount(ex))
    checks = extract.check_extraction(ex, info)
    src = {"llm_live": "LLM (live)", "llm_cached": "LLM (cached)", "seed_cached": "Pre-recorded extraction (cached)"}[info["source"]]
    cc = info["crosscheck"]
    cc_txt = ("text layer agrees" if cc.get("agreed") else "TEXT LAYER DISAGREES") if cc.get("available") else "scan – no text layer"
    return StageOut(f"Read {len(ex.line_items)} line item(s), total {fmt_inr(ex.total)} · {src} · {cc_txt}",
                    checks, {"extraction": info, "warnings": info.get("warnings", [])})


def st_validate(ctx: Ctx) -> StageOut:
    checks = validate.run_validate(ctx.ex)
    return StageOut(_count_summary(checks), checks)


def st_vendor(ctx: Ctx) -> StageOut:
    vendor, checks, det = match.check_vendor(ctx.db, ctx.ex)
    ctx.vendor = vendor
    ctx.run.vendor_id = vendor.id if vendor else None
    head = f"{vendor.name} ({vendor.id})" if vendor else "Vendor not recognised"
    return StageOut(f"{head} · {_count_summary(checks)}", checks, det)


def st_duplicate(ctx: Ctx) -> StageOut:
    checks, det = duplicate.check_duplicates(ctx.db, ctx.ex, ctx.vendor, ctx.run.id, ctx.run.file_sha)
    txt = f"Possible duplicate of run #{det['duplicate_of']}" if det.get("duplicate_of") else "No duplicate found"
    return StageOut(f"{txt} · compared with {det.get('compared_with', 0)} earlier invoice(s)", checks, det)


def st_po(ctx: Ctx) -> StageOut:
    dup = next((c for c in ctx.stage_checks.get("duplicate", [])
                if c.status == "fail" and c.severity == "reject" and c.evidence.get("duplicate_of_run")), None)
    res = match.run_po_match(ctx.db, ctx.ex, ctx.vendor, ctx.run.id, ctx.po_override,
                             duplicate_of=dup.evidence["duplicate_of_run"] if dup else None)
    r = ctx.run
    r.po_id = res.po.id if res.po else None
    r.line_matches = jsonable(res.line_matches) if res.line_matches else None
    r.po_balance = jsonable(res.po_balance) if res.po_balance else None
    r.po_candidates = jsonable(res.candidates) if res.candidates else None
    if res.po:
        head = f"Matched {res.po.id} ({res.po.type})"
    elif res.candidates and res.candidates["candidates"]:
        c = res.candidates["candidates"][0]
        head = f"No PO number · best guess {c['po_id']} ({c['score']:.0%})"
    else:
        head = "No PO found"
    return StageOut(f"{head} · {_count_summary(res.checks)}", res.checks,
                    {**res.details, "line_matches": jsonable(res.line_matches), "po_balance": jsonable(res.po_balance),
                     "candidates": jsonable(res.candidates)})


def st_decision(ctx: Ctx) -> StageOut:
    d = decide_mod.decide(ctx.all_checks())
    ctx.decision = d
    r = ctx.run
    r.decision = d.decision
    r.decision_detail = jsonable({**d.model_dump(), "short_reason": decide_mod.short_reason(d, ctx.all_checks())})
    # run.status stays PROCESSING until the very last stage has finished (set in process_run),
    # so a viewer never sees a final status next to a stale explanation.
    status = {"APPROVE": "passed", "PENDING": "warning", "REJECT": "failed"}[d.decision]
    label = d.decision + (" · SECURITY HOLD" if d.security_hold else "")
    return StageOut(f"{label} · rules fired: {', '.join(d.fired_rules) or 'none'}", [],
                    {"decision": jsonable(d)}, status=status)


def st_explain(ctx: Ctx) -> StageOut:
    ex, checks = ctx.ex or ExtractedInvoice(), ctx.all_checks()
    text, src = explain.explain(ctx.decision, checks, ex)
    action = actions.draft_next_action(ctx.decision, checks, ex, ctx.vendor)
    ctx.run.explanation, ctx.run.explanation_source = text, src
    ctx.run.next_action = jsonable(action)
    return StageOut(f"{action.title} · explanation by {'LLM' if src.startswith('llm') else 'template'}", [],
                    {"explanation": text, "explanation_source": src, "next_action": jsonable(action)}, status="passed")


STAGE_FUNCS: list[tuple[str, Callable[[Ctx], StageOut]]] = [
    ("intake", st_intake), ("extract", st_extract), ("validate", st_validate), ("vendor", st_vendor),
    ("duplicate", st_duplicate), ("po_match", st_po), ("decision", st_decision), ("explain", st_explain)]
FATAL = {"intake", "extract"}
NEEDS_EXTRACT = {"validate", "vendor", "duplicate", "po_match"}


# ============================================================ run lifecycle
def create_run(db: Session, filename: str, data: bytes, source: str = "upload",
               created_at: Optional[datetime] = None) -> Run:
    run = Run(file_name=filename, source=source, status="PROCESSING", created_at=created_at or utcnow(),
              file_sha=intake.sha256(data))
    db.add(run)
    db.flush()
    db.add(RunFile(run_id=run.id, content=data))
    db.add(AuditLog(run_id=run.id, actor="system", action="created", reason=f"Received {filename} ({source})"))
    db.commit()
    return run


def _upsert_stage(db: Session, run_id: int, seq: int, key: str, **vals) -> RunStage:
    row = db.query(RunStage).filter_by(run_id=run_id, stage=key).first()
    if row is None:
        row = RunStage(run_id=run_id, seq=seq, stage=key)
        db.add(row)
    for k, v in vals.items():
        setattr(row, k, v)
    db.commit()
    return row


def _load_ctx(db: Session, run: Run, pdf: bytes, start_idx: int, po_override: Optional[str]) -> Ctx:
    ctx = Ctx(db=db, run=run, pdf=pdf, po_override=po_override)
    if start_idx > 0:
        if run.extracted:
            ctx.ex = ExtractedInvoice.model_validate(run.extracted)
        ctx.ex_info = run.extraction_info or {}
        if run.vendor_id:
            ctx.vendor = db.get(Vendor, run.vendor_id)
        for row in db.query(RunStage).filter(RunStage.run_id == run.id, RunStage.seq < start_idx).all():
            ctx.stage_checks[row.stage] = [CheckResult.model_validate(c) for c in (row.details or {}).get("checks", [])]
    return ctx


# ---- concurrency -------------------------------------------------------------------------------------------
# Stages 5-8 (duplicate check -> PO balance -> decision -> final status) read what earlier runs decided, so two
# runs overlapping there could both pass R07/R08/R12/R13 and over-approve a PO. They are therefore serialised by a
# process-wide lock held until the final status is committed. (One worker process; with several workers use a
# database advisory lock instead.) Stages 1-4 stay parallel.
PIPELINE_LOCK = threading.RLock()
CRITICAL_FROM = config.STAGE_KEYS.index("duplicate")
_STATE = threading.Condition()
_active = 0
_resetting = False


@contextmanager
def exclusive():
    """Block new runs and wait for running ones to finish (used by the demo reset, which drops the tables)."""
    global _resetting
    with _STATE:
        _resetting = True
        _STATE.wait_for(lambda: _active == 0, timeout=90)
    try:
        yield
    finally:
        with _STATE:
            _resetting = False
            _STATE.notify_all()


def process_run(run_id: int, start_stage: str = "intake", po_override: Optional[str] = None) -> None:
    """Public entry point: registers the run as active (so a reset waits for it), then runs the pipeline."""
    global _active
    with _STATE:
        while _resetting:
            _STATE.wait(0.5)
        _active += 1
    try:
        _process_run_inner(run_id, start_stage, po_override)
    finally:
        with _STATE:
            _active -= 1
            _STATE.notify_all()


def _process_run_inner(run_id: int, start_stage: str = "intake", po_override: Optional[str] = None) -> None:
    """Runs (or re-runs from `start_stage`) the pipeline for one run. Safe to call from a thread."""
    db = SessionLocal()
    holding = False
    try:
        run = db.get(Run, run_id)
        pdf = db.get(RunFile, run_id).content
        start_idx = config.STAGE_KEYS.index(start_stage)
        if po_override is not None:
            run.po_override = po_override
        run.status = "PROCESSING"
        run.finished_at = None
        run.error = None
        run.decision, run.decision_detail = None, {}
        run.explanation = run.explanation_source = run.next_action = None
        db.query(RunStage).filter(RunStage.run_id == run_id, RunStage.seq >= start_idx).delete()
        db.commit()
        ctx = _load_ctx(db, run, pdf, start_idx, po_override or run.po_override)
        total_ms = 0
        aborted_at: Optional[str] = None
        for idx, (key, fn) in enumerate(STAGE_FUNCS):
            if idx < start_idx:
                continue
            if idx >= CRITICAL_FROM and not holding:
                PIPELINE_LOCK.acquire()
                holding = True
                db.rollback()  # drop any open transaction so the queries below see what earlier runs committed
            started = utcnow()
            _upsert_stage(db, run_id, idx, key, status="running", started_at=started, finished_at=None,
                          duration_ms=None, summary="", details={})
            if config.STAGE_DELAY_MS:
                time.sleep(config.STAGE_DELAY_MS / 1000)
            t0 = time.perf_counter()
            try:
                if aborted_at and (key in NEEDS_EXTRACT or (key == "extract" and aborted_at == "intake")):
                    raise StageSkipped(f"Skipped because the {aborted_at} stage failed")
                out = fn(ctx)
                status = out.status or stage_status(out.checks)
                summary, details = out.summary, {**out.details, "checks": jsonable(out.checks)}
                ctx.stage_checks[key] = out.checks
            except StageSkipped as e:
                status, summary, details = "skipped", str(e), {"checks": []}
                ctx.stage_checks[key] = []
            except Exception as e:  # noqa: BLE001 – the pipeline must never crash a run
                db.rollback()
                run = db.get(Run, run_id)
                ctx.run = run
                msg = f"Processing error at stage {key}: {type(e).__name__}: {e}"
                chk = CheckResult(rule_id="SYS", name="Processing error", stage=key, status="fail", severity="pending",
                                  message=msg, evidence={"stage": key, "error": str(e)})
                ctx.stage_checks[key] = [chk]
                status, summary, details = "failed", msg, {"checks": jsonable([chk]), "error": str(e)}
                run.error = msg
                if key in FATAL:
                    aborted_at = key
            ms = int((time.perf_counter() - t0) * 1000)
            total_ms += ms
            if key == "intake" and status != "failed":
                pass
            _upsert_stage(db, run_id, idx, key, status=status, finished_at=utcnow(), duration_ms=ms,
                          summary=summary, details=details)
            db.commit()
        # a hard failure before the decision stage still leaves a decision (PENDING) – see st_decision
        run = db.get(Run, run_id)
        run.duration_ms = total_ms
        run.finished_at = utcnow()
        # final status is set last; if the decision stage itself blew up there is no decision => PENDING
        run.status = {"APPROVE": "APPROVED", "PENDING": "PENDING", "REJECT": "REJECTED"}.get(run.decision or "", "PENDING")
        db.commit()
    except Exception:  # last-resort guard so a run never stays 'PROCESSING' forever
        db.rollback()
        run = db.get(Run, run_id)
        if run:
            run.status = "PENDING"
            run.error = "Unexpected error while processing"
            run.finished_at = utcnow()
            db.commit()
    finally:
        db.close()
        if holding:
            PIPELINE_LOCK.release()


def start_background(run_id: int, start_stage: str = "intake", po_override: Optional[str] = None) -> threading.Thread:
    t = threading.Thread(target=process_run, args=(run_id, start_stage, po_override), daemon=True,
                         name=f"run-{run_id}")
    t.start()
    return t


def seed_history(db: Session) -> None:
    """Process the historical sample invoices so the dashboard looks lived-in (real pipeline, backdated)."""
    import json
    manifest = json.loads((config.SAMPLES_DIR / "manifest.json").read_text(encoding="utf-8"))
    old_delay = config.STAGE_DELAY_MS
    config.STAGE_DELAY_MS = 0
    try:
        for h in manifest.get("historical", []):
            p = config.SAMPLES_DIR / h["file"]
            created = utcnow() - timedelta(days=h["days_ago"], hours=1)
            run = create_run(db, p.name, p.read_bytes(), source="seed", created_at=created)
            _process_run_inner(run.id)      # (not process_run: the demo reset holds `exclusive()` while seeding)
            r = db.get(Run, run.id)
            db.refresh(r)
            r.created_at = created
            r.finished_at = created + timedelta(milliseconds=r.duration_ms or 0)
            db.commit()
    finally:
        config.STAGE_DELAY_MS = old_delay
