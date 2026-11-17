"""Test environment: offline, deterministic, isolated SQLite file. Must run before `app` is imported."""
import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="invagent_"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["LLM_MODE"] = "cached"
for _k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "LLM_PROVIDER"):
    os.environ[_k] = ""                   # tests never touch the network
os.environ["STAGE_DELAY_MS"] = "0"
os.environ["APP_PASSWORD"] = ""

import pytest  # noqa: E402

from app import bootstrap, config  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Run  # noqa: E402
from app.pipeline import runner  # noqa: E402

ORDER = ["01_happy_sgi_0418.pdf", "02_happy_nimbus_0091.pdf", "03a_split_apex_1101.pdf", "03b_split_apex_1102.pdf",
         "03c_split_apex_1103.pdf", "04_implied_po_kaveri_2231.pdf", "05_dup_sgi_0418_scan.pdf",
         "06_bankchange_orbit_7782.pdf"]


def run_sample(db, name: str) -> Run:
    p = config.SAMPLES_DIR / name
    r = runner.create_run(db, name, p.read_bytes(), source="sample")
    runner.process_run(r.id)
    db.expire_all()
    return db.get(Run, r.id)


@pytest.fixture(scope="module")
def demo():
    """Reset, then run every sample in demo order (01 before 05; 03a -> 03b -> 03c)."""
    bootstrap.reset_demo()
    db = SessionLocal()
    runs = {name: run_sample(db, name) for name in ORDER}
    yield db, runs
    db.close()


def fired(run: Run) -> set[str]:
    return set(run.decision_detail.get("fired_rules", []))

