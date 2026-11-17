from __future__ import annotations

import json

from fastapi import APIRouter

from .. import bootstrap, config

router = APIRouter(prefix="/api", tags=["demo"])


@router.get("/samples")
def samples():
    p = config.SAMPLES_DIR / "manifest.json"
    if not p.exists():
        return []
    return sorted(json.loads(p.read_text(encoding="utf-8"))["samples"], key=lambda s: s["order"])


@router.post("/demo/reset")
def reset():
    bootstrap.reset_demo()
    return {"ok": True}


@router.get("/config")
def get_config():
    return {
        "tolerances": config.tolerances(), "rules": config.RULES,
        "stages": [{"key": k, "label": l} for k, l in config.STAGES],
        "buyer": {"name": config.BUYER_NAME, "state_code": config.BUYER_STATE_CODE, "gstin": config.BUYER_GSTIN},
        "llm": {"mode": config.LLM_MODE, "model": config.LLM_MODEL, "api_key_configured": bool(config.LLM_API_KEY), "provider": config.LLM_PROVIDER},
        "po_inference_weights": config.PO_INFERENCE_WEIGHTS,
    }

