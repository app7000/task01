"""CLI.  Примеры:
  python -m etl.run_all                                        # всё, окно по умолчанию
  python -m etl.run_all --steps core,mart --start-date 2026-09-01 --end-date 2026-09-30   # backfill
"""
import argparse
from datetime import date

from etl import pipeline
from etl.config import Settings
from etl.db import connect, get_logger

log = get_logger("run_all")
ALL = "ddl,dims,core,mart,ml"


def main() -> None:
    s = Settings()
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", default=ALL, help=f"подмножество из: {ALL}")
    ap.add_argument("--start-date", type=date.fromisoformat, default=s.start_date)
    ap.add_argument("--end-date", type=date.fromisoformat, default=s.end_date)
    ap.add_argument("--as-of", type=date.fromisoformat, default=s.as_of)
    a = ap.parse_args()
    steps = [x.strip() for x in a.steps.split(",")]

    conn = connect(s)
    try:
        if "ddl" in steps:
            pipeline.apply_ddl(conn)
        if "dims" in steps:
            pipeline.refresh_dims(conn)
        if "core" in steps:
            pipeline.load_core(conn, s, a.start_date, a.end_date)
        if "mart" in steps:
            pipeline.build_mart(conn, a.as_of)
        if "ml" in steps:
            from ml.run import run_ml
            run_ml(conn, a.as_of, s.seed)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
