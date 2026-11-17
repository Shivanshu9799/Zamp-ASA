"""Small pure helpers: money, dates, invoice-number normalisation, JSON-safe conversion."""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Optional

from pydantic import BaseModel

CENT = Decimal("0.01")


def q2(x: Decimal) -> Decimal:
    return x.quantize(CENT, ROUND_HALF_UP)


def to_dec(x: Any, default: Optional[Decimal] = None) -> Optional[Decimal]:
    if x is None or x == "":
        return default
    try:
        return Decimal(str(x))
    except InvalidOperation:
        return default


def parse_amount(s: Any) -> Optional[Decimal]:
    """'Rs. 1,00,300.00' -> Decimal('100300.00'). Returns None when unparseable. Never uses float."""
    if s is None:
        return None
    if isinstance(s, Decimal):
        return s
    if isinstance(s, (int,)):
        return Decimal(s)
    txt = str(s).strip()
    if not txt:
        return None
    neg = txt.startswith("(") and txt.endswith(")") or txt.startswith("-")
    txt = re.sub(r"(?i)(inr|rs\.?|₹|/-)", "", txt)
    txt = re.sub(r"[^\d.]", "", txt)
    if txt.count(".") > 1:
        head, _, tail = txt.rpartition(".")
        txt = head.replace(".", "") + "." + tail
    if not txt or txt == ".":
        return None
    try:
        v = Decimal(txt)
    except InvalidOperation:
        return None
    return -v if neg else v


_DATE_FORMATS = ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d-%b-%Y", "%d %b %Y", "%d %B %Y", "%d-%B-%Y",
                 "%d-%b-%y", "%b %d, %Y", "%B %d, %Y", "%d/%m/%y", "%Y/%m/%d"]


def parse_date(s: Any) -> Optional[date]:
    if s is None:
        return None
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s
    txt = str(s).strip()
    for f in _DATE_FORMATS:
        try:
            return datetime.strptime(txt, f).date()
        except ValueError:
            continue
    return None


def find_dates_in_text(text: str) -> list[date]:
    """Pull any recognisable dates out of free text such as 'your order dated 02-Oct-2026'."""
    if not text:
        return []
    out: list[date] = []
    patterns = [r"\d{4}-\d{2}-\d{2}", r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}", r"\d{1,2}[- ][A-Za-z]{3,9}[- ,]*\d{2,4}",
                r"[A-Za-z]{3,9} \d{1,2}, \d{4}"]
    for p in patterns:
        for m in re.finditer(p, text):
            d = parse_date(m.group(0).replace(",", ", ").replace(",  ", ", ").strip())
            if d and d not in out:
                out.append(d)
    return out


def normalise_invoice_no(s: Optional[str]) -> str:
    """Uppercase, strip leading zeros inside numeric runs, drop everything non-alphanumeric.
    'INV-SGI-0418' and 'INVSGI418' both become 'INVSGI418'."""
    if not s:
        return ""
    t = str(s).upper()
    t = re.sub(r"(?<![0-9])0+(?=[0-9])", "", t)
    return re.sub(r"[^A-Z0-9]", "", t)


def normalise_po(s: Optional[str]) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def normalise_currency(s: Optional[str]) -> str:
    if not s:
        return "INR"
    t = s.strip().upper().replace(".", "")
    if t in ("RS", "₹", "INR", "RUPEES", "RUPEE", "INR ₹"):
        return "INR"
    return t[:3]


def fmt_inr(x: Any, symbol: bool = True) -> str:
    """Indian digit grouping: 100300 -> ₹1,00,300.00"""
    d = to_dec(x)
    if d is None:
        return "—"
    s = f"{q2(d):.2f}"
    whole, frac = s.split(".")
    neg = whole.startswith("-")
    whole = whole.lstrip("-")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts) + "," + tail
    return ("-" if neg else "") + ("₹" if symbol else "") + whole + "." + frac


def fmt_qty(x: Any) -> str:
    d = to_dec(x)
    if d is None:
        return "—"
    return str(int(d)) if d == d.to_integral() else str(d.normalize())


def jsonable(obj: Any) -> Any:
    """Recursively convert Decimals/dates/pydantic models into JSON-safe values (Decimal -> string)."""
    if isinstance(obj, BaseModel):
        return jsonable(obj.model_dump())
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [jsonable(v) for v in obj]
    return obj
