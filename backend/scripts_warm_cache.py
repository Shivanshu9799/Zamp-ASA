"""Warm / refresh the extraction cache.

  python scripts_warm_cache.py --seed    # copy generator ground-truth for the sample PDFs into llm_cache/
                                         #   (marked source="seed": the UI shows it as a pre-recorded extraction)
  python scripts_warm_cache.py --live    # call the real LLM for every sample PDF (needs ANTHROPIC_API_KEY or GEMINI_API_KEY)
                                         #   and overwrite the cache (source="llm"). Files already done by the LLM are
                                         #   skipped, so you can simply re-run after a temporary API error.
  python scripts_warm_cache.py --live --force   # redo every file, even ones already extracted by the LLM
"""
import argparse
import json
import sys
import time

from app import config
from app.pipeline import extract
from app.pipeline.intake import sha256

ROOT = config.SAMPLES_DIR


def all_pdfs():
    return sorted(list(ROOT.glob("*.pdf")) + list((ROOT / "historical").glob("*.pdf")))


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--seed", action="store_true")
    g.add_argument("--live", action="store_true")
    ap.add_argument("--force", action="store_true", help="with --live: redo files that already have an LLM extraction")
    a = ap.parse_args()
    failed = []
    for pdf in all_pdfs():
        data = pdf.read_bytes()
        sha = sha256(data)
        if a.seed:
            truth = json.loads((ROOT / "truth" / (pdf.name + ".json")).read_text(encoding="utf-8"))
            extract.write_cache(sha, truth, "seed", "generator-ground-truth", pdf.name)
            print("seeded", pdf.name, sha[:10])
            continue
        if not config.LLM_API_KEY:
            sys.exit("no API key: set ANTHROPIC_API_KEY or GEMINI_API_KEY")
        cached = extract.read_cache(sha)
        if cached and cached.get("source") == "llm" and not a.force:
            print("skip  ", pdf.name, "(already extracted by the LLM)")
            continue
        try:
            raw = extract.call_llm(data, patient=True)
        except Exception as e:  # keep going; report at the end
            failed.append(pdf.name)
            print("FAILED", pdf.name, "-", str(e)[:200])
            continue
        extract.write_cache(sha, raw, "llm", config.LLM_MODEL, pdf.name)
        print("llm   ", pdf.name, sha[:10], "total=", raw.get("total"), "inv=", raw.get("invoice_number"))
        time.sleep(4.5)  # free tier of gemini-3.5-flash-lite allows 15 requests/min: stay under it
    if failed:
        print(f"\n{len(failed)} file(s) failed: {', '.join(failed)}\nRe-run the same command; finished files are skipped.")
        sys.exit(1)
    print("\nAll done.")


if __name__ == "__main__":
    main()
