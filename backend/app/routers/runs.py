from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..events import iso, stream_run_events
from ..models import AuditLog, Run, RunFile, RunStage
from ..pipeline import runner
from ..schemas import ActionRequest
from ..services import ActionError, apply_action

router = APIRouter(prefix="/api/runs", tags=["runs"])
MAX_UPLOAD = 15 * 1024 * 1024


def run_summary(r: Run) -> dict:
    dd = r.decision_detail or {}
    return {
        "id": r.id, "created_at": iso(r.created_at), "finished_at": iso(r.finished_at), "status": r.status,
        "decision": r.decision, "security_hold": bool(dd.get("security_hold")), "source": r.source,
        "file_name": r.file_name, "vendor_id": r.vendor_id, "vendor_name": r.vendor_name,
        "invoice_number": r.invoice_number, "invoice_date": r.invoice_date, "po_id": r.po_id, "total": r.total,
        "net_amount": r.net_amount, "reason": dd.get("short_reason"), "fired_rules": dd.get("fired_rules", []),
        "duration_ms": r.duration_ms, "scanned": (r.file_meta or {}).get("has_text_layer") is False,
    }


def run_detail(db: Session, r: Run) -> dict:
    stages = db.query(RunStage).filter_by(run_id=r.id).order_by(RunStage.seq).all()
    audit = db.query(AuditLog).filter_by(run_id=r.id).order_by(AuditLog.id).all()
    heavy = {"line_matches", "po_balance", "candidates", "file_meta", "extraction"}
    stage_rows = [{"stage": s.stage, "seq": s.seq, "status": s.status, "started_at": iso(s.started_at),
                   "finished_at": iso(s.finished_at), "duration_ms": s.duration_ms, "summary": s.summary,
                   "checks": (s.details or {}).get("checks", []),
                   "details": {k: v for k, v in (s.details or {}).items() if k not in heavy and k != "checks"}}
                  for s in stages]
    dup = next((s.details.get("duplicate_of") for s in stages if s.stage == "duplicate" and s.details), None)
    return {
        **run_summary(r), "file_meta": r.file_meta, "extracted": r.extracted, "extraction_info": r.extraction_info,
        "stages": stage_rows, "decision_detail": r.decision_detail, "explanation": r.explanation,
        "explanation_source": r.explanation_source, "next_action": r.next_action, "line_matches": r.line_matches,
        "po_balance": r.po_balance, "po_candidates": r.po_candidates, "po_override": r.po_override,
        "duplicate_of": dup, "error": r.error,
        "audit": [{"id": a.id, "ts": iso(a.ts), "actor": a.actor, "action": a.action, "reason": a.reason,
                   "details": a.details} for a in audit],
    }


def _sample_bytes(name: str) -> bytes:
    if "/" in name or "\\" in name or not name.lower().endswith(".pdf"):
        raise HTTPException(400, "Unknown sample")
    p = config.SAMPLES_DIR / name
    if not p.is_file():
        raise HTTPException(404, "Unknown sample")
    return p.read_bytes()


@router.post("")
async def create_run(request: Request, db: Session = Depends(get_db)):
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("application/json"):
        body = await request.json()
        name = body.get("sample")
        if not name:
            raise HTTPException(400, "Provide a file upload or {\"sample\": \"<file>.pdf\"}")
        data, filename, source = _sample_bytes(name), name, "sample"
    else:
        form = await request.form()
        up = form.get("file")
        if up is None or not hasattr(up, "read"):
            raise HTTPException(400, "Attach the invoice as the 'file' field")
        data = await up.read()
        filename, source = up.filename or "invoice.pdf", "upload"
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "File is larger than 15 MB")
        if not data:
            raise HTTPException(400, "The file is empty")
    run = runner.create_run(db, filename, data, source)
    runner.start_background(run.id)
    return {"run_id": run.id}


@router.get("")
def list_runs(status: Optional[str] = None, vendor: Optional[str] = None, q: Optional[str] = None,
              date_from: Optional[str] = None, date_to: Optional[str] = None, page: int = 1, page_size: int = 50,
              db: Session = Depends(get_db)):
    query = db.query(Run)
    if status and status.upper() != "ALL":
        query = query.filter(Run.status == status.upper())
    if vendor:
        query = query.filter(or_(Run.vendor_id == vendor, Run.vendor_name.ilike(f"%{vendor}%")))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Run.invoice_number.ilike(like), Run.vendor_name.ilike(like), Run.po_id.ilike(like),
                                 Run.file_name.ilike(like)))
    if date_from:
        query = query.filter(Run.created_at >= date_from)
    if date_to:
        query = query.filter(Run.created_at <= date_to + "T23:59:59")
    total = query.count()
    page_size = max(1, min(page_size, 200))
    rows = query.order_by(Run.id.desc()).offset((max(page, 1) - 1) * page_size).limit(page_size).all()
    return {"items": [run_summary(r) for r in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    r = db.get(Run, run_id)
    if r is None:
        raise HTTPException(404, "Run not found")
    return run_detail(db, r)


@router.get("/{run_id}/events")
async def run_events(run_id: int):
    return StreamingResponse(stream_run_events(run_id), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


@router.get("/{run_id}/file")
def run_file(run_id: int, db: Session = Depends(get_db)):
    f = db.get(RunFile, run_id)
    r = db.get(Run, run_id)
    if f is None or r is None:
        raise HTTPException(404, "File not found")
    return Response(f.content, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{r.file_name}"'})


@router.post("/{run_id}/actions")
def run_action(run_id: int, req: ActionRequest, db: Session = Depends(get_db)):
    try:
        run = apply_action(db, run_id, req, background=True)
    except ActionError as e:
        raise HTTPException(e.status, str(e))
    return run_detail(db, run)
