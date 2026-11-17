"""Generates every sample invoice PDF (5 distinct vendor layouts + one rasterised scan).

Run:  python samples/make_invoices.py
Outputs (next to this script):
  *.pdf                       scenario invoices (see SCENARIOS)
  historical/*.pdf            invoices used to seed the dashboard history
  truth/<file>.json           the ground-truth extraction for each PDF (used to pre-warm the LLM cache)
  manifest.json               labels/expected decisions for the UI sample gallery
"""
from __future__ import annotations

import csv
import io
import json
import random
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

HERE = Path(__file__).resolve().parent
SEED = HERE.parent / "backend" / "seed"
W, H = A4

BUYER = {
    "name": "Meridian Foods Pvt. Ltd.",
    "addr1": "Plot 14, MIDC Andheri East",
    "addr2": "Mumbai - 400093, Maharashtra",
    "gstin": "27AABCM4455R1Z9",
    "state": "Maharashtra (27)",
}

VENDOR_EXTRA = {
    "V001": {"addr": ["Gat No. 212, Bhosari MIDC", "Pune - 411026, Maharashtra"], "pan": "AABCS1234F"},
    "V002": {"addr": ["4th Floor, Prestige Tech Park, ORR", "Bengaluru - 560103, Karnataka"], "pan": "AAKFN5678K"},
    "V003": {"addr": ["Plot 33, Taloja Industrial Area", "Navi Mumbai - 410208, Maharashtra"], "pan": "AAEFK9012M"},
    "V004": {"addr": ["Unit 7, Andheri Industrial Estate", "Veera Desai Road, Mumbai - 400053"], "pan": "AAGCA3456P"},
    "V005": {"addr": ["Godown 5, JNPT Road, Panvel", "Navi Mumbai - 410206, Maharashtra"], "pan": "AAJFO7890Q"},
}


def load_vendors() -> dict:
    out = {}
    with open(SEED / "vendors.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r.update(VENDOR_EXTRA[r["id"]])
            out[r["id"]] = r
    return out


VENDORS = load_vendors()
D = Decimal


def q2(x: Decimal) -> Decimal:
    return x.quantize(D("0.01"), ROUND_HALF_UP)


# ------------------------------------------------------------ formatting helpers
def inr(x: Decimal, indian: bool = True) -> str:
    s = f"{q2(x):.2f}"
    whole, frac = s.split(".")
    neg = whole.startswith("-")
    whole = whole.lstrip("-")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        if indian:
            parts = []
            while len(head) > 2:
                parts.insert(0, head[-2:])
                head = head[:-2]
            if head:
                parts.insert(0, head)
            whole = ",".join(parts) + "," + tail
        else:
            whole = f"{int(head + tail):,}"
    return ("-" if neg else "") + whole + "." + frac


def fmt_qty(q: Decimal) -> str:
    return str(int(q)) if q == q.to_integral() else str(q)


ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
        "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _below_1000(n: int) -> str:
    out = []
    if n >= 100:
        out.append(ONES[n // 100] + " Hundred")
        n %= 100
    if n >= 20:
        out.append(TENS[n // 10] + (("-" + ONES[n % 10]) if n % 10 else ""))
    elif n > 0:
        out.append(ONES[n])
    return " ".join(out)


def amount_in_words(x: Decimal) -> str:
    rupees, paise = int(x), int((x - int(x)) * 100)
    parts = []
    for div, name in ((10_000_000, "Crore"), (100_000, "Lakh"), (1000, "Thousand")):
        if rupees >= div:
            parts.append(_below_1000(rupees // div) + " " + name)
            rupees %= div
    if rupees:
        parts.append(_below_1000(rupees))
    words = "Rupees " + (" ".join(parts) if parts else "Zero")
    if paise:
        words += " and " + _below_1000(paise) + " Paise"
    return words + " Only"


# ------------------------------------------------------------ invoice builder
def build(key, tpl, vendor_id, number, inv_date, due_date, po, po_text, lines, mode="cgst_sgst", rate=D("18"),
          inclusive=False, terms="Net 30 days", notes=None, bank=None, extra=None, name_override=None):
    v = VENDORS[vendor_id]
    L = []
    for desc, sku, hsn, qty, uom, price in lines:
        qty, price = D(str(qty)), D(str(price))
        L.append({"desc": desc, "sku": sku, "hsn": hsn, "qty": qty, "uom": uom, "rate": q2(price),
                  "amount": q2(qty * price)})
    rate = D(str(rate))
    if inclusive:
        total = sum((l["amount"] for l in L), D("0"))
        subtotal = q2(total / (1 + rate / 100))
        tax_total = total - subtotal
        if mode == "igst":
            taxes = [("IGST", rate, tax_total)]
        else:
            taxes = [("CGST", rate / 2, q2(tax_total / 2)), ("SGST", rate / 2, tax_total - q2(tax_total / 2))]
    else:
        subtotal = sum((l["amount"] for l in L), D("0"))
        if mode == "igst":
            taxes = [("IGST", rate, q2(subtotal * rate / 100))]
        else:
            half = q2(subtotal * rate / 200)
            taxes = [("CGST", rate / 2, half), ("SGST", rate / 2, half)]
        tax_total = sum((t[2] for t in taxes), D("0"))
        total = subtotal + tax_total
    return {
        "key": key, "tpl": tpl, "vendor": v, "vendor_name": name_override or v["name"], "number": number,
        "date": inv_date, "due": due_date, "po": po, "po_text": po_text, "lines": L, "mode": mode, "rate": rate,
        "inclusive": inclusive, "terms": terms, "notes": notes, "subtotal": subtotal, "taxes": taxes,
        "tax_total": tax_total, "total": total,
        "bank": bank or {"bank_name": v["bank_name"], "account_number": v["account_number"], "ifsc": v["ifsc"]},
        "extra": extra or {},
    }


def tax_label(t, rate_fmt=True):
    typ, r, _ = t
    return f"{typ} @ {r.normalize():f}%"


# ------------------------------------------------------------ drawing helpers
def cell(c, text, x, y, w, align="left", pad=2 * mm):
    if align == "right":
        c.drawRightString(x + w - pad, y, text)
    elif align == "center":
        c.drawCentredString(x + w / 2, y, text)
    else:
        c.drawString(x + pad, y, text)


def table(c, x, y, widths, header, rows, aligns, *, font="Helvetica", fs=8.5, hfont="Helvetica-Bold", hbg=None,
          hfg=colors.black, grid=False, rh=7.5 * mm, zebra=None, lc=colors.Color(.6, .6, .6), outer=True):
    tw = sum(widths)
    if hbg is not None:
        c.setFillColor(hbg)
        c.rect(x, y - rh, tw, rh, fill=1, stroke=0)
    c.setFillColor(hfg)
    c.setFont(hfont, fs)
    cx = x
    for w, h, a in zip(widths, header, aligns):
        cell(c, h, cx, y - rh + 2.4 * mm, w, a)
        cx += w
    y -= rh
    c.setStrokeColor(lc)
    c.setLineWidth(.6)
    if not grid:
        c.line(x, y, x + tw, y)
    for i, row in enumerate(rows):
        if zebra and i % 2 == 1:
            c.setFillColor(zebra)
            c.rect(x, y - rh, tw, rh, fill=1, stroke=0)
        c.setFillColor(colors.black)
        c.setFont(font, fs)
        cx = x
        for w, t, a in zip(widths, row, aligns):
            cell(c, str(t), cx, y - rh + 2.4 * mm, w, a)
            cx += w
        y -= rh
        if not grid:
            c.setStrokeColor(lc)
            c.line(x, y, x + tw, y)
    if grid:
        top = y + rh * (len(rows) + 1)
        c.setStrokeColor(lc)
        if outer:
            c.rect(x, y, tw, top - y, stroke=1, fill=0)
        cx = x
        for w in widths[:-1]:
            cx += w
            c.line(cx, y, cx, top)
        for i in range(len(rows) + 1):
            c.line(x, top - rh * (i + 1), x + tw, top - rh * (i + 1))
    return y


def kv(c, x, y, pairs, lw, fs=8.5, font="Helvetica", bold="Helvetica-Bold", lh=5 * mm, colon=True):
    for k, val in pairs:
        c.setFont(bold, fs)
        c.drawString(x, y, k + (":" if colon else ""))
        c.setFont(font, fs)
        c.drawString(x + lw, y, val)
        y -= lh
    return y


def fdate(d: date, style: str) -> str:
    return {"A": d.strftime("%d-%b-%Y"), "B": d.strftime("%d %b %Y"), "C": d.strftime("%d/%m/%Y"),
            "D": d.strftime("%d-%m-%Y"), "E": d.strftime("%d-%b-%Y"), "ISO": d.isoformat()}[style]


# ------------------------------------------------------------ template A: classic boxed GST invoice (Shree Ganesh)
def tpl_a(c, inv):
    v, m = inv["vendor"], 12 * mm
    c.setStrokeColor(colors.black)
    c.setLineWidth(1)
    c.rect(m, m, W - 2 * m, H - 2 * m)
    y = H - m - 9 * mm
    c.setFont("Helvetica-Bold", 15)
    c.drawString(m + 5 * mm, y, inv["vendor_name"].upper())
    c.setFont("Helvetica", 8.5)
    for i, ln in enumerate(v["addr"] + [f"GSTIN: {v['gstin']}   PAN: {v['pan']}",
                                        f"Tel: {v['phone_on_file']}   Email: {v['email']}"]):
        c.drawString(m + 5 * mm, y - 5 * mm * (i + 1), ln)
    c.setFont("Helvetica-Bold", 15)
    c.drawRightString(W - m - 5 * mm, y, "TAX INVOICE")
    c.setFont("Helvetica", 7.5)
    c.drawRightString(W - m - 5 * mm, y - 5 * mm, "(Original for Recipient)")
    y -= 30 * mm
    c.line(m, y, W - m, y)
    # meta boxes
    c.line(W / 2, y, W / 2, y - 38 * mm)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(m + 5 * mm, y - 5 * mm, "Bill To:")
    c.setFont("Helvetica", 8.5)
    for i, ln in enumerate([BUYER["name"], BUYER["addr1"], BUYER["addr2"], f"GSTIN: {BUYER['gstin']}",
                            f"State: {BUYER['state']}"]):
        c.drawString(m + 5 * mm, y - 10 * mm - i * 5 * mm, ln)
    pairs = [("Invoice No.", inv["number"]), ("Invoice Date", fdate(inv["date"], "A")),
             ("Due Date", fdate(inv["due"], "A")), ("PO No.", inv["po"] or "-"), ("Payment Terms", inv["terms"]),
             ("Place of Supply", "Maharashtra (27)")]
    kv(c, W / 2 + 4 * mm, y - 5 * mm, pairs, 30 * mm)
    y -= 38 * mm
    c.line(m, y, W - m, y)
    y -= 4 * mm
    widths = [10 * mm, 66 * mm, 18 * mm, 16 * mm, 16 * mm, 25 * mm, 31 * mm]
    rows = [[i + 1, l["desc"], l["hsn"], fmt_qty(l["qty"]), l["uom"], inr(l["rate"]), inr(l["amount"])]
            for i, l in enumerate(inv["lines"])]
    y = table(c, m + 1 * mm, y, widths, ["Sr", "Description of Goods", "HSN", "Qty", "UoM", "Rate (Rs.)",
                                          "Amount (Rs.)"], rows, ["center", "left", "center", "right", "center",
                                                                "right", "right"], grid=True,
              hbg=colors.Color(.9, .9, .9))
    y_tbl = y
    y -= 10 * mm
    tx = W - m - 70 * mm
    rowsT = [("Sub Total", inr(inv["subtotal"]))] + [(tax_label(t), inr(t[2])) for t in inv["taxes"]]
    for k, val in rowsT:
        c.setFont("Helvetica", 9)
        c.drawString(tx, y, k)
        c.drawRightString(W - m - 5 * mm, y, val)
        y -= 5.5 * mm
    y -= 2 * mm
    c.setFont("Helvetica-Bold", 10.5)
    c.rect(tx - 2 * mm, y - 2.5 * mm, 70 * mm, 8 * mm)
    c.drawString(tx, y, "GRAND TOTAL (Rs.)")
    c.drawRightString(W - m - 5 * mm, y, inr(inv["total"]))
    c.setFont("Helvetica-Oblique", 8.5)
    c.drawString(m + 5 * mm, y_tbl - 10 * mm, "Amount in words:")
    c.setFont("Helvetica", 8.5)
    c.drawString(m + 5 * mm, y_tbl - 15 * mm, amount_in_words(inv["total"]))
    y -= 22 * mm
    b = inv["bank"]
    c.setFont("Helvetica-Bold", 9)
    c.drawString(m + 5 * mm, y, "Bank Details")
    kv(c, m + 5 * mm, y - 5 * mm, [("Bank", b["bank_name"]), ("A/c No.", b["account_number"]), ("IFSC", b["ifsc"])],
       22 * mm)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(m + 5 * mm, y - 24 * mm, "Terms & Conditions")
    c.setFont("Helvetica", 7.5)
    for i, t in enumerate(["1. Goods once sold will not be taken back.", "2. Interest @ 18% p.a. on overdue payments.",
                           "3. Subject to Pune jurisdiction only."]):
        c.drawString(m + 5 * mm, y - 29 * mm - i * 4 * mm, t)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawRightString(W - m - 5 * mm, y - 24 * mm, f"For {inv['vendor_name']}")
    c.setFont("Helvetica", 8)
    c.drawRightString(W - m - 5 * mm, y - 40 * mm, "Authorised Signatory")


# ------------------------------------------------------------ template B: modern minimal, services (Nimbus)
def tpl_b(c, inv):
    v, m = inv["vendor"], 18 * mm
    teal = colors.Color(.05, .45, .50)
    c.setFillColor(teal)
    c.rect(0, H - 8 * mm, W, 8 * mm, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 26)
    c.drawString(m, H - 30 * mm, "nimbus")
    c.setFont("Helvetica", 7.5)
    c.setFillColor(colors.grey)
    c.drawString(m, H - 36 * mm, "CLOUD SERVICES LLP")
    c.setFont("Helvetica", 28)
    c.setFillColor(colors.Color(.75, .75, .75))
    c.drawRightString(W - m, H - 30 * mm, "Invoice")
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 8)
    for i, ln in enumerate(v["addr"] + [f"GSTIN {v['gstin']}  |  LLPIN AAK-5678", v["email"]]):
        c.drawString(m, H - 46 * mm - i * 4.2 * mm, ln)
    y = H - 72 * mm
    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(teal)
    c.drawString(m, y, "BILLED TO")
    c.drawString(W / 2 - 5 * mm, y, "INVOICE DETAILS")
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 8.5)
    for i, ln in enumerate([BUYER["name"], BUYER["addr1"], BUYER["addr2"], f"GSTIN {BUYER['gstin']}"]):
        c.drawString(m, y - 6 * mm - i * 4.8 * mm, ln)
    pairs = [("Invoice #", inv["number"]), ("Issued", fdate(inv["date"], "B")), ("Due", fdate(inv["due"], "B")),
             ("Customer PO", inv["po"] or "-"), ("Place of supply", "Maharashtra (27)")]
    for i, (k, val) in enumerate(pairs):
        c.setFillColor(colors.grey)
        c.drawString(W / 2 - 5 * mm, y - 6 * mm - i * 4.8 * mm, k)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(W / 2 + 28 * mm, y - 6 * mm - i * 4.8 * mm, val)
        c.setFont("Helvetica", 8.5)
    y -= 38 * mm
    widths = [88 * mm, 22 * mm, 14 * mm, 28 * mm, 24 * mm]
    rows = [[l["desc"], l["hsn"], fmt_qty(l["qty"]), inr(l["rate"], False), inr(l["amount"], False)]
            for l in inv["lines"]]
    y = table(c, m, y, widths, ["DESCRIPTION", "SAC", "QTY", "UNIT PRICE", "AMOUNT (INR)"], rows,
              ["left", "center", "right", "right", "right"], hfg=teal, fs=9, rh=9 * mm, lc=colors.Color(.85, .85, .85))
    c.setFont("Helvetica-Oblique", 8)
    c.setFillColor(colors.grey)
    if inv["extra"].get("period"):
        c.drawString(m + 2 * mm, y - 6 * mm, "Service period: " + inv["extra"]["period"])
    c.setFillColor(colors.Color(.95, .98, .98))
    bx, by, bw = W - m - 72 * mm, y - 12 * mm, 72 * mm
    c.rect(bx, by - 34 * mm, bw, 34 * mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    yy = by - 7 * mm
    c.setFont("Helvetica", 9)
    for k, val in [("Subtotal", inr(inv["subtotal"], False))] + [(tax_label(t), inr(t[2], False)) for t in inv["taxes"]]:
        c.drawString(bx + 4 * mm, yy, k)
        c.drawRightString(bx + bw - 4 * mm, yy, val)
        yy -= 5.5 * mm
    c.setFillColor(teal)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(bx + 4 * mm, yy - 3 * mm, "Total due")
    c.drawRightString(bx + bw - 4 * mm, yy - 3 * mm, "INR " + inr(inv["total"], False))
    b = inv["bank"]
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(m, by - 6 * mm, "Pay by NEFT / RTGS")
    c.setFont("Helvetica", 8.5)
    for i, ln in enumerate([f"Account name: {inv['vendor_name']}", f"Bank: {b['bank_name']}",
                            f"Account no: {b['account_number']}", f"IFSC: {b['ifsc']}"]):
        c.drawString(m, by - 12 * mm - i * 4.6 * mm, ln)
    c.setFont("Helvetica", 7.5)
    c.setFillColor(colors.grey)
    c.drawString(m, 18 * mm, "This is a computer-generated invoice and does not require a signature. Payment terms: "
                 + inv["terms"] + ".")


# ------------------------------------------------------------ template C: sidebar + dark table (Apex)
def tpl_c(c, inv):
    v = inv["vendor"]
    navy = colors.Color(.10, .18, .36)
    sw = 56 * mm
    c.setFillColor(navy)
    c.rect(0, 0, sw, H, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Times-Bold", 14)
    c.drawString(7 * mm, H - 22 * mm, "APEX")
    c.setFont("Times-Roman", 9)
    c.drawString(7 * mm, H - 28 * mm, "Electricals & Controls")
    c.drawString(7 * mm, H - 33 * mm, "Pvt. Ltd.")
    c.setFont("Helvetica", 7.5)
    y = H - 50 * mm
    side = ["REGISTERED OFFICE"] + v["addr"] + ["", f"GSTIN", v["gstin"], f"PAN {v['pan']}", "", "Phone", v["phone_on_file"],
                                                   "Email", v["email"], "", "BANK DETAILS", inv["bank"]["bank_name"],
                                                   "A/c " + inv["bank"]["account_number"], "IFSC " + inv["bank"]["ifsc"]]
    for ln in side:
        c.setFont("Helvetica-Bold" if ln.isupper() and ln else "Helvetica", 7.2)
        c.drawString(7 * mm, y, ln[:34])
        y -= 4.4 * mm
    x0 = sw + 10 * mm
    c.setFillColor(navy)
    c.setFont("Times-Bold", 26)
    c.drawString(x0, H - 24 * mm, "BILL")
    c.setFont("Times-Roman", 9)
    c.setFillColor(colors.black)
    c.drawString(x0, H - 30 * mm, "Tax Invoice cum Delivery Challan")
    pairs = [("Bill No.", inv["number"]), ("Bill Date", fdate(inv["date"], "C")), ("Your PO", inv["po"] or "-"),
             ("Terms", inv["terms"])]
    kv(c, x0, H - 44 * mm, pairs, 22 * mm, font="Times-Roman", bold="Times-Bold", fs=9.5, lh=5.5 * mm)
    c.setFont("Times-Bold", 9.5)
    c.drawString(x0 + 80 * mm, H - 44 * mm, "Billed to:")
    c.setFont("Times-Roman", 9.5)
    for i, ln in enumerate([BUYER["name"], BUYER["addr1"], BUYER["addr2"], "GSTIN: " + BUYER["gstin"]]):
        c.drawString(x0 + 80 * mm, H - 49.5 * mm - i * 5 * mm, ln)
    y = H - 82 * mm
    avail = W - x0 - 10 * mm
    rate_h = "Rate (incl. GST)" if inv["inclusive"] else "Rate"
    widths = [9 * mm, avail - 9 * mm - 16 * mm - 13 * mm - 13 * mm - 26 * mm - 28 * mm, 16 * mm, 13 * mm, 13 * mm,
              26 * mm, 28 * mm]
    rows = [[i + 1, l["desc"], l["hsn"], fmt_qty(l["qty"]), l["uom"], inr(l["rate"]), inr(l["amount"])]
            for i, l in enumerate(inv["lines"])]
    y = table(c, x0, y, widths, ["#", "Item Description", "HSN", "Qty", "Unit", rate_h, "Amount"], rows,
              ["center", "left", "center", "right", "center", "right", "right"], font="Times-Roman",
              hfont="Times-Bold", fs=9, hbg=navy, hfg=colors.white, zebra=colors.Color(.94, .95, .98), rh=8 * mm,
              lc=colors.Color(.8, .8, .85))
    y -= 8 * mm
    label_sub = "Taxable value" if inv["inclusive"] else "Sub total"
    rowsT = [(label_sub, inr(inv["subtotal"]))] + [(tax_label(t), inr(t[2])) for t in inv["taxes"]]
    tx = W - 10 * mm - 70 * mm
    for k, val in rowsT:
        c.setFont("Times-Roman", 10)
        c.drawString(tx, y, k)
        c.drawRightString(W - 12 * mm, y, val)
        y -= 5.8 * mm
    y -= 3 * mm
    c.setFillColor(navy)
    c.rect(tx - 2 * mm, y - 3.5 * mm, 72 * mm, 9 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Times-Bold", 11)
    c.drawString(tx, y - 0.5 * mm, "Total (incl. GST)" if inv["inclusive"] else "Total payable")
    c.drawRightString(W - 12 * mm, y - 0.5 * mm, "Rs. " + inr(inv["total"]))
    c.setFillColor(colors.black)
    c.setFont("Times-Italic", 8.5)
    if inv["inclusive"]:
        c.drawString(x0, y + 22 * mm, f"Note: Rates shown are inclusive of GST @ {inv['rate'].normalize():f}%.")
    c.drawString(x0, 30 * mm, "E. & O.E.  |  Goods supplied as per Challan. Warranty as per manufacturer's terms.")
    c.setFont("Times-Bold", 9)
    c.drawRightString(W - 12 * mm, 22 * mm, "For Apex Electricals & Controls Pvt. Ltd.")


# ------------------------------------------------------------ template D: centred serif, amount in words (Kaveri)
def tpl_d(c, inv):
    v, m = inv["vendor"], 14 * mm
    c.setFont("Times-Bold", 11)
    c.drawCentredString(W / 2, H - 16 * mm, "TAX INVOICE")
    c.setFont("Times-Bold", 20)
    c.drawCentredString(W / 2, H - 26 * mm, inv["vendor_name"])
    c.setFont("Times-Roman", 9.5)
    c.drawCentredString(W / 2, H - 32 * mm, ", ".join(v["addr"]))
    c.drawCentredString(W / 2, H - 37 * mm, f"GSTIN: {v['gstin']}   |   Ph: {v['phone_on_file']}   |   {v['email']}")
    c.setLineWidth(1.2)
    c.line(m, H - 41 * mm, W - m, H - 41 * mm)
    c.setLineWidth(.4)
    c.line(m, H - 42.5 * mm, W - m, H - 42.5 * mm)
    y = H - 52 * mm
    kv(c, m, y, [("Tax Invoice #", inv["number"]), ("Dated", fdate(inv["date"], "D")),
                 ("Mode of Despatch", "Road - Tempo"), ("Vehicle No.", "MH-46-AB-7712")], 32 * mm, font="Times-Roman",
       bold="Times-Bold", fs=9.5, lh=5.5 * mm)
    c.setFont("Times-Bold", 9.5)
    c.drawString(W / 2 + 5 * mm, y, "Buyer (Bill to / Ship to)")
    c.setFont("Times-Roman", 9.5)
    for i, ln in enumerate([BUYER["name"], BUYER["addr1"], BUYER["addr2"], "GSTIN: " + BUYER["gstin"]]):
        c.drawString(W / 2 + 5 * mm, y - 5.5 * mm * (i + 1), ln)
    y -= 34 * mm
    c.setFont("Times-Bold", 9.5)
    c.drawString(m, y, "Remarks:")
    c.setFont("Times-Italic", 9.5)
    c.drawString(m + 18 * mm, y, inv["extra"].get("remarks", ""))
    y -= 7 * mm
    widths = [10 * mm, 72 * mm, 20 * mm, 22 * mm, 14 * mm, 22 * mm, 22 * mm]
    rows = [[i + 1, l["desc"], l["hsn"], f"{fmt_qty(l['qty'])} {l['uom']}", "", inr(l["rate"]), inr(l["amount"])]
            for i, l in enumerate(inv["lines"])]
    y = table(c, m, y, widths, ["S.No", "Particulars", "HSN/SAC", "Quantity", "", "Rate", "Amount"], rows,
              ["center", "left", "center", "right", "center", "right", "right"], font="Times-Roman",
              hfont="Times-Bold", fs=9.5, grid=True, rh=8 * mm, hbg=colors.Color(.93, .93, .88))
    y -= 8 * mm
    tx = W - m - 74 * mm
    for k, val in [("Total (Taxable)", inr(inv["subtotal"]))] + [(tax_label(t), inr(t[2])) for t in inv["taxes"]]:
        c.setFont("Times-Roman", 10)
        c.drawString(tx, y, k)
        c.drawRightString(W - m - 2 * mm, y, val)
        y -= 5.6 * mm
    c.setLineWidth(.8)
    c.line(tx, y + 3.5 * mm, W - m, y + 3.5 * mm)
    c.setFont("Times-Bold", 11.5)
    c.drawString(tx, y - 1 * mm, "TOTAL")
    c.drawRightString(W - m - 2 * mm, y - 1 * mm, "Rs. " + inr(inv["total"]))
    y -= 12 * mm
    c.setFont("Times-Bold", 9.5)
    c.drawString(m, y, "Amount Chargeable (in words):")
    c.setFont("Times-Italic", 10)
    c.drawString(m, y - 5.5 * mm, amount_in_words(inv["total"]))
    y -= 18 * mm
    b = inv["bank"]
    c.setFont("Times-Bold", 9.5)
    c.drawString(m, y, "Our Bank Details")
    kv(c, m, y - 5.5 * mm, [("Bank", b["bank_name"]), ("Account No.", b["account_number"]), ("IFSC", b["ifsc"])],
       26 * mm, font="Times-Roman", bold="Times-Roman", fs=9.5)
    c.setFont("Times-Roman", 9)
    c.drawRightString(W - m, y - 4 * mm, "for " + inv["vendor_name"])
    c.drawRightString(W - m, y - 22 * mm, "Authorised Signatory")
    c.setFont("Times-Italic", 8)
    c.drawCentredString(W / 2, 14 * mm, "Declaration: We declare that this invoice shows the actual price of the goods described.")


# ------------------------------------------------------------ template E: freight invoice (Orbit)
def tpl_e(c, inv):
    v, m = inv["vendor"], 14 * mm
    slate = colors.Color(.17, .22, .28)
    orange = colors.Color(.93, .45, .10)
    c.setFillColor(slate)
    c.rect(0, H - 34 * mm, W, 34 * mm, fill=1, stroke=0)
    c.setFillColor(orange)
    c.rect(0, H - 36 * mm, W, 2 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(m, H - 17 * mm, "ORBIT LOGISTICS")
    c.setFont("Helvetica", 8)
    c.drawString(m, H - 24 * mm, " | ".join(v["addr"]))
    c.drawString(m, H - 29 * mm, f"GSTIN {v['gstin']}  |  {v['phone_on_file']}  |  {v['email']}")
    c.setFont("Helvetica-Oblique", 17)
    c.drawRightString(W - m, H - 17 * mm, "Freight Invoice")
    c.setFillColor(colors.black)
    y = H - 48 * mm
    kv(c, m, y, [("Inv Ref.", inv["number"]), ("Inv Date", fdate(inv["date"], "E")), ("Order Ref", inv["po"] or "-"),
                 ("Credit", inv["terms"])], 22 * mm, fs=9)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(W / 2, y, "Consignor / Bill To")
    c.setFont("Helvetica", 9)
    for i, ln in enumerate([BUYER["name"], BUYER["addr1"], BUYER["addr2"], "GSTIN " + BUYER["gstin"]]):
        c.drawString(W / 2, y - 5 * mm * (i + 1), ln)
    y -= 30 * mm
    c.setStrokeColor(slate)
    c.setLineWidth(.8)
    c.rect(m, y - 22 * mm, W - 2 * m, 22 * mm)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(m + 3 * mm, y - 5 * mm, "CONSIGNMENT DETAILS")
    c.setFont("Helvetica", 8.5)
    ex = inv["extra"]
    c.drawString(m + 3 * mm, y - 11 * mm, f"LR No: {ex.get('lr', '-')}      Vehicle: {ex.get('vehicle', '-')}      Type: {ex.get('vtype', '-')}")
    c.drawString(m + 3 * mm, y - 16.5 * mm, f"Route: {ex.get('route', '-')}      Date of movement: {ex.get('move', '-')}")
    y -= 30 * mm
    widths = [88 * mm, 22 * mm, 14 * mm, 28 * mm, 30 * mm]
    rows = [[l["desc"], l["hsn"], fmt_qty(l["qty"]), inr(l["rate"]), inr(l["amount"])] for l in inv["lines"]]
    y = table(c, m, y, widths, ["Particulars", "SAC", "Qty", "Rate (Rs.)", "Amount (Rs.)"], rows,
              ["left", "center", "right", "right", "right"], hbg=slate, hfg=colors.white, rh=9 * mm, fs=9, grid=True)
    y -= 8 * mm
    tx = W - m - 74 * mm
    for k, val in [("Freight charges", inr(inv["subtotal"]))] + [(tax_label(t), inr(t[2])) for t in inv["taxes"]]:
        c.setFont("Helvetica", 9.5)
        c.drawString(tx, y, k)
        c.drawRightString(W - m - 2 * mm, y, val)
        y -= 5.6 * mm
    y -= 3 * mm
    c.setFillColor(orange)
    c.rect(tx - 2 * mm, y - 3 * mm, 76 * mm, 9 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(tx, y, "NET PAYABLE")
    c.drawRightString(W - m - 2 * mm, y, "Rs. " + inr(inv["total"]))
    c.setFillColor(colors.black)
    y -= 20 * mm
    b = inv["bank"]
    changed = bool(inv["notes"])
    c.setStrokeColor(colors.Color(.8, .1, .1) if changed else slate)
    c.setLineWidth(1.4 if changed else .6)
    c.rect(m, y - 28 * mm, 100 * mm, 32 * mm)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(m + 3 * mm, y - 2 * mm, "Remit payment to")
    if changed:
        c.setFillColor(colors.Color(.8, .1, .1))
        c.drawString(m + 3 * mm, y - 7 * mm, inv["notes"])
        c.setFillColor(colors.black)
    kv(c, m + 3 * mm, y - 13 * mm, [("Bank", b["bank_name"]), ("A/c No.", b["account_number"]), ("IFSC", b["ifsc"])],
       20 * mm, fs=9)
    c.setFont("Helvetica", 8)
    c.drawString(m, 20 * mm, "Detention / demurrage, if any, to be billed separately.  Subject to Mumbai jurisdiction.")


TEMPLATES = {"A": tpl_a, "B": tpl_b, "C": tpl_c, "D": tpl_d, "E": tpl_e}


def render_pdf(inv, path_or_buf):
    c = canvas.Canvas(path_or_buf if isinstance(path_or_buf, str) else path_or_buf, pagesize=A4)
    c.setTitle(f"Invoice {inv['number']}")
    c.setAuthor(inv["vendor_name"])
    TEMPLATES[inv["tpl"]](c, inv)
    c.showPage()
    c.save()


# ------------------------------------------------------------ scan simulation (image-only PDF)
def render_scan(inv, out_path: Path, seed=7):
    import numpy as np
    import pypdfium2 as pdfium
    from PIL import Image, ImageFilter

    buf = io.BytesIO()
    render_pdf(inv, buf)
    buf.seek(0)
    page = pdfium.PdfDocument(buf)[0]
    img = page.render(scale=150 / 72).to_pil().convert("L")
    img = img.point(lambda p: int(p * 0.86 + 18))            # washed-out toner
    bg = 205
    rotated = img.rotate(1.5, expand=True, fillcolor=bg, resample=Image.BICUBIC)
    # scanner bed margin
    canvas_img = Image.new("L", (rotated.width + 40, rotated.height + 40), 188)
    canvas_img.paste(rotated, (20, 20))
    rng = np.random.default_rng(seed)
    arr = np.asarray(canvas_img, dtype=np.float32)
    arr += rng.normal(0, 9, arr.shape)                         # sensor noise
    yy = np.linspace(0, 1, arr.shape[0])[:, None]
    arr -= 14 * yy                                             # lighting gradient
    specks = rng.random(arr.shape) > 0.9993
    arr[specks] -= 70
    out = Image.fromarray(np.clip(arr, 0, 255).astype("uint8")).filter(ImageFilter.GaussianBlur(0.8))
    out.convert("RGB").save(out_path, "PDF", resolution=150, quality=62)


# ------------------------------------------------------------ truth (what a perfect extractor returns)
def truth_of(inv, scan=False):
    def conf(hi=0.98):
        return hi
    c = {k: (0.93 if scan else 0.99) for k in
         ["vendor_name", "vendor_gstin", "invoice_number", "invoice_date", "due_date", "po_number", "subtotal",
          "tax_total", "total", "line_items", "vendor_bank"]}
    if scan:
        c.update({"invoice_number": 0.88, "invoice_date": 0.91, "total": 0.95, "vendor_bank": 0.9, "line_items": 0.9})
    b = inv["bank"]
    return {
        "vendor_name": inv["vendor_name"],
        "vendor_gstin": inv["vendor"]["gstin"],
        "vendor_address": ", ".join(inv["vendor"]["addr"]),
        "vendor_bank": b,
        "bill_to_name": BUYER["name"],
        "invoice_number": inv["number"],
        "invoice_date": inv["date"].isoformat(),
        "due_date": inv["due"].isoformat(),
        "payment_terms": inv["terms"],
        "po_number": inv["po"],
        "po_reference_text": inv["po_text"],
        "currency": "INR",
        "line_items": [{"description": l["desc"], "sku": None, "hsn": l["hsn"], "quantity": fmt_qty(l["qty"]),
                        "uom": l["uom"], "unit_price": str(l["rate"]), "amount": str(l["amount"]),
                        "tax_rate": str(inv["rate"].normalize())} for l in inv["lines"]],
        "subtotal": str(inv["subtotal"]),
        "tax_lines": [{"type": t[0], "rate": str(t[1].normalize()), "amount": str(t[2])} for t in inv["taxes"]],
        "tax_total": str(inv["tax_total"]),
        "other_charges": "0.00",
        "total": str(inv["total"]),
        "prices_tax_inclusive": inv["inclusive"],
        "field_confidence": c,
        "notes": inv["notes"],
    }


# ------------------------------------------------------------ the scenarios
BEARING = ("Ball bearing 6205-2RS", None, "8482", 100, "NOS", 450)
BELT = ("V-belt B-52", None, "4010", 50, "NOS", 320)


def d(y, m, dd):
    return date(y, m, dd)


def scenarios():
    S = []
    inv01 = build("01", "A", "V001", "INV-SGI-0418", d(2026, 10, 14), d(2026, 11, 13), "PO-2026-1001", None,
                  [BEARING, BELT])
    S.append(dict(file="01_happy_sgi_0418.pdf", inv=inv01, label="Happy path", group="Core",
                  title="Goods invoice, 3-way match", expected="APPROVE", order=1,
                  blurb="Goods invoice that matches the PO, the goods receipt and the vendor master."))
    inv02 = build("02", "B", "V002", "NCS/26-27/0091", d(2026, 10, 31), d(2026, 11, 30), "PO-2026-1004", None,
                  [("Managed cloud hosting - Nov 2026", None, "998315", 1, "MONTH", 85000)], mode="igst",
                  extra={"period": "01-Nov-2026 to 30-Nov-2026"}, terms="Net 30")
    S.append(dict(file="02_happy_nimbus_0091.pdf", inv=inv02, label="Happy path (service)", group="Core",
                  title="Service invoice, inter-state IGST", expected="APPROVE", order=2,
                  blurb="Different layout, services (2-way match), inter-state so IGST only."))
    fl = lambda q: ("LED floodlight 200W", None, "9405", q, "NOS", 500)
    S.append(dict(file="03a_split_apex_1101.pdf", label="Split PO 1/3", group="Edge 1", title="One PO, three invoices",
                  expected="APPROVE", order=3, blurb="First of three invoices against PO-2026-1002 (48 of 120 units).",
                  inv=build("03a", "C", "V004", "APX-1101", d(2026, 10, 16), d(2026, 11, 15), "PO-2026-1002", None,
                            [fl(48)])))
    S.append(dict(file="03b_split_apex_1102.pdf", label="Split PO 2/3", group="Edge 1", title="One PO, three invoices",
                  expected="APPROVE", order=4, blurb="Second invoice (42 more units).",
                  inv=build("03b", "C", "V004", "APX-1102", d(2026, 10, 24), d(2026, 11, 23), "PO-2026-1002", None,
                            [fl(42)])))
    S.append(dict(file="03c_split_apex_1103.pdf", label="Split PO 3/3", group="Edge 1", title="Over-billed by 3 units",
                  expected="PENDING", order=5,
                  blurb="Third invoice bills 33 units but only 30 remain → over by 3 units / Rs 1,500.",
                  inv=build("03c", "C", "V004", "APX-1103", d(2026, 11, 2), d(2026, 12, 2), "PO-2026-1002", None,
                            [fl(33)])))
    inv04 = build("04", "D", "V003", "KPS-2231", d(2026, 10, 10), d(2026, 11, 9), None,
                  "Supplied against your order dated 02-Oct-2026",
                  [("5-Ply Corrugated Box 18x12x12 in", None, "4819", 2000, "NOS", 18)],
                  extra={"remarks": "Supplied against your order dated 02-Oct-2026"})
    S.append(dict(file="04_implied_po_kaveri_2231.pdf", inv=inv04, label="No PO number", group="Edge 2",
                  title="PO only implied in free text", expected="PENDING", order=6,
                  blurb="No PO field. The agent infers PO-2026-1003 and asks a human to confirm."))
    inv05 = build("05", "A", "V001", "INVSGI418", d(2026, 10, 16), d(2026, 11, 15), "PO-2026-1001", None,
                  [BEARING, BELT], name_override="Shree Ganesh Industrial Supplies Pvt. Ltd.")
    S.append(dict(file="05_dup_sgi_0418_scan.pdf", inv=inv05, scan=True, label="Scanned duplicate", group="Edge 3",
                  title="Same invoice, re-sent as a scan", expected="REJECT", order=7,
                  blurb="Image-only scan of invoice 01 with a re-typed number and a later date."))
    inv06 = build("06", "E", "V005", "ORB-7782", d(2026, 11, 5), d(2026, 11, 20), "PO-2026-1005", None,
                  [("FTL freight Mumbai to Pune (32 ft)", None, "996511", 1, "TRIP", 28000)], rate=5,
                  bank={"bank_name": "Kotak Mahindra Bank", "account_number": "7712009910", "ifsc": "KKBK0000555"},
                  notes="Please note our new bank details", terms="15 days",
                  extra={"lr": "ORB/MUM/5518", "vehicle": "MH-43-BX-2210", "vtype": "32 ft FTL",
                         "route": "Mumbai to Pune", "move": "03-Nov-2026"})
    S.append(dict(file="06_bankchange_orbit_7782.pdf", inv=inv06, label="Bank change", group="Edge 4",
                  title="Bank details changed", expected="PENDING", order=8,
                  blurb="Everything matches except the bank account: security hold."))
    return S


def historical():
    H_ = []
    H_.append(dict(file="h1_sgi_0392.pdf", inv=build(
        "h1", "A", "V001", "INV-SGI-0392", d(2026, 9, 15), d(2026, 10, 15), "PO-2026-0905", None,
        [("Hex bolt M12x60 zinc plated", None, "7318", 500, "NOS", 24)]), days_ago=6))
    H_.append(dict(file="h2_nimbus_0063.pdf", inv=build(
        "h2", "B", "V002", "NCS/26-27/0063", d(2026, 9, 30), d(2026, 10, 30), "PO-2026-0911", None,
        [("Managed cloud hosting - Sep 2026", None, "998315", 1, "MONTH", 78500)], mode="igst",
        extra={"period": "01-Sep-2026 to 30-Sep-2026"}, terms="Net 30"), days_ago=4))
    H_.append(dict(file="h3_apex_1088.pdf", inv=build(
        "h3", "C", "V004", "APX-1088", d(2026, 9, 27), d(2026, 10, 27), "PO-2026-0918", None,
        [("Contactor 3-pole 40A", None, "8536", 30, "NOS", 1357)], inclusive=True), days_ago=2))
    return H_


def main():
    (HERE / "historical").mkdir(exist_ok=True)
    (HERE / "truth").mkdir(exist_ok=True)
    manifest = []
    for s in scenarios():
        path = HERE / s["file"]
        if s.get("scan"):
            render_scan(s["inv"], path)
        else:
            render_pdf(s["inv"], str(path))
        (HERE / "truth" / (s["file"] + ".json")).write_text(
            json.dumps(truth_of(s["inv"], bool(s.get("scan"))), indent=2), encoding="utf-8")
        manifest.append({k: s[k] for k in ("file", "label", "group", "title", "expected", "order", "blurb")} |
                        {"scanned": bool(s.get("scan")), "total": str(s["inv"]["total"]),
                         "vendor": s["inv"]["vendor_name"], "invoice_number": s["inv"]["number"]})
        print("wrote", s["file"], inr(s["inv"]["total"]))
    hist = []
    for s in historical():
        path = HERE / "historical" / s["file"]
        render_pdf(s["inv"], str(path))
        (HERE / "truth" / (s["file"] + ".json")).write_text(json.dumps(truth_of(s["inv"]), indent=2), encoding="utf-8")
        hist.append({"file": "historical/" + s["file"], "days_ago": s["days_ago"]})
        print("wrote historical", s["file"], inr(s["inv"]["total"]))
    (HERE / "manifest.json").write_text(json.dumps({"samples": manifest, "historical": hist}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
