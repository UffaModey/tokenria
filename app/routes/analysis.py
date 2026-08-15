"""Read-only analysis routes: trends, cost drivers, and rule-generated
recommendations over the same `records` table the accounting view reads.

See stages/03.1-analysis-view.md. Not a new tier or ingestion source --
everything here reads `records` as it already exists after stage 3's
subagent-attribution and 1h/5m cache-pricing revisions.
"""

import sqlite3
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Query

from db.database import DEFAULT_DB_PATH, SYNTHETIC_MODEL, get_connection
from db.pricing import PRICING

router = APIRouter()

GROUP_BY_FORMATS = {
    "day": "%Y-%m-%d",
    "week": "%Y-%W",
    "month": "%Y-%m",
}

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / ".claude" / "skills"


def get_db_path() -> Path:
    return DEFAULT_DB_PATH


def _category_costs(model: str | None, row: sqlite3.Row) -> dict[str, float] | None:
    """Split a (period, model) token bucket into per-category dollar amounts.

    `cost_usd` on `records` is a single blended total computed at insert time;
    getting a dollar figure *per category* means re-applying the same
    `db.pricing.PRICING` rates here rather than re-deriving them.
    """
    rates = PRICING.get(model)
    if rates is None:
        return None
    (
        input_rate,
        output_rate,
        cache_write_1h_rate,
        cache_write_5m_rate,
        cache_read_rate,
    ) = rates
    return {
        "input_cost": row["input_tokens"] * input_rate / 1_000_000,
        "output_cost": row["output_tokens"] * output_rate / 1_000_000,
        "cache_write_cost": (
            row["cache_write_1h_tokens"] * cache_write_1h_rate
            + row["cache_write_5m_tokens"] * cache_write_5m_rate
        )
        / 1_000_000,
        "cache_read_cost": row["cache_read_tokens"] * cache_read_rate / 1_000_000,
    }


def _fetch_period_model_totals(
    conn: sqlite3.Connection, period_format: str
) -> list[sqlite3.Row]:
    return conn.execute(
        f"""
        SELECT
            strftime('{period_format}', timestamp) AS period,
            model,
            COUNT(*) AS record_count,
            SUM(input_tokens) AS input_tokens,
            SUM(output_tokens) AS output_tokens,
            SUM(cache_read_tokens) AS cache_read_tokens,
            SUM(cache_write_1h_tokens) AS cache_write_1h_tokens,
            SUM(cache_write_5m_tokens) AS cache_write_5m_tokens,
            SUM(cost_usd) AS cost_usd
        FROM records
        WHERE model IS NOT :synthetic_model
        GROUP BY period, model
        ORDER BY period
        """,
        {"synthetic_model": SYNTHETIC_MODEL},
    ).fetchall()


def _trends_data(conn: sqlite3.Connection, group_by: str) -> dict:
    period_format = GROUP_BY_FORMATS[group_by]
    rows = conn.execute(
        f"""
        SELECT
            strftime('{period_format}', timestamp) AS period,
            SUM(input_tokens) AS input_tokens,
            SUM(cache_write_tokens) AS cache_write_tokens,
            SUM(cache_read_tokens) AS cache_read_tokens,
            SUM(output_tokens) AS output_tokens
        FROM records
        WHERE model IS NOT :synthetic_model
        GROUP BY period
        ORDER BY period
        """,
        {"synthetic_model": SYNTHETIC_MODEL},
    ).fetchall()

    by_period = []
    for row in rows:
        total = (
            row["input_tokens"]
            + row["cache_write_tokens"]
            + row["cache_read_tokens"]
            + row["output_tokens"]
        )
        by_period.append(
            {
                "period": row["period"],
                "input_tokens": row["input_tokens"],
                "cache_write_tokens": row["cache_write_tokens"],
                "cache_read_tokens": row["cache_read_tokens"],
                "output_tokens": row["output_tokens"],
                "cache_read_share": (
                    None if total == 0 else row["cache_read_tokens"] / total * 100
                ),
            }
        )

    model_rows = conn.execute(
        f"""
        SELECT
            strftime('{period_format}', timestamp) AS period,
            model,
            COUNT(*) AS record_count,
            SUM(cost_usd) AS cost_usd
        FROM records
        WHERE model IS NOT :synthetic_model
        GROUP BY period, model
        ORDER BY period
        """,
        {"synthetic_model": SYNTHETIC_MODEL},
    ).fetchall()
    by_period_model = [
        {
            "period": row["period"],
            "model": row["model"],
            "record_count": row["record_count"],
            "cost_usd": row["cost_usd"],
        }
        for row in model_rows
    ]

    return {"by_period": by_period, "by_period_model": by_period_model}


def _repeated_prompts_data(
    conn: sqlite3.Connection, min_occurrences: int, min_length: int
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            prompt_text,
            COUNT(DISTINCT session_id) AS session_count,
            COUNT(*) AS record_count,
            SUM(cost_usd) AS total_cost
        FROM records
        WHERE prompt_text IS NOT NULL AND LENGTH(prompt_text) >= :min_length
          AND model IS NOT :synthetic_model
        GROUP BY prompt_text
        HAVING COUNT(DISTINCT session_id) >= :min_occurrences
        ORDER BY total_cost DESC
        """,
        {
            "min_length": min_length,
            "min_occurrences": min_occurrences,
            "synthetic_model": SYNTHETIC_MODEL,
        },
    ).fetchall()

    # Per-model cost within each qualifying prompt -- these sum back to that
    # prompt's own total_cost, since both are SUM(cost_usd) over the same
    # records, just grouped differently (SQL SUM ignores NULLs either way).
    prompt_texts = [row["prompt_text"] for row in rows]
    models_by_prompt: dict[str, list[dict]] = {text: [] for text in prompt_texts}
    if prompt_texts:
        placeholders = ",".join("?" * len(prompt_texts))
        prompt_model_rows = conn.execute(
            f"""
            SELECT prompt_text, model, SUM(cost_usd) AS cost_usd
            FROM records
            WHERE prompt_text IN ({placeholders})
              AND model IS NOT ?
            GROUP BY prompt_text, model
            HAVING cost_usd IS NOT NULL
            ORDER BY cost_usd DESC
            """,
            [*prompt_texts, SYNTHETIC_MODEL],
        ).fetchall()
        for row in prompt_model_rows:
            models_by_prompt[row["prompt_text"]].append(
                {"model": row["model"], "cost_usd": row["cost_usd"]}
            )

    return [
        {
            "prompt_text": row["prompt_text"],
            "session_count": row["session_count"],
            "record_count": row["record_count"],
            "total_cost": row["total_cost"],
            "models": models_by_prompt[row["prompt_text"]],
        }
        for row in rows
    ]


def _prompt_instances_data(conn: sqlite3.Connection, prompt_text: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT * FROM records
        WHERE prompt_text = :prompt_text
          AND model IS NOT :synthetic_model
        ORDER BY timestamp ASC
        """,
        {"prompt_text": prompt_text, "synthetic_model": SYNTHETIC_MODEL},
    ).fetchall()

    return [{**dict(row), "is_estimated": bool(row["is_estimated"])} for row in rows]


def _cost_drivers_data(conn: sqlite3.Connection, group_by: str) -> dict:
    period_format = GROUP_BY_FORMATS[group_by]
    period_model_rows = _fetch_period_model_totals(conn, period_format)

    cost_by_category: dict[str, dict[str, float]] = {}
    cost_by_model: dict[str, float] = {}
    # Per (period, category), which models made up that bar -- lets the merged
    # cost-by-category chart show a model breakdown on hover instead of
    # needing a separate cost-by-model chart alongside it.
    cost_by_category_model: dict[str, dict[str, list[dict]]] = {}
    for row in period_model_rows:
        costs = _category_costs(row["model"], row)
        if costs is None:
            continue
        period = row["period"]
        bucket = cost_by_category.setdefault(
            period,
            {
                "input_cost": 0.0,
                "cache_write_cost": 0.0,
                "cache_read_cost": 0.0,
                "output_cost": 0.0,
            },
        )
        bucket["input_cost"] += costs["input_cost"]
        bucket["cache_write_cost"] += costs["cache_write_cost"]
        bucket["cache_read_cost"] += costs["cache_read_cost"]
        bucket["output_cost"] += costs["output_cost"]

        model = row["model"]
        cost_by_model[model] = cost_by_model.get(model, 0.0) + sum(costs.values())

        period_bucket = cost_by_category_model.setdefault(
            period,
            {
                "input_cost": [],
                "cache_write_cost": [],
                "cache_read_cost": [],
                "output_cost": [],
            },
        )
        for category_key, cost_value in costs.items():
            if cost_value > 0:
                period_bucket[category_key].append(
                    {"model": model, "cost_usd": cost_value}
                )

    cost_by_category_series = [
        {"period": period, **totals}
        for period, totals in sorted(cost_by_category.items())
    ]
    cost_by_model_list = sorted(
        [{"model": model, "cost_usd": cost} for model, cost in cost_by_model.items()],
        key=lambda r: r["cost_usd"],
        reverse=True,
    )
    for period_bucket in cost_by_category_model.values():
        for entries in period_bucket.values():
            entries.sort(key=lambda e: e["cost_usd"], reverse=True)

    human_vs_subagent = conn.execute(
        """
        SELECT
            is_subagent,
            SUM(cost_usd) AS cost_usd,
            COUNT(*) AS record_count
        FROM records
        WHERE model IS NOT :synthetic_model
        GROUP BY is_subagent
        """,
        {"synthetic_model": SYNTHETIC_MODEL},
    ).fetchall()
    human_vs_subagent_split = {
        "human_cost_usd": next(
            (r["cost_usd"] for r in human_vs_subagent if not r["is_subagent"]), 0.0
        ),
        "subagent_cost_usd": next(
            (r["cost_usd"] for r in human_vs_subagent if r["is_subagent"]), 0.0
        ),
    }

    top_sessions = conn.execute(
        f"""
        SELECT
            session_id,
            MAX(session_name) AS session_name,
            strftime('{period_format}', MIN(timestamp)) AS period,
            SUM(cost_usd) AS cost_usd
        FROM records
        WHERE session_id IS NOT NULL
          AND model IS NOT :synthetic_model
        GROUP BY session_id
        HAVING cost_usd IS NOT NULL
        ORDER BY cost_usd DESC
        LIMIT 10
        """,
        {"synthetic_model": SYNTHETIC_MODEL},
    ).fetchall()

    # Per-model cost within each of those top sessions -- e.g. "$115 total:
    # $98 claude-fable-5, $17 claude-sonnet-5" -- not just which models ran.
    top_session_ids = [row["session_id"] for row in top_sessions]
    models_by_session: dict[str, list[dict]] = {sid: [] for sid in top_session_ids}
    if top_session_ids:
        placeholders = ",".join("?" * len(top_session_ids))
        session_model_rows = conn.execute(
            f"""
            SELECT session_id, model, SUM(cost_usd) AS cost_usd
            FROM records
            WHERE session_id IN ({placeholders})
              AND model IS NOT ?
            GROUP BY session_id, model
            HAVING cost_usd IS NOT NULL
            ORDER BY cost_usd DESC
            """,
            [*top_session_ids, SYNTHETIC_MODEL],
        ).fetchall()
        for row in session_model_rows:
            models_by_session[row["session_id"]].append(
                {"model": row["model"], "cost_usd": row["cost_usd"]}
            )

    unknown_cost = conn.execute(
        """
        SELECT
            model,
            COUNT(*) AS record_count,
            SUM(
                input_tokens + output_tokens + cache_read_tokens + cache_write_tokens
            ) AS token_count
        FROM records
        WHERE cost_usd IS NULL
          AND model IS NOT :synthetic_model
        GROUP BY model
        """,
        {"synthetic_model": SYNTHETIC_MODEL},
    ).fetchall()

    return {
        "cost_by_category": cost_by_category_series,
        "cost_by_category_model": cost_by_category_model,
        "cost_by_model": cost_by_model_list,
        "human_vs_subagent": human_vs_subagent_split,
        "top_sessions": [
            {
                "session_id": row["session_id"],
                "session_name": row["session_name"],
                "period": row["period"],
                "cost_usd": row["cost_usd"],
                "models": models_by_session[row["session_id"]],
            }
            for row in top_sessions
        ],
        "unknown_cost": [
            {
                "model": row["model"],
                "record_count": row["record_count"],
                "token_count": row["token_count"],
            }
            for row in unknown_cost
        ],
    }


def _known_skills() -> list[dict[str, str]]:
    skills = []
    if not SKILLS_DIR.is_dir():
        return skills
    for skill_dir in SKILLS_DIR.iterdir():
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            continue
        text = skill_file.read_text()
        name = ""
        description = ""
        for line in text.splitlines():
            if line.startswith("name:"):
                name = line[len("name:") :].strip()
            elif line.startswith("description:"):
                description = line[len("description:") :].strip()
        skills.append({"name": name, "description": description})
    return skills


def _matches_known_skill(prompt_text: str, skills: list[dict[str, str]]) -> bool:
    """Match the skill's full name as a contiguous phrase, not individual words.

    A single-word check (e.g. "feature", "project", "task") false-positives
    constantly against long prompt bodies -- a repeated prompt that's itself a
    multi-paragraph skill invocation (the exact case this rule exists to
    catch) incidentally contains plenty of generic English words. The full
    hyphenated name read as a phrase is specific enough to stay a meaningful
    v1 substring check without that noise.
    """
    lowered = prompt_text.lower()
    for skill in skills:
        name_phrase = skill["name"].replace("-", " ").strip()
        if name_phrase and name_phrase in lowered:
            return True
    return False


def _recommendations_data(
    trends: dict, cost_drivers: dict, repeated_prompts: list[dict]
) -> list[dict]:
    recommendations = []

    total_cost_by_model = {
        row["model"]: row["cost_usd"] for row in cost_drivers["cost_by_model"]
    }
    total_cost = sum(total_cost_by_model.values())
    record_counts_by_model: dict[str, int] = {}
    for row in trends["by_period_model"]:
        record_counts_by_model[row["model"]] = (
            record_counts_by_model.get(row["model"], 0) + row["record_count"]
        )
    total_records = sum(record_counts_by_model.values())

    if total_cost > 0 and total_records > 0:
        for model, cost in total_cost_by_model.items():
            cost_share = cost / total_cost
            record_share = record_counts_by_model.get(model, 0) / total_records
            if (
                record_share > 0
                and cost_share > record_share * 1.5
                and cost_share - record_share > 0.1
            ):
                cheaper_models = sorted(
                    (m for m in PRICING if m != model),
                    key=lambda m: PRICING[m][0],
                )
                cheaper = cheaper_models[0] if cheaper_models else "a cheaper model"
                recommendations.append(
                    {
                        "rule": "model_cost_share",
                        "message": (
                            f"Review whether `{model}`'s extra cost is buying you "
                            f"something `{cheaper}` couldn't -- it accounts for "
                            f"{cost_share * 100:.1f}% of cost but only "
                            f"{record_share * 100:.1f}% of records."
                        ),
                    }
                )

    skills = _known_skills()
    for prompt in repeated_prompts:
        if not _matches_known_skill(prompt["prompt_text"], skills):
            recommendations.append(
                {
                    "rule": "repeated_prompt_candidate",
                    "message": (
                        f"Prompt repeated across {prompt['session_count']} sessions "
                        f"(${(prompt['total_cost'] or 0):.2f} total) isn't backed by "
                        "a known skill/command -- consider turning it into one: "
                        f'"{prompt["prompt_text"][:80]}"'
                    ),
                }
            )

    for unknown in cost_drivers["unknown_cost"]:
        recommendations.append(
            {
                "rule": "unknown_cost_model",
                "message": (
                    f"Add a `db/pricing.py` entry for `{unknown['model']}` -- "
                    f"{unknown['record_count']} record(s) currently excluded from "
                    "every total."
                ),
            }
        )

    periods = [p for p in trends["by_period"] if p["cache_read_share"] is not None]
    if len(periods) >= 2:
        latest = periods[-1]
        trailing = periods[:-1]
        trailing_avg = sum(p["cache_read_share"] for p in trailing) / len(trailing)
        if latest["cache_read_share"] < trailing_avg - 10:
            recommendations.append(
                {
                    "rule": "cache_efficiency_regression",
                    "message": (
                        "Cache efficiency regressed this period "
                        f"({latest['cache_read_share']:.1f}% vs a {trailing_avg:.1f}% "
                        "trailing average) -- check for unusually short-lived "
                        "sessions or context that isn't being reused."
                    ),
                }
            )

    return recommendations


@router.get("/analysis/trends")
def get_trends(
    group_by: Literal["day", "week", "month"] = "day",
    db_path: Path = Depends(get_db_path),
):
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return _trends_data(conn, group_by)
    finally:
        conn.close()


@router.get("/analysis/repeated-prompts")
def get_repeated_prompts(
    min_occurrences: int = Query(2, ge=1),
    min_length: int = Query(20, ge=0),
    db_path: Path = Depends(get_db_path),
):
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return _repeated_prompts_data(conn, min_occurrences, min_length)
    finally:
        conn.close()


@router.get("/analysis/repeated-prompts/instances")
def get_prompt_instances(prompt_text: str, db_path: Path = Depends(get_db_path)):
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return _prompt_instances_data(conn, prompt_text)
    finally:
        conn.close()


@router.get("/analysis/cost-drivers")
def get_cost_drivers(
    group_by: Literal["day", "week", "month"] = "day",
    db_path: Path = Depends(get_db_path),
):
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return _cost_drivers_data(conn, group_by)
    finally:
        conn.close()


@router.get("/analysis/recommendations")
def get_recommendations(
    group_by: Literal["day", "week", "month"] = "day",
    min_occurrences: int = Query(2, ge=1),
    min_length: int = Query(20, ge=0),
    db_path: Path = Depends(get_db_path),
):
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    try:
        trends = _trends_data(conn, group_by)
        cost_drivers = _cost_drivers_data(conn, group_by)
        repeated_prompts = _repeated_prompts_data(conn, min_occurrences, min_length)
    finally:
        conn.close()
    return _recommendations_data(trends, cost_drivers, repeated_prompts)
