"""Read-only accounting routes: structural token/cost rollups over `records`.

See stages/03-accounting-view.md — four measurable categories (new input,
cache write, cache read, output), not the six spec.md originally named, since
the raw usage data doesn't expose a finer split.
"""

import sqlite3
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Query

from db.database import DEFAULT_DB_PATH, get_connection

router = APIRouter()

GROUP_BY_FORMATS = {
    "day": "%Y-%m-%d",
    "week": "%Y-%W",
    "month": "%Y-%m",
}


def get_db_path() -> Path:
    return DEFAULT_DB_PATH


@router.get("/records/summary")
def get_records_summary(
    group_by: Literal["day", "week", "month"] = "day",
    source: str | None = None,
    is_estimated: bool | None = None,
    db_path: Path = Depends(get_db_path),
):
    period_format = GROUP_BY_FORMATS[group_by]
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""
            SELECT
                strftime('{period_format}', timestamp) AS period,
                source,
                is_estimated,
                SUM(input_tokens) AS input_tokens,
                SUM(cache_write_tokens) AS cache_write_tokens,
                SUM(cache_read_tokens) AS cache_read_tokens,
                SUM(output_tokens) AS output_tokens,
                SUM(cost_usd) AS cost_usd
            FROM records
            WHERE (:source IS NULL OR source = :source)
              AND (:is_estimated IS NULL OR is_estimated = :is_estimated)
            GROUP BY period, source, is_estimated
            ORDER BY period
            """,
            {
                "source": source,
                "is_estimated": None if is_estimated is None else int(is_estimated),
            },
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            "period": row["period"],
            "source": row["source"],
            "is_estimated": bool(row["is_estimated"]),
            "input_tokens": row["input_tokens"],
            "cache_write_tokens": row["cache_write_tokens"],
            "cache_read_tokens": row["cache_read_tokens"],
            "output_tokens": row["output_tokens"],
            "cost_usd": row["cost_usd"],
        }
        for row in rows
    ]


@router.get("/records")
def list_records(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    source: str | None = None,
    has_response_text: bool | None = None,
    db_path: Path = Depends(get_db_path),
):
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT * FROM records
            WHERE (:source IS NULL OR source = :source)
              AND (
                :has_response_text IS NULL
                OR (
                    :has_response_text = 1
                    AND response_text IS NOT NULL AND response_text != ''
                )
                OR (
                    :has_response_text = 0
                    AND (response_text IS NULL OR response_text = '')
                )
              )
            ORDER BY timestamp DESC
            LIMIT :limit OFFSET :offset
            """,
            {
                "source": source,
                "has_response_text": (
                    None if has_response_text is None else int(has_response_text)
                ),
                "limit": limit,
                "offset": offset,
            },
        ).fetchall()
    finally:
        conn.close()

    return [{**dict(row), "is_estimated": bool(row["is_estimated"])} for row in rows]
