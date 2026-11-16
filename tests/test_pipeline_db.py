"""SQL smoke / идемпотентность. Пропускаются, если БД недоступна или пайплайн не запускался."""
from datetime import date

import psycopg
import pytest

from etl import pipeline
from etl.config import Settings
from etl.db import connect

S = Settings()


@pytest.fixture(scope="module")
def conn():
    try:
        c = connect(S)
        with c.cursor() as cur:
            cur.execute("SELECT count(*) FROM core.prices_clean")
            if cur.fetchone()[0] == 0:
                pytest.skip("core is empty")
    except psycopg.Error:
        pytest.skip("database not available")
    yield c
    c.close()


def q(conn, sql):
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()[0]


def test_core_has_no_invalid_rows(conn):
    assert q(conn, "SELECT count(*) FROM core.prices_clean WHERE price_rub <= 0 OR distance <= 0") == 0
    assert q(conn, "SELECT count(*) FROM core.prices_clean WHERE total_weight < 0 OR total_volume < 0") == 0


def test_no_overlap_with_quarantine(conn):
    assert q(conn, "SELECT count(*) FROM core.prices_clean c "
                   "JOIN core.dq_quarantine_prices x USING (price_id)") == 0


def test_rows_balance(conn):
    src = q(conn, "SELECT count(*) FROM public.prices")
    tot = q(conn, "SELECT (SELECT count(*) FROM core.prices_clean) + "
                  "(SELECT count(*) FROM core.dq_quarantine_prices)")
    assert src == tot


def test_city_dim_unique(conn):
    assert q(conn, "SELECT count(*) - count(DISTINCT gc_id) FROM core.dim_city") == 0


def test_etl_window_idempotent(conn):
    start, end = date(2026, 9, 1), date(2026, 9, 30)
    sql = ("SELECT count(*)::text || '/' || coalesce(sum(price_rub),0)::text FROM core.prices_clean "
           "WHERE loading_date BETWEEN '2026-09-01' AND '2026-09-30'")
    before = q(conn, sql)
    pipeline.load_core(conn, S, start, end)
    pipeline.load_core(conn, S, start, end)
    assert q(conn, sql) == before


def test_mart_idempotent(conn):
    sql = "SELECT count(*)::text || '/' || coalesce(sum(median_trip),0)::text FROM mart.mart_route_card"
    before = q(conn, sql)
    pipeline.build_mart(conn, S.as_of)
    assert q(conn, sql) == before


def test_mart_rules(conn):
    assert q(conn, "SELECT count(*) FROM mart.mart_route_card WHERE month_start > DATE '2026-10-26'") == 0
    assert q(conn, "SELECT count(*) FROM mart.mart_route_card WHERE median_trip < p25_trip "
                   "OR median_trip > p75_trip") == 0


def test_future_predictions_have_no_actuals(conn):
    assert q(conn, "SELECT count(*) FROM mart.ml_price_predictions WHERE split_name='future' AND "
                   "(actual_price_rub IS NOT NULL OR abs_error_rub IS NOT NULL OR ape_pct IS NOT NULL)") == 0
