"""Server-Sent Events for a run.

Stage rows are written to the database by the runner as each stage starts and finishes, so the stream simply
replays what exists and then follows changes. That makes it replay-safe (open the page at any time, even after
the run finished) and independent of which worker process is running the pipeline.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Optional

from . import config
from .db import SessionLocal
from .models import Run, RunStage

LABELS = dict(config.STAGES)


def iso(dt) -> Optional[str]:
    return dt.isoformat() + "Z" if dt else None


def stage_event(run_id: int, s: RunStage) -> dict[str, Any]:
    return {"run_id": run_id, "stage": s.stage, "label": LABELS.get(s.stage, s.stage), "seq": s.seq,
            "status": s.status, "started_at": iso(s.started_at), "finished_at": iso(s.finished_at),
            "duration_ms": s.duration_ms, "summary": s.summary, "details": s.details or {}}


def _snapshot(run_id: int):
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        if run is None:
            return None
        stages = db.query(RunStage).filter_by(run_id=run_id).order_by(RunStage.seq).all()
        return run.status, run.decision, [stage_event(run_id, s) for s in stages]


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def stream_run_events(run_id: int) -> AsyncIterator[str]:
    sent: dict[str, tuple] = {}
    yield "retry: 1500\n\n"
    ticks = 0
    while True:
        snap = await asyncio.to_thread(_snapshot, run_id)
        if snap is None:
            yield sse("error", {"message": "run not found"})
            return
        status, decision, stages = snap
        present = {e["stage"] for e in stages}
        for gone in [k for k in sent if k not in present]:
            sent.pop(gone)
        for e in stages:
            key = (e["status"], e["finished_at"])
            if sent.get(e["stage"]) != key:
                sent[e["stage"]] = key
                yield sse("stage", e)
        if status != "PROCESSING" and all(e["status"] != "running" for e in stages):
            yield sse("done", {"run_id": run_id, "status": status, "decision": decision})
            return
        ticks += 1
        if ticks % 150 == 0:
            yield ": keep-alive\n\n"
        await asyncio.sleep(0.1)
