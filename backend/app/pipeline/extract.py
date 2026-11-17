"""Stage 2 – Extract.

The LLM reads the PDF (digital or scanned) into the ExtractedInvoice schema using forced tool-use.
Code then normalises everything (Decimal money, ISO dates, normalised invoice number) and cross-checks the
key fields against the PDF's own text layer when there is one.

LLM_MODE:
  cached – use backend/llm_cache/<sha256>.json when present; call the API only on a cache miss (if a key exists)
  live   – always call the API (and refresh the cache); fall back to the cache only if the API call fails
"""
from __future__ import annotations

import base64
import copy
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .. import config
from ..schemas import (CheckResult, ExtractedInvoice, LineItem, LLMInvoice, TaxLine)
from ..util import (normalise_currency, normalise_invoice_no, parse_amount, parse_date, to_dec)
from .intake import pdf_text

PROMPT = (
    "You are an accounts-payable data-entry assistant. Read the attached vendor invoice (it may be a scan) and "
    "record it with the record_invoice tool. Rules: copy values exactly as printed; do not guess or compute missing "
    "values - use null; keep the invoice number exactly as printed; dates as YYYY-MM-DD; amounts as plain strings "
    "without currency symbols (commas are fine); set po_number only if a PO number is printed, otherwise put any "
    "free-text order reference (e.g. 'your order dated ...') in po_reference_text; give a 0..1 confidence for each "
    "top-level field in field_confidence (lower it for blurry, ambiguous or hand-written values); put anything "
    "unusual (e.g. 'new bank details') in notes."
)


class ExtractionError(Exception):
    pass


# ---------------------------------------------------------------- cache
def cache_path(sha: str) -> Path:
    return config.CACHE_DIR / f"{sha}.json"


def read_cache(sha: str) -> Optional[dict]:
    p = cache_path(sha)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def write_cache(sha: str, extraction: dict, source: str, model: str, filename: str = "") -> None:
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path(sha).write_text(json.dumps({
        "sha256": sha, "source": source, "model": model, "file": filename,
        "created_at": datetime.utcnow().isoformat() + "Z", "extraction": extraction}, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- LLM call
def _inline_refs(schema: dict) -> dict:
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            return {k: walk(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def tool_schema() -> dict:
    return {
        "name": "record_invoice",
        "description": "Record the structured contents of the vendor invoice.",
        "input_schema": _inline_refs(LLMInvoice.model_json_schema()),
    }


def _call_llm_once(pdf_bytes: bytes) -> dict:
    if config.LLM_PROVIDER == "gemini":
        from .. import llm_gemini
        raw = llm_gemini.extract_json(pdf_bytes, PROMPT, tool_schema()["input_schema"])
        return LLMInvoice.model_validate(raw).model_dump()

    import anthropic

    client = anthropic.Anthropic(api_key=config.LLM_API_KEY, timeout=90.0, max_retries=1)
    msg = client.messages.create(
        model=config.LLM_MODEL, max_tokens=4096, temperature=0,
        tools=[tool_schema()], tool_choice={"type": "tool", "name": "record_invoice"},
        messages=[{"role": "user", "content": [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                            "data": base64.standard_b64encode(pdf_bytes).decode()}},
            {"type": "text", "text": PROMPT}]}])
    for block in msg.content:
        if getattr(block, "type", "") == "tool_use":
            return LLMInvoice.model_validate(block.input).model_dump()
    raise ValueError("model returned no tool call")


_TRANSIENT = ("429", "500", "502", "503", "504", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "timed out", "overloaded")


def call_llm(pdf_bytes: bytes, patient: bool = False) -> dict:
    """Retry on API error / invalid JSON. Overload errors (503/429) get exponential back-off:
    3 tries (~6 s) inside a request, 6 tries (~1 min) when `patient` (batch scripts)."""
    attempts = 6 if patient else 3
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return _call_llm_once(pdf_bytes)
        except Exception as e:  # noqa: BLE001
            last = e
            transient = any(t in str(e) for t in _TRANSIENT)
            if not transient and attempt >= 1:
                break  # bad JSON etc.: one retry is enough
            time.sleep(min(2.0 * (2 ** attempt), 30) if transient else 0.8)
    raise ExtractionError(f"LLM extraction failed after {attempt + 1} attempt(s): {type(last).__name__}: {last}")


# ---------------------------------------------------------------- normalisation
def normalise(raw: dict) -> ExtractedInvoice:
    r = LLMInvoice.model_validate(raw)
    unparsed: list[str] = []

    def money(name: str, v: Optional[str]):
        out = parse_amount(v)
        if v not in (None, "") and out is None:
            unparsed.append(name)
        return out

    def dt(name: str, v: Optional[str]):
        out = parse_date(v)
        if v not in (None, "") and out is None:
            unparsed.append(name)
        return out

    lines = [LineItem(description=l.description, sku=l.sku, hsn=l.hsn, quantity=money("quantity", l.quantity),
                      uom=l.uom, unit_price=money("unit_price", l.unit_price), amount=money("line.amount", l.amount),
                      tax_rate=to_dec(re.sub(r"[^\d.]", "", l.tax_rate or "") or None)) for l in r.line_items]
    taxes = [TaxLine(type=t.type, rate=to_dec(re.sub(r"[^\d.]", "", t.rate or "") or None),
                     amount=money("tax.amount", t.amount)) for t in r.tax_lines]
    tax_total = money("tax_total", r.tax_total)
    if tax_total is None and taxes and all(t.amount is not None for t in taxes):
        tax_total = sum((t.amount for t in taxes), start=to_dec(0))
    inv_no = (r.invoice_number or "").strip() or None
    po = (r.po_number or "").strip() or None
    return ExtractedInvoice(
        vendor_name=(r.vendor_name or "").strip() or None, vendor_gstin=(r.vendor_gstin or "").strip().upper() or None,
        vendor_address=r.vendor_address, vendor_bank=r.vendor_bank, bill_to_name=r.bill_to_name,
        invoice_number=inv_no, invoice_number_normalised=normalise_invoice_no(inv_no) or None,
        invoice_date=dt("invoice_date", r.invoice_date), due_date=dt("due_date", r.due_date),
        payment_terms=r.payment_terms, po_number=po, po_reference_text=r.po_reference_text,
        currency=normalise_currency(r.currency), line_items=lines, subtotal=money("subtotal", r.subtotal),
        tax_lines=taxes, tax_total=tax_total, other_charges=money("other_charges", r.other_charges) or to_dec(0),
        total=money("total", r.total), prices_tax_inclusive=r.prices_tax_inclusive,
        field_confidence={k: float(v) for k, v in r.field_confidence.items()}, notes=r.notes, unparsed=unparsed)


# ---------------------------------------------------------------- text-layer cross-check
def crosscheck(pdf_bytes: bytes, ex: ExtractedInvoice, has_text: bool) -> dict:
    """Independent evidence: do the values the model returned literally appear in the PDF's own text?"""
    if not has_text:
        return {"available": False, "agreed": None, "fields": {},
                "note": "Scanned PDF: no text layer to cross-check against."}
    text = pdf_text(pdf_bytes)
    alnum = re.sub(r"[^A-Z0-9]", "", text.upper())
    # every number in the text as a Decimal, so "61,000", "61,000.00" and "Rs. 61,000/-" all equal 61000
    amounts = {a for a in (parse_amount(m) for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text)) if a is not None}
    fields: dict = {}

    def add(name, llm_value, found):
        fields[name] = {"llm": None if llm_value is None else str(llm_value), "found_in_text": bool(found)}

    if ex.invoice_number:
        add("invoice_number", ex.invoice_number, re.sub(r"[^A-Z0-9]", "", ex.invoice_number.upper()) in alnum)
    if ex.total is not None:
        add("total", ex.total, ex.total in amounts)
    if ex.subtotal is not None:
        add("subtotal", ex.subtotal, ex.subtotal in amounts)
    if ex.vendor_gstin:
        add("vendor_gstin", ex.vendor_gstin, ex.vendor_gstin in alnum)
    return {"available": True, "agreed": all(f["found_in_text"] for f in fields.values()) if fields else None,
            "fields": fields, "note": "Compared the model's values with the text embedded in the PDF."}


# ---------------------------------------------------------------- stage entry point
def run_extract(pdf_bytes: bytes, sha: str, has_text: bool, filename: str = "") -> tuple[ExtractedInvoice, dict]:
    t0 = time.time()
    info: dict = {"model": config.LLM_MODEL, "mode": config.LLM_MODE}
    raw: Optional[dict] = None
    cached = read_cache(sha)

    def from_cache(reason: Optional[str] = None):
        nonlocal raw
        raw = cached["extraction"]
        src = cached.get("source", "llm")
        info.update(source="llm_cached" if src == "llm" else "seed_cached", cache_source=src,
                    model=cached.get("model", config.LLM_MODEL))
        if reason:
            info["fallback_reason"] = reason

    if config.LLM_MODE == "cached" and cached:
        from_cache()
    elif config.LLM_API_KEY:
        try:
            raw = call_llm(pdf_bytes)
            write_cache(sha, raw, "llm", config.LLM_MODEL, filename)
            info.update(source="llm_live", cache_source="llm")
        except ExtractionError as e:
            if cached:
                from_cache(reason=str(e))
            else:
                raise
    elif cached:
        from_cache()
    else:
        raise ExtractionError("No cached extraction exists for this file and no LLM API key (ANTHROPIC_API_KEY or GEMINI_API_KEY) is configured.")

    ex = normalise(raw)
    cc = crosscheck(pdf_bytes, ex, has_text)
    info["crosscheck"] = cc
    warnings: list[str] = []
    if cc.get("available"):
        for name, f in cc["fields"].items():
            if not f["found_in_text"]:
                ex.field_confidence[name] = min(ex.field_confidence.get(name, 1.0), 0.5)
                warnings.append(f"{name.replace('_', ' ')} '{f['llm']}' was not found in the PDF text layer")
    for u in ex.unparsed:
        warnings.append(f"Could not parse {u.replace('_', ' ')}")
    info["warnings"] = warnings
    info["elapsed_ms"] = int((time.time() - t0) * 1000)
    return ex, info


# ---------------------------------------------------------------- rule R02
def check_extraction(ex: ExtractedInvoice, info: dict) -> list[CheckResult]:
    # a critical field with NO reported confidence is treated as low (0.5), never as a silent pass
    conf = {f: ex.field_confidence.get(f, 0.5) for f in config.CRITICAL_FIELDS}
    unreported = [f for f in config.CRITICAL_FIELDS if f not in ex.field_confidence]
    low = [f for f, c in conf.items() if c < config.EXTRACTION_MIN_CONFIDENCE]
    cc = info.get("crosscheck", {})
    disagreed = [n for n, f in cc.get("fields", {}).items() if not f["found_in_text"]]
    evidence = {"confidence": conf, "threshold": config.EXTRACTION_MIN_CONFIDENCE, "crosscheck": cc,
                "low_confidence_fields": low, "confidence_not_reported": unreported,
                "cross_check_mismatches": disagreed}
    if low or disagreed:
        bits = []
        if low:
            bits.append("low-confidence reading of " + ", ".join(f.replace("_", " ") for f in low))
        if disagreed:
            bits.append("the PDF's own text disagrees on " + ", ".join(f.replace("_", " ") for f in disagreed))
        return [CheckResult(rule_id="R02", name="Extraction confidence & cross-check", stage="extract", status="fail",
                            severity="pending", evidence=evidence,
                            message="A person should double-check the reading of this invoice: " + "; ".join(bits) + ".")]
    if not cc.get("available"):
        return [CheckResult(rule_id="R02", name="Extraction confidence & cross-check", stage="extract", status="warn",
                            severity="info", evidence=evidence,
                            message="Scanned invoice: all key fields were read with high confidence, but there is no "
                                    "text layer to cross-check against.")]
    return [CheckResult(rule_id="R02", name="Extraction confidence & cross-check", stage="extract", status="pass",
                        severity="pending", evidence=evidence,
                        message="Key fields were read with high confidence and match the PDF's own text.")]
