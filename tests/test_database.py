import sqlite3
import uuid

from db.database import get_connection, init_db, insert_records

BASE_RECORD = {
    "source": "claude_code",
    "timestamp": "2026-01-01T00:00:00Z",
    "session_id": "sess1",
    "model": "claude-sonnet-5",
    "prompt_text": "hello",
    "response_text": "hi there",
    "input_tokens": 100,
    "output_tokens": 200,
    "cache_read_tokens": 1000,
    "cache_write_tokens": 500,
    "cache_write_1h_tokens": 400,
    "cache_write_5m_tokens": 100,
    "is_estimated": False,
    "closing_entry_uuid": "uuid-1",
}


def _table_names(conn: sqlite3.Connection) -> set:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


def test_init_db_creates_records_and_tags_tables_with_indexes(tmp_path):
    db_path = tmp_path / "tokenria.db"
    init_db(db_path)

    conn = get_connection(db_path)
    assert {"records", "tags"} <= _table_names(conn)
    index_names = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    }
    assert "idx_records_timestamp" in index_names
    assert "idx_records_source" in index_names
    assert "idx_tags_record_id" in index_names
    conn.close()


def test_insert_records_computes_external_id_and_cost(tmp_path):
    db_path = tmp_path / "tokenria.db"
    init_db(db_path)

    inserted = insert_records([BASE_RECORD], db_path)
    assert inserted == 1

    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT external_id, cost_usd, is_estimated FROM records"
    ).fetchone()
    conn.close()

    assert row[0] == "claude_code:sess1:uuid-1"
    # 100 * 2.00 + 200 * 10.00 + 400 * 4.00 + 100 * 2.50 + 1000 * 0.20, all /1e6
    assert (
        row[1]
        == (100 * 2.00 + 200 * 10.00 + 400 * 4.00 + 100 * 2.50 + 1000 * 0.20)
        / 1_000_000
    )
    assert row[2] == 0


def test_insert_records_is_idempotent_on_rerun(tmp_path):
    db_path = tmp_path / "tokenria.db"
    init_db(db_path)

    first = insert_records([BASE_RECORD], db_path)
    second = insert_records([BASE_RECORD], db_path)

    conn = get_connection(db_path)
    count = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    conn.close()

    assert first == 1
    assert second == 0
    assert count == 1


def test_unrecognized_model_gets_null_cost_not_dropped(tmp_path):
    db_path = tmp_path / "tokenria.db"
    init_db(db_path)

    record = {
        **BASE_RECORD,
        "model": "some-unknown-model",
        "closing_entry_uuid": "uuid-2",
    }
    insert_records([record], db_path)

    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT cost_usd FROM records WHERE model = ?", ("some-unknown-model",)
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] is None


def test_init_db_adds_session_name_to_a_table_created_without_it(tmp_path):
    db_path = tmp_path / "tokenria.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE records (
            id INTEGER PRIMARY KEY,
            external_id TEXT UNIQUE,
            source TEXT NOT NULL,
            session_id TEXT,
            model TEXT,
            timestamp TEXT NOT NULL,
            prompt_text TEXT,
            response_text TEXT,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cache_read_tokens INTEGER NOT NULL DEFAULT 0,
            cache_write_tokens INTEGER NOT NULL DEFAULT 0,
            is_estimated BOOLEAN NOT NULL,
            cost_usd REAL
        )
        """
    )
    conn.commit()
    conn.close()

    init_db(db_path)

    conn = get_connection(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(records)")}
    conn.close()
    assert "session_name" in columns


def test_insert_records_writes_and_backfills_session_name(tmp_path):
    db_path = tmp_path / "tokenria.db"
    init_db(db_path)

    insert_records([{**BASE_RECORD, "session_name": "Fix the off-by-one bug"}], db_path)

    conn = get_connection(db_path)
    name = conn.execute("SELECT session_name FROM records").fetchone()[0]
    assert name == "Fix the off-by-one bug"

    # a later ingest run re-parses the whole session and learns its settled
    # title only then -- that must update the row inserted earlier, not
    # just fill in rows that don't have a name yet.
    insert_records(
        [
            {
                **BASE_RECORD,
                "closing_entry_uuid": "uuid-2",
                "session_name": "Fix parse_session's loop bound",
            }
        ],
        db_path,
    )
    names = {
        row[0] for row in conn.execute("SELECT session_name FROM records").fetchall()
    }
    conn.close()
    assert names == {"Fix parse_session's loop bound"}


def test_insert_records_defaults_is_subagent_false_when_key_absent(tmp_path):
    db_path = tmp_path / "tokenria.db"
    init_db(db_path)

    insert_records([BASE_RECORD], db_path)

    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT is_subagent, agent_type, agent_description FROM records"
    ).fetchone()
    conn.close()

    assert row == (0, None, None)


def test_insert_records_persists_subagent_fields_and_uses_subagent_external_id(
    tmp_path,
):
    db_path = tmp_path / "tokenria.db"
    init_db(db_path)

    subagent_record = {
        **BASE_RECORD,
        "closing_entry_uuid": "uuid-3",
        "is_subagent": True,
        "agent_type": "general-purpose",
        "agent_description": "Survey subdirectories",
        "agent_id": "a9b9a92a1c",
    }
    insert_records([subagent_record], db_path)

    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT external_id, is_subagent, agent_type, agent_description "
        "FROM records WHERE agent_type = 'general-purpose'"
    ).fetchone()
    conn.close()

    assert row[0] == "claude_code:subagent:a9b9a92a1c:uuid-3"
    assert row[1] == 1
    assert row[2] == "general-purpose"
    assert row[3] == "Survey subdirectories"


def test_subagent_and_main_thread_records_in_same_session_dont_collide(tmp_path):
    db_path = tmp_path / "tokenria.db"
    init_db(db_path)

    main_thread_record = {**BASE_RECORD, "closing_entry_uuid": "same-uuid"}
    subagent_record = {
        **BASE_RECORD,
        "closing_entry_uuid": "same-uuid",
        "is_subagent": True,
        "agent_type": "general-purpose",
        "agent_description": "Survey subdirectories",
        "agent_id": "a9b9a92a1c",
    }

    inserted = insert_records([main_thread_record, subagent_record], db_path)
    assert inserted == 2

    conn = get_connection(db_path)
    count = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    conn.close()
    assert count == 2


def test_deleting_a_record_cascades_to_its_tags(tmp_path):
    db_path = tmp_path / "tokenria.db"
    init_db(db_path)
    insert_records([BASE_RECORD], db_path)

    conn = get_connection(db_path)
    record_id = conn.execute("SELECT id FROM records").fetchone()[0]
    conn.execute(
        "INSERT INTO tags (id, record_id, span_start, span_end, used, source) "
        "VALUES (?, ?, 0, 10, 1, 'manual')",
        (str(uuid.uuid4()), record_id),
    )
    conn.commit()

    conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
    conn.commit()

    remaining_tags = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
    conn.close()

    assert remaining_tags == 0
