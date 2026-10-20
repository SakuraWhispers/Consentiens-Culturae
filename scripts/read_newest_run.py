"""Read-only: find the newest persisted run and summarize its report shape.

Used to recover the outcome of a POST whose HTTP response was lost to a
client timeout. Prints run_id/state only — never env values or keys.
Run: .venv\\Scripts\\python.exe scripts\\read_newest_run.py
"""

from __future__ import annotations

import sys

from sqlalchemy import select

from app.config import Settings
from app.services.persistence import DecisionRun, _session, get_engine


def main() -> None:
    settings = Settings.from_env()
    engine = get_engine(settings.database_url)
    with _session(engine) as session:
        row = session.execute(
            select(DecisionRun).order_by(DecisionRun.created_at.desc()).limit(1)
        ).scalar_one_or_none()
        if row is None:
            print(sys.stderr, "no runs persisted yet")
            return
        print("run_id:", row.run_id)
        print("state:", row.state)


if __name__ == "__main__":
    main()
