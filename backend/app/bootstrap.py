"""Database bootstrap and the repeatable-demo reset."""
from __future__ import annotations

from . import models  # noqa: F401  (register tables)
from .db import Base, SessionLocal, engine
from .models import Vendor
from .pipeline import runner
from .seed_loader import load_master_data


def init_db(seed_if_empty: bool = True) -> None:
    Base.metadata.create_all(engine)
    if seed_if_empty:
        with SessionLocal() as db:
            if db.query(Vendor).count() == 0:
                load_master_data(db)
                runner.seed_history(db)


def reset_demo() -> None:
    """Wipe all runs, reload master data and re-process the seeded history."""
    with runner.exclusive():      # waits for in-flight runs; new runs wait until the reset is done
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            load_master_data(db)
            runner.seed_history(db)
