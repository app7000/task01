#!/usr/bin/env bash
# Инициализация источника (если пуст) -> ETL -> витрины -> ML -> тесты. Всё идемпотентно.
set -euo pipefail
export PGPASSWORD="${POSTGRES_PASSWORD}"
PSQL="psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT:-5432} -U ${POSTGRES_USER} -d ${POSTGRES_DB} -v ON_ERROR_STOP=1"

until pg_isready -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER}" >/dev/null 2>&1; do
  echo "[entrypoint] waiting for postgres..."; sleep 2
done

if [ "$($PSQL -tAc "SELECT to_regclass('public.prices') IS NOT NULL")" != "t" ]; then
  echo "[entrypoint] applying sql/schema.sql"
  $PSQL -f sql/schema.sql
fi
if [ "$($PSQL -tAc "SELECT count(*) FROM public.prices")" = "0" ]; then
  echo "[entrypoint] generating ${N_PRICES:-300000} synthetic deals"
  $PSQL -v n_prices="${N_PRICES:-300000}" -f sql/synthetic.sql
fi

STEPS="ddl,dims,core,mart"
[ "${RUN_ML:-1}" = "1" ] && STEPS="${STEPS},ml"
python -m etl.run_all --steps "${STEPS}"

if [ "${RUN_TESTS:-1}" = "1" ]; then
  python -m pytest -q tests || echo "[WARN] some tests failed, see output above"
fi
echo "[entrypoint] DONE"
