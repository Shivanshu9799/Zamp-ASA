"""SQLAlchemy models. Money is always stored as a decimal string, never a float."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.utcnow()


# ---------------- master data ----------------
class Vendor(Base):
    __tablename__ = "vendors"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    aliases: Mapped[str] = mapped_column(String(400), default="")
    gstin: Mapped[str] = mapped_column(String(20))
    bank_name: Mapped[str] = mapped_column(String(100))
    account_number: Mapped[str] = mapped_column(String(40))
    ifsc: Mapped[str] = mapped_column(String(20))
    state_code: Mapped[str] = mapped_column(String(4), default="27")
    phone_on_file: Mapped[str] = mapped_column(String(40), default="")
    email: Mapped[str] = mapped_column(String(120), default="")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String(16), ForeignKey("vendors.id"))
    type: Mapped[str] = mapped_column(String(10))  # goods | service
    date: Mapped[str] = mapped_column(String(10))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    amount: Mapped[str] = mapped_column(String(32))  # pre-tax
    note: Mapped[str] = mapped_column(String(200), default="")


class POLine(Base):
    __tablename__ = "po_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    po_id: Mapped[str] = mapped_column(String(24), ForeignKey("purchase_orders.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    sku: Mapped[str] = mapped_column(String(40), default="")
    description: Mapped[str] = mapped_column(String(200))
    qty: Mapped[str] = mapped_column(String(24))
    uom: Mapped[str] = mapped_column(String(16), default="")
    unit_price: Mapped[str] = mapped_column(String(24))
    amount: Mapped[str] = mapped_column(String(32))


class GoodsReceipt(Base):
    __tablename__ = "goods_receipts"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    po_id: Mapped[str] = mapped_column(String(24), ForeignKey("purchase_orders.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    qty: Mapped[str] = mapped_column(String(24))
    date: Mapped[str] = mapped_column(String(10))


# ---------------- runs ----------------
class Run(Base):
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(12), default="upload")  # upload | sample | seed
    file_name: Mapped[str] = mapped_column(String(200))
    file_sha: Mapped[str] = mapped_column(String(64), index=True, default="")
    file_meta: Mapped[dict] = mapped_column(JSON, default=dict)

    # PROCESSING | APPROVED | PENDING | REJECTED   (current status, can be changed by a human)
    status: Mapped[str] = mapped_column(String(12), default="PROCESSING", index=True)
    # what the system decided before any human action: APPROVE | PENDING | REJECT
    decision: Mapped[str | None] = mapped_column(String(10), nullable=True)
    decision_detail: Mapped[dict] = mapped_column(JSON, default=dict)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    next_action: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    extracted: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    extraction_info: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    vendor_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    vendor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    invoice_number_norm: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    invoice_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    total: Mapped[str | None] = mapped_column(String(32), nullable=True)      # grand total payable
    net_amount: Mapped[str | None] = mapped_column(String(32), nullable=True)  # ex-tax value billed

    po_id: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    po_override: Mapped[str | None] = mapped_column(String(24), nullable=True)
    line_matches: Mapped[list | None] = mapped_column(JSON, nullable=True)
    po_balance: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    po_candidates: Mapped[list | None] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class RunFile(Base):
    __tablename__ = "run_files"
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("runs.id"), primary_key=True)
    content: Mapped[bytes] = mapped_column(LargeBinary)


class RunStage(Base):
    __tablename__ = "run_stages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("runs.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(10), default="pending")  # running|passed|warning|failed
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("runs.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    actor: Mapped[str] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
