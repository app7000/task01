import logging
import re
from pathlib import Path

import psycopg

from etl.config import Settings


def connect(settings: Settings) -> psycopg.Connection:
    # ClientCursor: клиентская подстановка параметров, нужна для многооператорных скриптов
    return psycopg.connect(settings.dsn, cursor_factory=psycopg.ClientCursor)


def sql_sections(path: Path) -> dict[str, str]:
    """Разбивает .sql на секции по маркерам '-- @@ name'."""
    text = path.read_text(encoding="utf-8")
    parts = re.split(r"^-- @@\s*(\S+)\s*$", text, flags=re.M)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}


def get_logger(name: str) -> logging.Logger:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return logging.getLogger(name)
