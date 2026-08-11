"""Manual chunk-tagging routes over `tags`, backing Feature 2 (adoption ratio).

See stages/04-tagging-view.md — chunk-level, character-space tagging. PUT
never touches source='auto' rows (stage 7's not-yet-built suggestions).
"""

import sqlite3
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.routes.accounting import get_db_path
from db.database import get_connection

router = APIRouter()


class TagIn(BaseModel):
    span_start: int
    span_end: int
    used: bool


@router.get("/records/picker")
def list_picker_records(db_path: Path = Depends(get_db_path)):
    """Lightweight id/timestamp/session_id/preview rows for the tagging
    view's ID/date/session filters — the full taggable set, not paginated,
    since the filters need every value to cross-reference against.
    """
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, timestamp, session_id, session_name,
                   SUBSTR(prompt_text, 1, 80) AS prompt_preview
            FROM records
            WHERE response_text IS NOT NULL AND response_text != ''
            ORDER BY timestamp DESC
            """
        ).fetchall()
    finally:
        conn.close()

    return [dict(row) for row in rows]


@router.get("/records/{record_id}")
def get_record(record_id: str, db_path: Path = Depends(get_db_path)):
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM records WHERE id = ?", (record_id,)
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail="record not found")
    return {**dict(row), "is_estimated": bool(row["is_estimated"])}


@router.get("/records/{record_id}/tags")
def get_tags(record_id: str, db_path: Path = Depends(get_db_path)):
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, span_start, span_end, used, source FROM tags"
            " WHERE record_id = ? ORDER BY span_start",
            (record_id,),
        ).fetchall()
    finally:
        conn.close()

    return [{**dict(row), "used": bool(row["used"])} for row in rows]


@router.put("/records/{record_id}/tags")
def replace_manual_tags(
    record_id: str, tags: list[TagIn], db_path: Path = Depends(get_db_path)
):
    conn = get_connection(db_path)
    try:
        exists = conn.execute(
            "SELECT 1 FROM records WHERE id = ?", (record_id,)
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="record not found")

        conn.execute(
            "DELETE FROM tags WHERE record_id = ? AND source = 'manual'",
            (record_id,),
        )
        conn.executemany(
            """
            INSERT INTO tags (id, record_id, span_start, span_end, used, source)
            VALUES (?, ?, ?, ?, ?, 'manual')
            """,
            [
                (str(uuid.uuid4()), record_id, t.span_start, t.span_end, t.used)
                for t in tags
            ],
        )
        conn.commit()
    finally:
        conn.close()

    return {"saved": len(tags)}
