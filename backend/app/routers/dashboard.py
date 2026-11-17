from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AuditLog, Run
from ..pipeline.decide import RULE_LABELS
from ..util import to_dec

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    runs = db.query(Run).all()
    done = [r for r in runs if r.status != "PROCESSING"]
    by_status = Counter(r.status for r in runs)
    value = defaultdict(lambda: Decimal("0"))
    for r in done:
        value[r.status] += to_dec(r.total, Decimal("0"))
    touched = {a.run_id for a in db.query(AuditLog).filter(AuditLog.actor != "system").all()}
    # "auto-approved" = the rules approved it and no human acted on it (no PO confirmation, override or re-run)
    auto = [r for r in done if r.decision == "APPROVE" and r.status == "APPROVED" and r.id not in touched]
    reasons: Counter = Counter()
    for r in done:
        if r.decision and r.decision != "APPROVE":
            for rule in (r.decision_detail or {}).get("fired_rules", []):
                reasons[rule] += 1
    durations = [r.duration_ms for r in done if r.duration_ms]
    return {
        "processed": len(done),
        "by_status": {s: by_status.get(s, 0) for s in ("APPROVED", "PENDING", "REJECTED", "PROCESSING")},
        "value_by_status": {s: str(value.get(s, Decimal("0"))) for s in ("APPROVED", "PENDING", "REJECTED")},
        "auto_approval_rate": round(len(auto) / len(done), 4) if done else 0.0,
        "auto_approved": len(auto),
        "avg_processing_ms": int(sum(durations) / len(durations)) if durations else 0,
        "top_exception_reasons": [{"rule_id": k, "label": RULE_LABELS.get(k, k), "count": v}
                                  for k, v in reasons.most_common(8)],
        "security_holds": sum(1 for r in done if (r.decision_detail or {}).get("security_hold") and r.status == "PENDING"),
    }
