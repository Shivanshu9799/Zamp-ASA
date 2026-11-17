"""Stage 8a – Explain. The decision is already made by code; this only *words* it.

Template text is always available. When an API key exists the LLM rewrites it in friendlier prose, but only
from the check results, and its output is rejected (falling back to the template) if it contains any number
that is not present in those results.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Optional

from .. import config
from ..schemas import CheckResult, Decision, ExtractedInvoice
from ..util import fmt_inr, jsonable

OK_PHRASE = {
    "R03": "the arithmetic reconciles", "R04": "GST is structured correctly", "R05": "the vendor is in the vendor master",
    "R06": "the bank details match the vendor master", "R07": "it is not an exact duplicate",
    "R08": "it does not look like a duplicate", "R09": "the PO is valid for this vendor",
    "R11": "unit prices match the PO", "R12": "quantities are covered by goods receipts",
    "R13": "billing stays within the PO value", "R14": "the currency matches the PO",
    "R16": "it is addressed to the right company",
}


def _facts(decision: Decision, checks: list[CheckResult], ex: ExtractedInvoice) -> dict:
    return {
        "decision": decision.decision, "security_hold": decision.security_hold,
        "invoice": {"vendor": ex.vendor_name, "number": ex.invoice_number, "total": fmt_inr(ex.total) if ex.total is not None else None},
        "failed_checks": [{"rule": c.rule_id, "finding": c.message} for c in checks if c.status == "fail"],
        "warnings": [{"rule": c.rule_id, "finding": c.message} for c in checks if c.status == "warn"],
        "passed_checks": [{"rule": c.rule_id, "what": OK_PHRASE[c.rule_id]} for c in checks
                          if c.status == "pass" and c.rule_id in OK_PHRASE],
    }


def template_explanation(decision: Decision, checks: list[CheckResult], ex: ExtractedInvoice) -> str:
    who = f"invoice {ex.invoice_number or '(no number)'} from {ex.vendor_name or 'an unidentified vendor'}"
    amt = f" for {fmt_inr(ex.total)}" if ex.total is not None else ""
    passes = [OK_PHRASE[c.rule_id] for c in checks if c.status == "pass" and c.rule_id in OK_PHRASE]
    fails = [c for c in checks if c.status == "fail"]
    order = {"reject": 0, "security": 1, "pending": 2}
    fails.sort(key=lambda c: order.get(c.severity, 3))
    if decision.decision == "APPROVE":
        n = sum(1 for c in checks if c.status == "pass")
        s = [f"Recommended for payment: {who}{amt} passed all {n} checks."]
        key = [OK_PHRASE[r] for r in ("R05", "R06", "R12", "R11", "R13")
               if any(c.rule_id == r and c.status == "pass" for c in checks)]
        if key:
            s.append("In particular, " + ", ".join(key[:-1]) + (", and " if len(key) > 1 else "") + key[-1] + ".")
        s.append("This is a recommendation to post the invoice for payment, not a payment release.")
        return " ".join(s)
    if decision.decision == "REJECT":
        head = f"Rejected: {who}{amt} should not be paid."
    elif decision.security_hold:
        head = f"Held for security review: {who}{amt} needs verification before any payment."
    else:
        head = f"Held for review: {who}{amt} cannot be approved automatically."
    s = [head] + [f.message if f.message.endswith(".") else f.message + "." for f in fails[:2]]
    if len(fails) > 2:
        s.append(f"{len(fails) - 2} other check(s) also need attention (see the check list).")
    if passes and decision.decision != "REJECT":
        s.append("What did check out: " + ", ".join(passes[:4]) + ".")
    return " ".join(s)


# --------------------------------------------------------------------- LLM wording (guard-railed)
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    return {m.group(0).replace(",", "").rstrip(".") for m in _NUM.finditer(text)}


def numbers_are_grounded(output: str, facts: dict) -> bool:
    allowed = _numbers(json.dumps(facts, ensure_ascii=False)) | {"2", "3", "4"}
    # allow trailing-zero variants: 61000.00 == 61000
    allowed |= {a.split(".")[0] for a in allowed}
    return all((n in allowed or n.split(".")[0] in allowed) for n in _numbers(output))


SYSTEM = ("You explain invoice-processing outcomes to a non-technical finance buyer. The decision has ALREADY "
          "been made by deterministic rules; never change, question or soften it. Write 2-4 plain-English "
          "sentences using ONLY the facts provided. Do not invent or compute any number, name or date; "
          "quote numbers exactly as given. No bullet points, no rule IDs.")


def _llm_text(facts: dict) -> str:
    if config.LLM_PROVIDER == "gemini":
        from .. import llm_gemini
        return llm_gemini.generate_text(SYSTEM, json.dumps(facts, ensure_ascii=False))
    import anthropic
    client = anthropic.Anthropic(api_key=config.LLM_API_KEY, timeout=45.0, max_retries=1)
    msg = client.messages.create(
        model=config.LLM_MODEL, max_tokens=400, temperature=0, system=SYSTEM,
        messages=[{"role": "user", "content": json.dumps(facts, ensure_ascii=False)}])
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()


def explain(decision: Decision, checks: list[CheckResult], ex: ExtractedInvoice) -> tuple[str, str]:
    """Returns (text, source) where source is template | llm_live | llm_cached."""
    template = template_explanation(decision, checks, ex)
    if not config.LLM_API_KEY and config.LLM_MODE != "cached":
        return template, "template"
    facts = jsonable(_facts(decision, checks, ex))
    key = hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()[:24]
    path = config.CACHE_DIR / f"explain_{key}.json"
    if config.LLM_MODE == "cached" and path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))["text"]
            if numbers_are_grounded(cached, facts):
                return cached, "llm_cached"
        except Exception:
            pass
    if not config.LLM_API_KEY:
        return template, "template"
    for _ in range(2):
        try:
            text = _llm_text(facts)
            if text and numbers_are_grounded(text, facts):
                config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"text": text, "facts": facts}), encoding="utf-8")
                return text, "llm_live"
            break  # ungrounded output: do not retry, use the template
        except Exception:
            time.sleep(0.5)
    return template, "template"

