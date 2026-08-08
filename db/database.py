"""SQLite persistence for normalized usage records.

See stages/02-sqlite-schema.md for the external_id/cost_usd design this
implements.
"""

import sqlite3
from pathlib import Path

from db.pricing import compute_cost

DEFAULT_DB_PATH = Path(__file__).parent / "tokenria.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
    finally:
        conn.close()


def insert_records(records: list[dict], db_path: Path = DEFAULT_DB_PATH) -> int:
    """Insert normalized records, skipping any whose external_id already exists.

    Returns the number of rows actually inserted (excludes ignored duplicates).
    """
    conn = get_connection(db_path)
    inserted = 0
    try:
        for record in records:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO records (
                    external_id, source, session_id, model, timestamp,
                    prompt_text, response_text, input_tokens, output_tokens,
                    cache_read_tokens, cache_write_tokens, is_estimated, cost_usd
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _external_id(record),
                    record["source"],
                    record.get("session_id"),
                    record.get("model"),
                    record["timestamp"],
                    record.get("prompt_text"),
                    record.get("response_text"),
                    record["input_tokens"],
                    record["output_tokens"],
                    record["cache_read_tokens"],
                    record["cache_write_tokens"],
                    record["is_estimated"],
                    compute_cost(
                        record.get("model"),
                        record["input_tokens"],
                        record["output_tokens"],
                        record["cache_read_tokens"],
                        record["cache_write_tokens"],
                    ),
                ),
            )
            inserted += cursor.rowcount
        conn.commit()
    finally:
        conn.close()
    return inserted


def _external_id(record: dict) -> str | None:
    closing_entry_uuid = record.get("closing_entry_uuid")
    if closing_entry_uuid is None:
        return None
    return f"{record['source']}:{record.get('session_id')}:{closing_entry_uuid}"
