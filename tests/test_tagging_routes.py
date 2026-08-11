import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.accounting import get_db_path
from db.database import get_connection, init_db, insert_records

BASE_RECORD = {
    "source": "claude_code",
    "session_id": "sess1",
    "model": "claude-sonnet-5",
    "prompt_text": "hello",
    "response_text": "hi there",
    "input_tokens": 10,
    "output_tokens": 20,
    "cache_read_tokens": 100,
    "cache_write_tokens": 50,
    "is_estimated": False,
    "timestamp": "2026-01-01T10:00:00Z",
}


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "tokenria.db"
    init_db(db_path)

    app.dependency_overrides[get_db_path] = lambda: db_path
    yield TestClient(app), db_path
    app.dependency_overrides.clear()


def _record(**overrides):
    return {**BASE_RECORD, **overrides}


def test_has_response_text_filter_excludes_empty_responses(client):
    test_client, db_path = client
    insert_records(
        [
            _record(closing_entry_uuid="u1", response_text="a real reply"),
            _record(closing_entry_uuid="u2", response_text=""),
        ],
        db_path,
    )

    taggable = test_client.get("/api/records?has_response_text=true").json()
    empty_only = test_client.get("/api/records?has_response_text=false").json()

    assert len(taggable) == 1
    assert taggable[0]["response_text"] == "a real reply"
    assert len(empty_only) == 1
    assert empty_only[0]["response_text"] == ""


def test_picker_returns_lightweight_taggable_records(client):
    test_client, db_path = client
    insert_records(
        [
            _record(
                closing_entry_uuid="u1",
                session_id="sess-a",
                timestamp="2026-01-01T10:00:00Z",
                prompt_text="a" * 200,
                response_text="reply one",
            ),
            _record(closing_entry_uuid="u2", response_text=""),
        ],
        db_path,
    )

    response = test_client.get("/api/records/picker")
    assert response.status_code == 200
    picker = response.json()

    assert len(picker) == 1
    row = picker[0]
    expected_keys = {"id", "timestamp", "session_id", "session_name", "prompt_preview"}
    assert set(row.keys()) == expected_keys
    assert row["session_id"] == "sess-a"
    assert row["timestamp"] == "2026-01-01T10:00:00Z"
    assert row["prompt_preview"] == "a" * 80


def test_get_record_found_and_not_found(client):
    test_client, db_path = client
    insert_records([_record(closing_entry_uuid="u1")], db_path)

    conn = get_connection(db_path)
    record_id = conn.execute("SELECT id FROM records").fetchone()[0]
    conn.close()

    found = test_client.get(f"/api/records/{record_id}")
    assert found.status_code == 200
    assert found.json()["prompt_text"] == "hello"

    missing = test_client.get("/api/records/999999")
    assert missing.status_code == 404


def test_put_tags_round_trips_and_replaces_rather_than_accumulates(client):
    test_client, db_path = client
    insert_records([_record(closing_entry_uuid="u1")], db_path)

    conn = get_connection(db_path)
    record_id = conn.execute("SELECT id FROM records").fetchone()[0]
    conn.close()

    first_save = test_client.put(
        f"/api/records/{record_id}/tags",
        json=[
            {"span_start": 0, "span_end": 2, "used": True},
            {"span_start": 3, "span_end": 8, "used": False},
        ],
    )
    assert first_save.status_code == 200

    tags = test_client.get(f"/api/records/{record_id}/tags").json()
    assert len(tags) == 2
    assert {(t["span_start"], t["span_end"], t["used"]) for t in tags} == {
        (0, 2, True),
        (3, 8, False),
    }

    # re-tag differently: fewer spans, different states
    second_save = test_client.put(
        f"/api/records/{record_id}/tags",
        json=[{"span_start": 0, "span_end": 8, "used": True}],
    )
    assert second_save.status_code == 200

    conn = get_connection(db_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM tags WHERE record_id = ?", (record_id,)
    ).fetchone()[0]
    conn.close()
    assert count == 1

    tags_after = test_client.get(f"/api/records/{record_id}/tags").json()
    assert tags_after == [
        {
            "id": tags_after[0]["id"],
            "span_start": 0,
            "span_end": 8,
            "used": True,
            "source": "manual",
        }
    ]


def test_put_tags_never_touches_auto_rows(client):
    test_client, db_path = client
    insert_records([_record(closing_entry_uuid="u1")], db_path)

    conn = get_connection(db_path)
    record_id = conn.execute("SELECT id FROM records").fetchone()[0]
    conn.execute(
        "INSERT INTO tags (id, record_id, span_start, span_end, used, source) "
        "VALUES (?, ?, 0, 4, 1, 'auto')",
        (str(uuid.uuid4()), record_id),
    )
    conn.commit()
    conn.close()

    test_client.put(
        f"/api/records/{record_id}/tags",
        json=[{"span_start": 0, "span_end": 8, "used": False}],
    )

    tags = test_client.get(f"/api/records/{record_id}/tags").json()
    sources = {t["source"] for t in tags}
    assert sources == {"manual", "auto"}
    auto_tag = next(t for t in tags if t["source"] == "auto")
    assert auto_tag["span_start"] == 0 and auto_tag["span_end"] == 4


def test_put_tags_on_missing_record_returns_404(client):
    test_client, _ = client
    response = test_client.put(
        "/api/records/999999/tags",
        json=[{"span_start": 0, "span_end": 1, "used": True}],
    )
    assert response.status_code == 404
