"""CLI: reset the demo database and run every sample in demo order, printing the decisions.
   python scripts_run_samples.py
"""
import json
import os

os.environ.setdefault("STAGE_DELAY_MS", "0")
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/cli.db")

from app import bootstrap, config  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Run  # noqa: E402
from app.pipeline import runner  # noqa: E402

EXPECTED_ORDER = ["01_happy_sgi_0418.pdf", "02_happy_nimbus_0091.pdf", "03a_split_apex_1101.pdf",
                  "03b_split_apex_1102.pdf", "03c_split_apex_1103.pdf", "04_implied_po_kaveri_2231.pdf",
                  "05_dup_sgi_0418_scan.pdf", "06_bankchange_orbit_7782.pdf"]


def run_sample(db, name):
    p = config.SAMPLES_DIR / name
    r = runner.create_run(db, name, p.read_bytes(), source="sample")
    runner.process_run(r.id)
    db.expire_all()
    return db.get(Run, r.id)


def main():
    bootstrap.reset_demo()
    manifest = {s["file"]: s for s in json.loads((config.SAMPLES_DIR / "manifest.json").read_text())["samples"]}
    bad = 0
    with SessionLocal() as db:
        for name in EXPECTED_ORDER:
            r = run_sample(db, name)
            exp = manifest[name]["expected"]
            ok = "OK " if r.decision == exp else "BAD"
            bad += r.decision != exp
            d = r.decision_detail
            print(f"{ok} #{r.id:<2} {name:<34} -> {r.decision:<8} (expected {exp:<8}) fired={d.get('fired_rules')} "
                  f"warn={d.get('warning_rules')}")
            print("     ", (r.explanation or "")[:230])
        print("bad:", bad)


if __name__ == "__main__":
    main()
