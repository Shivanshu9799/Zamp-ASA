"""Google Gemini provider (plain REST via httpx, no extra SDK). Used when LLM_PROVIDER=gemini."""
from __future__ import annotations

import base64
import json
import re
from typing import Optional

import httpx

from . import config

BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _post(payload: dict, timeout: float) -> str:
    r = httpx.post(f"{BASE}/{config.LLM_MODEL}:generateContent", json=payload, timeout=timeout,
                   headers={"x-goog-api-key": config.LLM_API_KEY, "Content-Type": "application/json"})
    if r.status_code != 200:
        raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError):
        raise RuntimeError(f"Gemini returned no content: {json.dumps(data)[:300]}")
    return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()


def extract_json(pdf_bytes: bytes, instruction: str, schema: dict) -> dict:
    """Send the PDF inline and ask for a JSON object that fits `schema`."""
    prompt = (instruction + "\n\nReturn ONLY one JSON object (no markdown) matching this JSON Schema; "
              "use null for anything not printed on the invoice:\n" + json.dumps(schema))
    text = _post({
        "contents": [{"role": "user", "parts": [
            {"inline_data": {"mime_type": "application/pdf", "data": base64.standard_b64encode(pdf_bytes).decode()}},
            {"text": prompt}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }, timeout=120)
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return json.loads(text)


def generate_text(system: str, user: str, max_tokens: int = 400) -> str:
    return _post({
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens},
    }, timeout=60)
