"""Loads the master-data CSVs into the database (idempotent)."""
from __future__ import annotations

import csv

from sqlalchemy.orm import Session

from . import config
from .models import GoodsReceipt, POLine, PurchaseOrder, Vendor


def _rows(name: str):
    with open(config.SEED_DIR / name, newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def load_master_data(db: Session) -> None:
    for t in (GoodsReceipt, POLine, PurchaseOrder, Vendor):
        db.query(t).delete()
    for r in _rows("vendors.csv"):
        db.add(Vendor(**r))
    db.flush()
    for r in _rows("purchase_orders.csv"):
        db.add(PurchaseOrder(id=r["po_id"], vendor_id=r["vendor_id"], type=r["type"], date=r["date"],
                             currency=r["currency"], amount=r["amount"], note=r.get("note", "")))
    db.flush()
    for r in _rows("po_lines.csv"):
        db.add(POLine(po_id=r["po_id"], line_no=int(r["line_no"]), sku=r["sku"], description=r["description"],
                      qty=r["qty"], uom=r["uom"], unit_price=r["unit_price"], amount=r["amount"]))
    for r in _rows("goods_receipts.csv"):
        db.add(GoodsReceipt(id=r["grn_id"], po_id=r["po_id"], line_no=int(r["line_no"]), qty=r["qty"], date=r["date"]))
    db.commit()
