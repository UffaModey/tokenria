"""SQLite persistence for normalized usage records.

See stages/02-sqlite-schema.md for the external_id/cost_usd design this
implements.
"""

import sqlite3
import uuid
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
        _migrate_add_session_name_column(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate_add_session_name_column(conn: sqlite3.Connection) -> None:
    """Add session_name to a records table created before this column existed.

    `CREATE TABLE IF NOT EXISTS` in schema.sql only shapes brand-new
    databases; a pre-existing db/tokenria.db needs this to pick it up.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(records)")}
    if "session_name" not in columns:
        conn.execute("ALTER TABLE records ADD COLUMN session_name TEXT")


def insert_records(records: list[dict], db_path: Path = DEFAULT_DB_PATH) -> int:
    """Insert normalized records, skipping any whose external_id already exists.

    Also refreshes session_name on every existing row of each session
    present in `records`, since a session's title can settle to its final
    value only after re-parsing the file on a later ingest run.

    Returns the number of rows actually inserted (excludes ignored duplicates).
    """
    conn = get_connection(db_path)
    inserted = 0
    try:
        for record in records:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO records (
                    id, external_id, source, session_id, session_name, model,
                    timestamp, prompt_text, response_text, input_tokens,
                    output_tokens, cache_read_tokens, cache_write_tokens,
                    cache_write_1h_tokens, cache_write_5m_tokens,
                    is_estimated, cost_usd, is_subagent, agent_type,
                    agent_description
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    _external_id(record),
                    record["source"],
                    record.get("session_id"),
                    record.get("session_name"),
                    record.get("model"),
                    record["timestamp"],
                    record.get("prompt_text"),
                    record.get("response_text"),
                    record["input_tokens"],
                    record["output_tokens"],
                    record["cache_read_tokens"],
                    record["cache_write_tokens"],
                    record.get("cache_write_1h_tokens", 0),
                    record.get("cache_write_5m_tokens", 0),
                    record["is_estimated"],
                    compute_cost(
                        record.get("model"),
                        record["input_tokens"],
                        record["output_tokens"],
                        record["cache_read_tokens"],
                        record.get("cache_write_1h_tokens", 0),
                        record.get("cache_write_5m_tokens", 0),
                    ),
                    record.get("is_subagent", False),
                    record.get("agent_type"),
                    record.get("agent_description"),
                ),
            )
            inserted += cursor.rowcount

        session_names = {
            record["session_id"]: record["session_name"]
            for record in records
            if record.get("session_id") and record.get("session_name")
        }
        for session_id, session_name in session_names.items():
            conn.execute(
                "UPDATE records SET session_name = ? WHERE session_id = ?",
                (session_name, session_id),
            )

        conn.commit()
    finally:
        conn.close()
    return inserted


def _external_id(record: dict) -> str | None:
    closing_entry_uuid = record.get("closing_entry_uuid")
    if closing_entry_uuid is None:
        return None
    if record.get("is_subagent"):
        return f"{record['source']}:subagent:{record['agent_id']}:{closing_entry_uuid}"
    return f"{record['source']}:{record.get('session_id')}:{closing_entry_uuid}"
