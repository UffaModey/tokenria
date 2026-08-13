import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.analysis import get_db_path
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


def test_trends_cache_read_share_by_period(client):
    test_client, db_path = client
    insert_records(
        [
            _record(
                timestamp="2026-01-01T10:00:00Z",
                closing_entry_uuid="u1",
                input_tokens=100,
                output_tokens=100,
                cache_read_tokens=1800,
                cache_write_tokens=0,
            ),
        ],
        db_path,
    )

    rows = test_client.get("/api/analysis/trends?group_by=day").json()["by_period"]

    assert rows[0]["period"] == "2026-01-01"
    # 1800 / (100 + 0 + 1800 + 100) = 90%
    assert rows[0]["cache_read_share"] == pytest.approx(90.0)


def test_trends_cache_read_share_null_when_no_tokens(client):
    test_client, db_path = client
    insert_records(
        [
            _record(
                timestamp="2026-01-01T10:00:00Z",
                closing_entry_uuid="u1",
                input_tokens=0,
                output_tokens=0,
                cache_read_tokens=0,
                cache_write_tokens=0,
            ),
        ],
        db_path,
    )

    rows = test_client.get("/api/analysis/trends?group_by=day").json()["by_period"]

    assert rows[0]["cache_read_share"] is None


def test_trends_by_period_model_splits_records(client):
    test_client, db_path = client
    insert_records(
        [
            _record(
                timestamp="2026-01-01T10:00:00Z",
                closing_entry_uuid="u1",
                model="claude-sonnet-5",
            ),
            _record(
                timestamp="2026-01-01T11:00:00Z",
                closing_entry_uuid="u2",
                model="claude-haiku-4-5",
            ),
        ],
        db_path,
    )

    rows = test_client.get("/api/analysis/trends?group_by=day").json()[
        "by_period_model"
    ]

    models = {row["model"] for row in rows}
    assert models == {"claude-sonnet-5", "claude-haiku-4-5"}


def test_repeated_prompts_filters_by_min_length_and_occurrences(client):
    test_client, db_path = client
    insert_records(
        [
            _record(
                session_id="sess1",
                timestamp="2026-01-01T10:00:00Z",
                closing_entry_uuid="u1",
                prompt_text="a repeated long enough prompt to pass the length filter",
            ),
            _record(
                session_id="sess2",
                timestamp="2026-01-02T10:00:00Z",
                closing_entry_uuid="u2",
                prompt_text="a repeated long enough prompt to pass the length filter",
            ),
            _record(
                session_id="sess3",
                timestamp="2026-01-03T10:00:00Z",
                closing_entry_uuid="u3",
                prompt_text="yes",
            ),
            _record(
                session_id="sess4",
                timestamp="2026-01-04T10:00:00Z",
                closing_entry_uuid="u4",
                prompt_text="yes",
            ),
        ],
        db_path,
    )

    rows = test_client.get(
        "/api/analysis/repeated-prompts?min_occurrences=2&min_length=20"
    ).json()

    prompt_texts = {row["prompt_text"] for row in rows}
    assert "a repeated long enough prompt to pass the length filter" in prompt_texts
    assert "yes" not in prompt_texts


def test_repeated_prompts_ranked_by_total_cost_not_occurrence_count(client):
    test_client, db_path = client
    insert_records(
        [
            _record(
                session_id=f"cheap-sess{i}",
                timestamp="2026-01-01T10:00:00Z",
                closing_entry_uuid=f"cheap{i}",
                prompt_text="a cheap prompt repeated many times over here",
                input_tokens=1,
                output_tokens=1,
                cache_read_tokens=0,
                cache_write_tokens=0,
            )
            for i in range(5)
        ]
        + [
            _record(
                session_id=f"expensive-sess{i}",
                timestamp="2026-01-01T10:00:00Z",
                closing_entry_uuid=f"expensive{i}",
                prompt_text="an expensive prompt repeated only a couple times",
                model="claude-fable-5",
                input_tokens=1_000_000,
                output_tokens=1_000_000,
                cache_read_tokens=0,
                cache_write_tokens=0,
            )
            for i in range(2)
        ],
        db_path,
    )

    rows = test_client.get(
        "/api/analysis/repeated-prompts?min_occurrences=2&min_length=20"
    ).json()

    assert rows[0]["prompt_text"] == "an expensive prompt repeated only a couple times"


def test_repeated_prompts_model_breakdown_sums_to_total_cost(client):
    test_client, db_path = client
    insert_records(
        [
            _record(
                session_id="sess1",
                timestamp="2026-01-01T10:00:00Z",
                closing_entry_uuid="u1",
                prompt_text="a shared prompt used across two different models",
                model="claude-fable-5",
                input_tokens=1_000_000,
                output_tokens=0,
                cache_read_tokens=0,
                cache_write_tokens=0,
            ),
            _record(
                session_id="sess2",
                timestamp="2026-01-02T10:00:00Z",
                closing_entry_uuid="u2",
                prompt_text="a shared prompt used across two different models",
                model="claude-sonnet-5",
                input_tokens=1_000_000,
                output_tokens=0,
                cache_read_tokens=0,
                cache_write_tokens=0,
            ),
        ],
        db_path,
    )

    rows = test_client.get(
        "/api/analysis/repeated-prompts?min_occurrences=2&min_length=20"
    ).json()
    row = rows[0]

    # claude-fable-5's input rate (10.00) is 5x claude-sonnet-5's (2.00).
    assert row["models"][0] == {
        "model": "claude-fable-5",
        "cost_usd": pytest.approx(10.0),
    }
    assert row["models"][1] == {
        "model": "claude-sonnet-5",
        "cost_usd": pytest.approx(2.0),
    }
    assert sum(m["cost_usd"] for m in row["models"]) == pytest.approx(row["total_cost"])


def test_cost_drivers_category_dollars_match_hand_calc(client):
    test_client, db_path = client
    insert_records(
        [
            _record(
                timestamp="2026-01-01T10:00:00Z",
                closing_entry_uuid="u1",
                model="claude-sonnet-5",
                input_tokens=1_000_000,
                output_tokens=1_000_000,
                cache_read_tokens=1_000_000,
                cache_write_tokens=1_000_000,
                cache_write_1h_tokens=1_000_000,
                cache_write_5m_tokens=0,
            ),
        ],
        db_path,
    )

    rows = test_client.get("/api/analysis/cost-drivers?group_by=day").json()[
        "cost_by_category"
    ]

    # claude-sonnet-5 rates ($/M tok): input 2.00, output 10.00, cache_write_1h
    # 4.00, cache_read 0.20
    row = rows[0]
    assert row["input_cost"] == pytest.approx(2.0)
    assert row["output_cost"] == pytest.approx(10.0)
    assert row["cache_write_cost"] == pytest.approx(4.0)
    assert row["cache_read_cost"] == pytest.approx(0.2)


def test_cost_drivers_category_model_breakdown_sorted_by_cost(client):
    test_client, db_path = client
    insert_records(
        [
            _record(
                timestamp="2026-01-01T10:00:00Z",
                closing_entry_uuid="u1",
                model="claude-haiku-4-5",
                input_tokens=0,
                output_tokens=0,
                cache_read_tokens=0,
                cache_write_tokens=1_000_000,
                cache_write_1h_tokens=1_000_000,
                cache_write_5m_tokens=0,
            ),
            _record(
                timestamp="2026-01-01T11:00:00Z",
                closing_entry_uuid="u2",
                model="claude-fable-5",
                input_tokens=0,
                output_tokens=0,
                cache_read_tokens=0,
                cache_write_tokens=1_000_000,
                cache_write_1h_tokens=1_000_000,
                cache_write_5m_tokens=0,
            ),
        ],
        db_path,
    )

    data = test_client.get("/api/analysis/cost-drivers?group_by=day").json()
    breakdown = data["cost_by_category_model"]["2026-01-01"]["cache_write_cost"]

    # claude-fable-5's cache_write_1h rate (20.00) is 10x claude-haiku-4-5's (2.00).
    assert breakdown[0]["model"] == "claude-fable-5"
    assert breakdown[0]["cost_usd"] == pytest.approx(20.0)
    assert breakdown[1]["model"] == "claude-haiku-4-5"
    assert breakdown[1]["cost_usd"] == pytest.approx(2.0)
    # Categories with no cost for either model stay empty, not zero-filled.
    assert data["cost_by_category_model"]["2026-01-01"]["input_cost"] == []


def test_cost_drivers_cost_by_model_ranked_descending(client):
    test_client, db_path = client
    insert_records(
        [
            _record(
                timestamp="2026-01-01T10:00:00Z",
                closing_entry_uuid="u1",
                model="claude-haiku-4-5",
                input_tokens=1_000_000,
                output_tokens=0,
                cache_read_tokens=0,
                cache_write_tokens=0,
            ),
            _record(
                timestamp="2026-01-01T10:00:00Z",
                closing_entry_uuid="u2",
                model="claude-fable-5",
                input_tokens=1_000_000,
                output_tokens=0,
                cache_read_tokens=0,
                cache_write_tokens=0,
            ),
        ],
        db_path,
    )

    rows = test_client.get("/api/analysis/cost-drivers?group_by=day").json()[
        "cost_by_model"
    ]

    assert rows[0]["model"] == "claude-fable-5"
    assert rows[0]["cost_usd"] > rows[1]["cost_usd"]


def test_cost_drivers_human_vs_subagent_split(client):
    test_client, db_path = client
    insert_records(
        [
            _record(timestamp="2026-01-01T10:00:00Z", closing_entry_uuid="u1"),
            _record(
                timestamp="2026-01-01T11:00:00Z",
                closing_entry_uuid="u2",
                is_subagent=True,
                agent_id="a1",
                agent_type="Explore",
            ),
        ],
        db_path,
    )

    split = test_client.get("/api/analysis/cost-drivers?group_by=day").json()[
        "human_vs_subagent"
    ]

    assert split["human_cost_usd"] > 0
    assert split["subagent_cost_usd"] > 0


def test_cost_drivers_unknown_cost_grouped_by_model(client):
    test_client, db_path = client
    insert_records(
        [
            _record(
                timestamp="2026-01-01T10:00:00Z",
                closing_entry_uuid="u1",
                model="totally-unknown-model",
            ),
        ],
        db_path,
    )

    unknown = test_client.get("/api/analysis/cost-drivers?group_by=day").json()[
        "unknown_cost"
    ]

    assert unknown[0]["model"] == "totally-unknown-model"
    assert unknown[0]["record_count"] == 1


def test_cost_drivers_top_sessions_exclude_unknown_cost(client):
    test_client, db_path = client
    insert_records(
        [
            _record(
                session_id="sess1",
                timestamp="2026-01-01T10:00:00Z",
                closing_entry_uuid="u1",
            ),
            _record(
                session_id="sess2",
                timestamp="2026-01-02T10:00:00Z",
                closing_entry_uuid="u2",
                model="totally-unknown-model",
            ),
        ],
        db_path,
    )

    data = test_client.get("/api/analysis/cost-drivers?group_by=day").json()

    sessions = {row["session_id"] for row in data["top_sessions"]}
    assert sessions == {"sess1"}


def test_cost_drivers_top_sessions_includes_per_model_cost_breakdown(client):
    test_client, db_path = client
    insert_records(
        [
            _record(
                session_id="sess1",
                timestamp="2026-01-01T10:00:00Z",
                closing_entry_uuid="u1",
                model="claude-fable-5",
                input_tokens=1_000_000,
                output_tokens=0,
                cache_read_tokens=0,
                cache_write_tokens=0,
            ),
            _record(
                session_id="sess1",
                timestamp="2026-01-01T11:00:00Z",
                closing_entry_uuid="u2",
                model="claude-sonnet-5",
                input_tokens=1_000_000,
                output_tokens=0,
                cache_read_tokens=0,
                cache_write_tokens=0,
            ),
        ],
        db_path,
    )

    data = test_client.get("/api/analysis/cost-drivers?group_by=day").json()
    session = next(r for r in data["top_sessions"] if r["session_id"] == "sess1")

    # claude-fable-5's input rate (10.00) is 5x claude-sonnet-5's (2.00).
    assert session["models"][0] == {
        "model": "claude-fable-5",
        "cost_usd": pytest.approx(10.0),
    }
    assert session["models"][1] == {
        "model": "claude-sonnet-5",
        "cost_usd": pytest.approx(2.0),
    }


def test_recommendations_model_cost_share_rule_fires(client):
    test_client, db_path = client
    insert_records(
        [
            _record(
                session_id=f"cheap{i}",
                timestamp="2026-01-01T10:00:00Z",
                closing_entry_uuid=f"cheap{i}",
                model="claude-sonnet-5",
                input_tokens=10,
                output_tokens=10,
                cache_read_tokens=0,
                cache_write_tokens=0,
            )
            for i in range(9)
        ]
        + [
            _record(
                session_id="expensive",
                timestamp="2026-01-01T10:00:00Z",
                closing_entry_uuid="expensive1",
                model="claude-fable-5",
                input_tokens=10_000_000,
                output_tokens=10_000_000,
                cache_read_tokens=0,
                cache_write_tokens=0,
            )
        ],
        db_path,
    )

    recommendations = test_client.get(
        "/api/analysis/recommendations?group_by=day"
    ).json()

    assert any(r["rule"] == "model_cost_share" for r in recommendations)


def test_recommendations_unknown_cost_rule_fires(client):
    test_client, db_path = client
    insert_records(
        [
            _record(
                timestamp="2026-01-01T10:00:00Z",
                closing_entry_uuid="u1",
                model="totally-unknown-model",
            ),
        ],
        db_path,
    )

    recommendations = test_client.get(
        "/api/analysis/recommendations?group_by=day"
    ).json()

    assert any(r["rule"] == "unknown_cost_model" for r in recommendations)


def test_recommendations_repeated_prompt_candidate_fires_without_matching_skill(client):
    test_client, db_path = client
    insert_records(
        [
            _record(
                session_id="sess1",
                timestamp="2026-01-01T10:00:00Z",
                closing_entry_uuid="u1",
                prompt_text="please refactor the database layer for me now",
            ),
            _record(
                session_id="sess2",
                timestamp="2026-01-02T10:00:00Z",
                closing_entry_uuid="u2",
                prompt_text="please refactor the database layer for me now",
            ),
        ],
        db_path,
    )

    recommendations = test_client.get(
        "/api/analysis/recommendations?group_by=day"
    ).json()

    assert any(r["rule"] == "repeated_prompt_candidate" for r in recommendations)


def test_recommendations_cache_efficiency_regression_rule_fires(client):
    test_client, db_path = client
    insert_records(
        [
            _record(
                timestamp="2026-01-01T10:00:00Z",
                closing_entry_uuid="u1",
                input_tokens=50,
                output_tokens=50,
                cache_read_tokens=1900,
                cache_write_tokens=0,
            ),
            _record(
                timestamp="2026-01-02T10:00:00Z",
                closing_entry_uuid="u2",
                input_tokens=500,
                output_tokens=500,
                cache_read_tokens=1000,
                cache_write_tokens=0,
            ),
        ],
        db_path,
    )

    recommendations = test_client.get(
        "/api/analysis/recommendations?group_by=day"
    ).json()

    assert any(r["rule"] == "cache_efficiency_regression" for r in recommendations)
