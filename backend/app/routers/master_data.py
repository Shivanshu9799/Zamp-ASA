from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import GoodsReceipt, POLine, PurchaseOrder, Vendor
from ..pipeline.match import history
from ..util import to_dec

router = APIRouter(prefix="/api/master", tags=["master"])


@router.get("/{kind}")
def master(kind: str, db: Session = Depends(get_db)):
    if kind == "vendors":
        return [{"id": v.id, "name": v.name, "aliases": [a for a in v.aliases.split(";") if a], "gstin": v.gstin,
                 "bank_name": v.bank_name, "account_number": v.account_number, "ifsc": v.ifsc,
                 "state_code": v.state_code, "phone_on_file": v.phone_on_file, "email": v.email}
                for v in db.query(Vendor).order_by(Vendor.id)]
    if kind == "pos":
        out = []
        vendors = {v.id: v.name for v in db.query(Vendor)}
        for po in db.query(PurchaseOrder).order_by(PurchaseOrder.id):
            h = history(db, po.id, 0)
            amt = to_dec(po.amount)
            lines = db.query(POLine).filter_by(po_id=po.id).order_by(POLine.line_no).all()
            recv: dict[int, object] = {}
            for g in db.query(GoodsReceipt).filter_by(po_id=po.id):
                recv[g.line_no] = recv.get(g.line_no, 0) + to_dec(g.qty)
            out.append({
                "id": po.id, "vendor_id": po.vendor_id, "vendor_name": vendors.get(po.vendor_id), "type": po.type,
                "date": po.date, "currency": po.currency, "amount": po.amount, "note": po.note,
                "invoiced_to_date": str(h["invoiced"]), "in_review": str(h["in_review"]),
                "remaining": str(amt - h["invoiced"]), "approved_invoices": h["approved_runs"],
                "lines": [{"line_no": l.line_no, "sku": l.sku, "description": l.description, "qty": l.qty,
                           "uom": l.uom, "unit_price": l.unit_price, "amount": l.amount,
                           "received": str(recv.get(l.line_no, 0)) if po.type == "goods" else None,
                           "invoiced_qty": str(h["qty"].get(l.line_no, 0))} for l in lines]})
        return out
    if kind == "grns":
        return [{"id": g.id, "po_id": g.po_id, "line_no": g.line_no, "qty": g.qty, "date": g.date}
                for g in db.query(GoodsReceipt).order_by(GoodsReceipt.date, GoodsReceipt.id)]
    raise HTTPException(404, "Unknown master data set")
