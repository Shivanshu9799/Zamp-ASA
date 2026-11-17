"""Human-in-the-loop actions. Every action is written to the audit log with actor, time and reason."""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import config
from .models import AuditLog, PurchaseOrder, Run, RunStage
from .pipeline import runner
from .schemas import ActionRequest


def _clear_stages(db: Session, run_id: int, from_stage: str) -> None:
    """Drop stale stage rows synchronously so a live viewer never flashes the old results."""
    idx = config.STAGE_KEYS.index(from_stage)
    db.query(RunStage).filter(RunStage.run_id == run_id, RunStage.seq >= idx).delete()


class ActionError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def apply_action(db: Session, run_id: int, req: ActionRequest, background: bool = True) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise ActionError("Run not found", 404)
    if run.status == "PROCESSING":
        raise ActionError("This run is still processing. Please wait for it to finish.", 409)
    actor = req.actor or "finance.user"
    reason = (req.reason or "").strip()

    if req.type in ("approve", "reject"):
        if len(reason) < 3:
            raise ActionError("A reason is required for a manual override.")
        before = run.status
        run.status = "APPROVED" if req.type == "approve" else "REJECTED"
        db.add(AuditLog(run_id=run.id, actor=actor, action=f"{req.type}_override", reason=reason,
                        details={"from": before, "to": run.status, "system_decision": run.decision}))
        db.commit()
        return run

    if req.type == "confirm_po":
        po = db.get(PurchaseOrder, req.po_id or "")
        if po is None:
            raise ActionError("Unknown PO")
        if run.vendor_id and po.vendor_id != run.vendor_id:
            raise ActionError(f"{po.id} belongs to a different vendor")
        db.add(AuditLog(run_id=run.id, actor=actor, action="confirm_po", reason=reason or f"Confirmed {po.id}",
                        details={"po_id": po.id}))
        run.status = "PROCESSING"
        _clear_stages(db, run.id, "po_match")
        db.commit()
        if background:
            runner.start_background(run.id, "po_match", po.id)
        else:
            runner.process_run(run.id, "po_match", po.id)
            db.refresh(run)
        return run

    if req.type == "rerun":
        db.add(AuditLog(run_id=run.id, actor=actor, action="rerun", reason=reason or "Re-ran the whole pipeline", details={}))
        run.status = "PROCESSING"
        run.po_override = None
        _clear_stages(db, run.id, "intake")
        db.commit()
        if background:
            runner.start_background(run.id, "intake", None)
        else:
            runner.process_run(run.id, "intake", None)
            db.refresh(run)
        return run
    raise ActionError("Unknown action")
