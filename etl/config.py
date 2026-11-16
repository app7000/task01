import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql" / "dwh"


def _d(name: str, default: str) -> date:
    return date.fromisoformat(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("POSTGRES_HOST", "localhost")
    port: str = os.getenv("POSTGRES_PORT", "5432")
    dbname: str = os.getenv("POSTGRES_DB", "deals_bigdata")
    user: str = os.getenv("POSTGRES_USER", "postgres")
    password: str = os.getenv("POSTGRES_PASSWORD", "")
    as_of: date = _d("AS_OF_DATE", "2026-10-26")
    start_date: date = _d("ETL_START_DATE", "2000-01-01")
    end_date: date = _d("ETL_END_DATE", "2100-01-01")
    rub_min_price: float = float(os.getenv("DQ_RUB_MIN_PRICE", "1000"))
    seed: int = int(os.getenv("RANDOM_SEED", "42"))

    @property
    def dsn(self) -> str:
        return (f"host={self.host} port={self.port} dbname={self.dbname} "
                f"user={self.user} password={self.password}")
