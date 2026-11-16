"""ETL: Source (public) -> Core (core) -> Mart (mart). Все шаги идемпотентны."""
from datetime import date

from etl.config import SQL_DIR, Settings
from etl.db import get_logger, sql_sections

log = get_logger("etl")


def apply_ddl(conn) -> None:
    with conn.cursor() as cur:
        cur.execute((SQL_DIR / "01_ddl.sql").read_text(encoding="utf-8"))
    conn.commit()
    log.info("DDL applied (schemas core, mart)")


def refresh_dims(conn) -> int:
    secs = sql_sections(SQL_DIR / "10_dims.sql")
    with conn.cursor() as cur:
        cur.execute(secs["clear"])
        cur.execute(secs["load"])
        n = cur.rowcount
    conn.commit()
    log.info("core.dim_city refreshed: %d distinct gc_id", n)
    return n


def load_core(conn, s: Settings, start: date, end: date) -> dict:
    """Атомарная перезапись окна [start, end] по loading_date: DELETE + INSERT в одной транзакции."""
    secs = sql_sections(SQL_DIR / "20_load_core.sql")
    params = {"start_date": start, "end_date": end, "rub_min_price": s.rub_min_price}
    try:
        with conn.cursor() as cur:
            cur.execute(secs["stage"], params)
            cur.execute("SELECT count(*) FROM stg_prices")
            read = cur.fetchone()[0]
            cur.execute("SELECT dq_reason, count(*) FROM stg_prices "
                        "WHERE dq_reason IS NOT NULL GROUP BY 1 ORDER BY 2 DESC")
            reasons = dict(cur.fetchall())
            for name in ("del_body_groups", "del_core", "del_quarantine"):
                cur.execute(secs[name], params)
            cur.execute(secs["ins_core"], params)
            loaded = cur.rowcount
            cur.execute(secs["ins_quarantine"], params)
            quarantined = cur.rowcount
            cur.execute(secs["ins_body_groups"], params)
            bg = cur.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    stats = {"read": read, "loaded": loaded, "quarantined": quarantined,
             "body_group_rows": bg, "dq_reasons": reasons}
    log.info("core load [%s..%s]: read=%d loaded=%d quarantined=%d body_group_rows=%d",
             start, end, read, loaded, quarantined, bg)
    for reason, cnt in reasons.items():
        log.info("  DQ %-24s %d", reason, cnt)
    return stats


def build_mart(conn, as_of: date) -> int:
    secs = sql_sections(SQL_DIR / "30_mart_route_card.sql")
    try:
        with conn.cursor() as cur:
            cur.execute(secs["clear"])
            cur.execute(secs["build"], {"as_of": as_of})
            n = cur.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    log.info("mart.mart_route_card rebuilt: %d rows (as_of=%s)", n, as_of)
    return n
