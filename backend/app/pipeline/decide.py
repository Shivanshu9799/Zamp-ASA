"""Stage 7 – Decision: the precedence engine. No LLM, no I/O – just rules over check results.

Precedence:  any REJECT-severity failure  →  REJECT
             else any SECURITY failure    →  PENDING (security hold, never auto-approved)
             else any PENDING failure     →  PENDING
             else                         →  APPROVE
All fired rules are returned, not only the first.
"""
from __future__ import annotations

from ..schemas import CheckResult, Decision

_ORDER = {"reject": 0, "security": 1, "pending": 2}


def decide(checks: list[CheckResult]) -> Decision:
    fails = [c for c in checks if c.status == "fail"]
    warns = [c for c in checks if c.status == "warn"]
    passes = [c for c in checks if c.status == "pass"]
    fails_sorted = sorted(fails, key=lambda c: (_ORDER.get(c.severity, 3)))
    rejects = [c for c in fails if c.severity == "reject"]
    security = [c for c in fails if c.severity == "security"]
    if rejects:
        verdict, security_hold = "REJECT", False
    elif security:
        verdict, security_hold = "PENDING", True
    elif fails:
        verdict, security_hold = "PENDING", False
    else:
        verdict, security_hold = "APPROVE", False
    if fails_sorted:
        primary = fails_sorted[0].message
    else:
        primary = "All checks passed."
    return Decision(decision=verdict, security_hold=security_hold, primary_reason=primary,
                    fired_rules=[c.rule_id for c in fails_sorted],
                    warning_rules=[c.rule_id for c in warns],
                    passed_rules=[c.rule_id for c in passes])


RULE_LABELS = {
    "R01": "Missing fields", "R02": "Low-confidence reading", "R03": "Arithmetic mismatch",
    "R04": "GST structure", "R05": "Unknown/unclear vendor", "R06": "Bank details changed",
    "R07": "Duplicate invoice", "R08": "Probable duplicate", "R09": "PO not found",
    "R10": "No PO – needs confirmation", "R11": "Price mismatch", "R12": "Billed > received",
    "R13": "Exceeds PO value", "R14": "Currency mismatch", "R15": "Non-positive total", "R16": "Addressed to someone else", "SYS": "Processing error",
}


def short_reason(d: Decision, checks: list[CheckResult]) -> str:
    """One-line label for the dashboard's 'main reason' column."""
    if d.decision == "APPROVE":
        return "All checks passed"
    return " + ".join(RULE_LABELS.get(r, r) for r in d.fired_rules[:2]) + ("…" if len(d.fired_rules) > 2 else "")
