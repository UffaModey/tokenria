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


def discover_subagent_sessions(root: Path = DEFAULT_PROJECTS_ROOT) -> list[Path]:
    """Return every subagent transcript file under every session directory.

    A subagent's transcript lives at
    `<project>/<session-id>/subagents/agent-<id>.jsonl`, a sibling of that
    session's own `<session-id>.jsonl` -- `discover_sessions`'s
    two-segments-deep glob never matches this four-segments-deep path, which
    is why subagent usage went undiscovered rather than merely filtered out.
    """
    if not root.exists():
        return []
    return sorted(root.glob("*/*/subagents/*.jsonl"))


def parse_all(root: Path = DEFAULT_PROJECTS_ROOT) -> list[dict]:
    records = []
    for session_path in discover_sessions(root):
        records.extend(parse_session(session_path))
    for subagent_path in discover_subagent_sessions(root):
        records.extend(parse_subagent_session(subagent_path))
    return records


def parse_session(path: Path) -> list[dict]:
    """Parse one main-thread session file into a list of normalized record dicts.

    Aggregates every assistant JSONL line since the last real user prompt
    into one record, emitted when a `text` content block closes the turn
    (or at EOF, if the turn never closed).
    """
    session_id = path.stem
    entries = _read_entries(path)
    records, session_title = _parse_turns(entries, session_id, skip_sidechain=True)
    for record in records:
        record["session_name"] = session_title
    return records


def parse_subagent_session(path: Path) -> list[dict]:
    """Parse one subagent transcript into a list of normalized record dicts.

    `path` is `<project>/<session-id>/subagents/agent-<id>.jsonl`. Every entry
    in this file is internally marked `isSidechain: true`, but the file itself
    is a dedicated subagent transcript rather than sidechain noise inside a
    main-thread session, so its turns are aggregated the same way a
    main-thread session's are, not skipped. `session_id` is the parent
    session's id (the folder name containing `subagents/`), not this file's
    own name, so a subagent's work can be joined back to the human session it
    happened under.
    """
    agent_id = path.stem.removeprefix("agent-")
    session_id = path.parent.parent.name
    entries = _read_entries(path)
    records, _session_title = _parse_turns(entries, session_id, skip_sidechain=False)

    meta = _read_agent_meta(path)
    for record in records:
        record["is_subagent"] = True
        record["agent_type"] = meta.get("agentType")
        record["agent_description"] = meta.get("description")
        record["agent_id"] = agent_id

    return records


def _parse_turns(
    entries: list[dict], session_id: str, skip_sidechain: bool
) -> tuple[list[dict], str | None]:
    """Walk entries in file order, aggregating usage per human-perceived turn.

    Args:
        entries: parsed JSONL entries, in file order.
        session_id: value to stamp onto every emitted record's `session_id`.
        skip_sidechain: when True, `isSidechain: true` assistant entries are
            excluded and their usage only logged (main-thread session files,
            where sidechain entries are a different turn's subagent noise);
            when False, they're aggregated normally (dedicated subagent
            transcript files, where every entry is marked isSidechain but
            represents that file's own real turns).

    Returns:
        A tuple of (records, session_title), where session_title is the last
        `ai-title` entry's title seen, or None if there was none.
    """
    records = []
    current_prompt = None
    turn_totals = _new_totals()
    turn_model = None
    last_turn_entry = None
    skipped_sidechain_tokens = _new_totals()
    session_title = None

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

        if entry_type == "ai-title":
            # Claude Code re-emits this as the conversation's auto-generated
            # title settles or shifts topic; the last one seen is the
            # session's final name, applied retroactively to every record
            # below once the whole file has been read.
            session_title = entry.get("aiTitle", session_title)
            continue

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

        if skip_sidechain and entry.get("isSidechain"):
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

    return records, session_title


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


def _read_agent_meta(jsonl_path: Path) -> dict:
    """Read the `agent-<id>.meta.json` sidecar for a subagent transcript.

    Returns {} (with a logged warning) if the sidecar is missing or
    malformed, so a subagent record still gets ingested with
    agent_type/agent_description left None rather than the whole file
    failing to parse.
    """
    meta_path = jsonl_path.parent / f"{jsonl_path.stem}.meta.json"
    if not meta_path.exists():
        logger.warning("%s: missing sidecar meta.json", jsonl_path)
        return {}
    try:
        return json.loads(meta_path.read_text())
    except json.JSONDecodeError:
        logger.warning("%s: malformed meta.json", meta_path)
        return {}


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
        "cache_write_1h_tokens": 0,
        "cache_write_5m_tokens": 0,
    }


def _sum_usage(totals: dict, usage: dict) -> None:
    totals["input_tokens"] += usage.get("input_tokens", 0)
    totals["output_tokens"] += usage.get("output_tokens", 0)
    totals["cache_read_tokens"] += usage.get("cache_read_input_tokens", 0)

    flat_cache_write = usage.get("cache_creation_input_tokens", 0)
    cache_creation = usage.get("cache_creation") or {}
    cache_write_1h = cache_creation.get("ephemeral_1h_input_tokens", 0)
    cache_write_5m = cache_creation.get("ephemeral_5m_input_tokens", 0)
    if cache_write_1h + cache_write_5m != flat_cache_write:
        logger.warning(
            "cache_creation sub-fields (1h=%s, 5m=%s) don't sum to "
            "cache_creation_input_tokens=%s",
            cache_write_1h,
            cache_write_5m,
            flat_cache_write,
        )

    totals["cache_write_tokens"] += flat_cache_write
    totals["cache_write_1h_tokens"] += cache_write_1h
    totals["cache_write_5m_tokens"] += cache_write_5m


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
        "cache_write_1h_tokens": totals["cache_write_1h_tokens"],
        "cache_write_5m_tokens": totals["cache_write_5m_tokens"],
        "is_estimated": False,
        "closing_entry_uuid": closing_entry.get("uuid"),
    }


if __name__ == "__main__":
    from db.database import init_db, insert_records

    init_db()
    inserted = insert_records(parse_all())
    print(f"inserted {inserted} new record(s)")
