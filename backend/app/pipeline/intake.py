"""Stage 1 – Intake: fingerprint the file and find out whether it has a text layer."""
from __future__ import annotations

import hashlib
import io

import pdfplumber


class IntakeError(Exception):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pdf_text(data: bytes) -> str:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def run_intake(data: bytes, filename: str) -> dict:
    if not data[:5] == b"%PDF-":
        raise IntakeError("This file is not a PDF. Please upload a PDF invoice.")
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = len(pdf.pages)
            text_chars = sum(len((p.extract_text() or "").strip()) for p in pdf.pages)
    except Exception as e:  # corrupt / encrypted
        raise IntakeError(f"The PDF could not be opened ({type(e).__name__}).") from e
    if pages == 0:
        raise IntakeError("The PDF has no pages.")
    has_text = text_chars >= 40
    return {
        "filename": filename,
        "sha256": sha256(data),
        "size_bytes": len(data),
        "pages": pages,
        "has_text_layer": has_text,
        "text_chars": text_chars,
        "kind": "Digital PDF (text layer)" if has_text else "Scanned / image-only PDF",
    }
