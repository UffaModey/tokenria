import sqlite3

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
    # 100 * 2.00 + 200 * 10.00 + 500 * 2.50 + 1000 * 0.20 = 3450.00, all /1e6
    assert row[1] == (100 * 2.00 + 200 * 10.00 + 500 * 2.50 + 1000 * 0.20) / 1_000_000
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


def test_deleting_a_record_cascades_to_its_tags(tmp_path):
    db_path = tmp_path / "tokenria.db"
    init_db(db_path)
    insert_records([BASE_RECORD], db_path)

    conn = get_connection(db_path)
    record_id = conn.execute("SELECT id FROM records").fetchone()[0]
    conn.execute(
        "INSERT INTO tags (record_id, span_start, span_end, used, source) "
        "VALUES (?, 0, 10, 1, 'manual')",
        (record_id,),
    )
    conn.commit()

    conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
    conn.commit()

    remaining_tags = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
    conn.close()

    assert remaining_tags == 0
