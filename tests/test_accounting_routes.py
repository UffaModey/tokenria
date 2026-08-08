import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.accounting import get_db_path
from db.database import init_db, insert_records

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


def test_summary_groups_by_day(client):
    test_client, db_path = client
    insert_records(
        [
            _record(timestamp="2026-01-01T10:00:00Z", closing_entry_uuid="u1"),
            _record(timestamp="2026-01-01T14:00:00Z", closing_entry_uuid="u2"),
            _record(timestamp="2026-01-02T10:00:00Z", closing_entry_uuid="u3"),
        ],
        db_path,
    )

    response = test_client.get("/api/records/summary?group_by=day")
    assert response.status_code == 200
    rows = response.json()

    periods = {row["period"] for row in rows}
    assert periods == {"2026-01-01", "2026-01-02"}
    day_one = next(row for row in rows if row["period"] == "2026-01-01")
    assert day_one["input_tokens"] == 20  # two records, 10 tokens each


def test_summary_groups_by_week_and_month(client):
    test_client, db_path = client
    insert_records(
        [_record(timestamp="2026-01-15T10:00:00Z", closing_entry_uuid="u1")], db_path
    )

    week_rows = test_client.get("/api/records/summary?group_by=week").json()
    month_rows = test_client.get("/api/records/summary?group_by=month").json()

    # SQLite's %W (Monday-start week number) for 2026-01-15
    assert week_rows[0]["period"] == "2026-02"
    assert month_rows[0]["period"] == "2026-01"


def test_summary_filters_by_source_and_is_estimated(client):
    test_client, db_path = client
    insert_records(
        [
            _record(
                timestamp="2026-01-01T10:00:00Z",
                closing_entry_uuid="u1",
                is_estimated=False,
            ),
            _record(
                timestamp="2026-01-01T10:00:00Z",
                closing_entry_uuid="u2",
                is_estimated=True,
                source="text_paste",
                session_id=None,
            ),
        ],
        db_path,
    )

    exact_only = test_client.get(
        "/api/records/summary?group_by=day&is_estimated=false"
    ).json()
    estimated_only = test_client.get(
        "/api/records/summary?group_by=day&is_estimated=true"
    ).json()
    text_paste_only = test_client.get(
        "/api/records/summary?group_by=day&source=text_paste"
    ).json()

    assert all(not row["is_estimated"] for row in exact_only)
    assert all(row["is_estimated"] for row in estimated_only)
    assert all(row["source"] == "text_paste" for row in text_paste_only)


def test_list_records_pagination_and_source_filter(client):
    test_client, db_path = client
    insert_records(
        [
            _record(timestamp="2026-01-01T10:00:00Z", closing_entry_uuid=f"u{i}")
            for i in range(5)
        ],
        db_path,
    )

    page = test_client.get("/api/records?limit=2&offset=0").json()
    assert len(page) == 2

    filtered = test_client.get("/api/records?source=claude_code").json()
    assert all(row["source"] == "claude_code" for row in filtered)
    assert all(isinstance(row["is_estimated"], bool) for row in filtered)
