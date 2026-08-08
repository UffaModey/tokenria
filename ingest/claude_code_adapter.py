"""Parses Claude Code session JSONL files into normalized usage records.

See stages/01-claude-code-adapter.md for the format this is reverse-engineered
from.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PROJECTS_ROOT = Path.home() / ".claude" / "projects"


def discover_sessions(root: Path = DEFAULT_PROJECTS_ROOT) -> list[Path]:
    """Return every session JSONL file under every project directory."""
    if not root.exists():
        return []
    return sorted(root.glob("*/*.jsonl"))


def parse_all(root: Path = DEFAULT_PROJECTS_ROOT) -> list[dict]:
    records = []
    for session_path in discover_sessions(root):
        records.extend(parse_session(session_path))
    return records


def parse_session(path: Path) -> list[dict]:
    """Parse one session file into a list of normalized record dicts.

    Aggregates every assistant JSONL line since the last real user prompt
    into one record, emitted when a `text` content block closes the turn
    (or at EOF, if the turn never closed).
    """
    session_id = path.stem
    entries = _read_entries(path)

    records = []
    current_prompt = None
    turn_totals = _new_totals()
    turn_model = None
    last_turn_entry = None
    skipped_sidechain_tokens = _new_totals()

    def flush_open_turn():
        nonlocal turn_totals, turn_model, last_turn_entry
        if last_turn_entry is not None:
            records.append(
                _build_record(
                    last_turn_entry,
                    session_id,
                    current_prompt,
                    turn_model,
                    turn_totals,
                    "",
                )
            )
        turn_totals = _new_totals()
        turn_model = None
        last_turn_entry = None

    for entry in entries:
        entry_type = entry.get("type")

        if entry_type == "user":
            if _is_real_prompt(entry):
                # A new real prompt starting before the previous turn got a
                # closing `text` block means that turn stalled mid-tool-loop
                # (e.g. this project's own "init" -> real-prompt sequence).
                # Flush it as its own record rather than silently folding its
                # tokens into whichever turn closes next.
                flush_open_turn()
                current_prompt = _prompt_text(entry)
            continue

        if entry_type != "assistant":
            continue

        if entry.get("isSidechain"):
            usage = entry.get("message", {}).get("usage")
            if usage:
                _sum_usage(skipped_sidechain_tokens, usage)
            continue

        message = entry.get("message") or {}
        usage = message.get("usage")
        content_blocks = message.get("content") or []
        block_type = content_blocks[0].get("type") if content_blocks else None

        if usage:
            _sum_usage(turn_totals, usage)
            turn_model = message.get("model", turn_model)
            last_turn_entry = entry

        if block_type == "text":
            response_text = _joined_text(content_blocks)
            records.append(
                _build_record(
                    entry,
                    session_id,
                    current_prompt,
                    turn_model,
                    turn_totals,
                    response_text,
                )
            )
            turn_totals = _new_totals()
            turn_model = None
            last_turn_entry = None

    flush_open_turn()

    if any(skipped_sidechain_tokens.values()):
        logger.info(
            "session %s: skipped sidechain usage %s",
            session_id,
            skipped_sidechain_tokens,
        )

    return records


def _read_entries(path: Path) -> list[dict]:
    entries = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("%s: skipping malformed JSONL line", path)
    return entries


def _is_real_prompt(entry: dict) -> bool:
    content = entry.get("message", {}).get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return any(block.get("type") == "text" for block in content)
    return False


def _prompt_text(entry: dict) -> str:
    content = entry["message"]["content"]
    if isinstance(content, str):
        return content
    return _joined_text(content)


def _joined_text(content_blocks: list[dict]) -> str:
    return "".join(
        block.get("text", "") for block in content_blocks if block.get("type") == "text"
    )


def _new_totals() -> dict:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }


def _sum_usage(totals: dict, usage: dict) -> None:
    totals["input_tokens"] += usage.get("input_tokens", 0)
    totals["output_tokens"] += usage.get("output_tokens", 0)
    totals["cache_read_tokens"] += usage.get("cache_read_input_tokens", 0)
    totals["cache_write_tokens"] += usage.get("cache_creation_input_tokens", 0)


def _build_record(
    closing_entry: dict,
    session_id: str,
    prompt_text: str | None,
    model: str | None,
    totals: dict,
    response_text: str,
) -> dict:
    return {
        "source": "claude_code",
        "timestamp": closing_entry.get("timestamp"),
        "session_id": session_id,
        "model": model,
        "prompt_text": prompt_text,
        "response_text": response_text,
        "input_tokens": totals["input_tokens"],
        "output_tokens": totals["output_tokens"],
        "cache_read_tokens": totals["cache_read_tokens"],
        "cache_write_tokens": totals["cache_write_tokens"],
        "is_estimated": False,
        "closing_entry_uuid": closing_entry.get("uuid"),
    }


if __name__ == "__main__":
    from db.database import init_db, insert_records

    init_db()
    inserted = insert_records(parse_all())
    print(f"inserted {inserted} new record(s)")
