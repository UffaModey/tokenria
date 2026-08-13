from pathlib import Path

from ingest.claude_code_adapter import (
    discover_sessions,
    discover_subagent_sessions,
    parse_session,
    parse_subagent_session,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_aggregates_thinking_and_tool_use_into_one_record_and_skips_tool_result():
    records = parse_session(FIXTURES / "basic_session.jsonl")

    assert len(records) == 1
    record = records[0]
    assert record["prompt_text"] == "Fix the off-by-one bug in parse_session"
    assert record["response_text"] == "Fixed the off-by-one bug."
    assert record["model"] == "claude-sonnet-5"
    assert record["session_id"] == "basic_session"
    assert record["is_estimated"] is False
    assert record["closing_entry_uuid"] == "a3"
    # sum of the thinking (10/5), tool_use (2/20), and text (3/15) calls
    assert record["input_tokens"] == 15
    assert record["output_tokens"] == 40
    assert record["cache_read_tokens"] == 300
    assert record["cache_write_tokens"] == 0


def test_excludes_sidechain_turns_from_records_and_usage():
    records = parse_session(FIXTURES / "sidechain_session.jsonl")

    assert len(records) == 1
    record = records[0]
    assert record["response_text"] == "Here's the summary."
    # only the non-sidechain assistant entry's usage counts
    assert record["input_tokens"] == 8
    assert record["output_tokens"] == 40


def test_unclosed_turn_emits_record_with_empty_response_text_and_accumulated_usage():
    records = parse_session(FIXTURES / "unclosed_session.jsonl")

    assert len(records) == 1
    record = records[0]
    assert record["response_text"] == ""
    assert record["prompt_text"] == "Run the migration"
    assert record["input_tokens"] == 10
    assert record["output_tokens"] == 21


def test_new_prompt_flushes_a_stalled_open_turn_as_its_own_record():
    records = parse_session(FIXTURES / "stalled_turn_before_new_prompt.jsonl")

    assert len(records) == 2
    stalled, closed = records

    assert stalled["prompt_text"] == "init"
    assert stalled["response_text"] == ""
    assert stalled["input_tokens"] == 8
    assert stalled["output_tokens"] == 9

    assert closed["prompt_text"] == "Please analyze this codebase"
    assert closed["response_text"] == "Here's my analysis."
    # only prompt B's own assistant call counts here, not A's leftover usage
    assert closed["input_tokens"] == 6
    assert closed["output_tokens"] == 30


def test_malformed_line_is_skipped_not_fatal():
    records = parse_session(FIXTURES / "malformed_line.jsonl")

    assert len(records) == 1
    assert records[0]["prompt_text"] == "Say hi"
    assert records[0]["response_text"] == "Hi there!"


def test_empty_session_produces_no_records():
    assert parse_session(FIXTURES / "empty_session.jsonl") == []


def test_session_name_uses_the_final_ai_title_for_every_record():
    records = parse_session(FIXTURES / "session_with_title.jsonl")

    assert len(records) == 2
    # both records get the title as it settled by end of session, not the
    # earlier draft title that was current when the first record closed
    assert records[0]["session_name"] == "Add session filter to tagging picker"
    assert records[1]["session_name"] == "Add session filter to tagging picker"


def test_session_without_ai_title_gets_no_session_name():
    records = parse_session(FIXTURES / "basic_session.jsonl")

    assert records[0]["session_name"] is None


def test_discover_sessions_returns_empty_list_for_missing_root(tmp_path):
    assert discover_sessions(tmp_path / "does-not-exist") == []


def test_discover_sessions_finds_jsonl_files_one_level_under_project_dirs(tmp_path):
    project_dir = tmp_path / "-Users-someone-project"
    project_dir.mkdir()
    session_file = project_dir / "session-1.jsonl"
    session_file.write_text("")
    (tmp_path / "not-a-session.txt").write_text("")

    assert discover_sessions(tmp_path) == [session_file]


def test_discover_subagent_sessions_returns_empty_list_for_missing_root(tmp_path):
    assert discover_subagent_sessions(tmp_path / "does-not-exist") == []


def test_discover_subagent_sessions_finds_files_under_session_subagents_dirs(tmp_path):
    project_dir = tmp_path / "-Users-someone-project"
    subagents_dir = project_dir / "session-1" / "subagents"
    subagents_dir.mkdir(parents=True)
    agent_file = subagents_dir / "agent-abc.jsonl"
    agent_file.write_text("")
    # a plain main-thread session file, at discover_sessions' own depth,
    # must not be picked up by the subagent discoverer
    (project_dir / "session-1.jsonl").write_text("")

    assert discover_subagent_sessions(tmp_path) == [agent_file]


def test_parse_subagent_session_aggregates_isSidechain_turns_and_tags_agent_fields():
    path = FIXTURES / "subagent_session" / "subagents" / "agent-a9b9a92a1c.jsonl"
    records = parse_subagent_session(path)

    assert len(records) == 1
    record = records[0]
    assert record["prompt_text"] == "Survey the subdirectories and report back"
    assert record["response_text"] == "Found 3 relevant projects."
    # session_id is the parent folder's name, not this file's own name
    assert record["session_id"] == "subagent_session"
    assert record["is_subagent"] is True
    assert record["agent_type"] == "general-purpose"
    assert record["agent_description"] == "Survey subdirectories"
    assert record["agent_id"] == "a9b9a92a1c"
    # isSidechain turns are aggregated here, not skipped as they would be
    # inside a main-thread session
    assert record["input_tokens"] == 6
    assert record["output_tokens"] == 50
    assert record["cache_read_tokens"] == 600
    assert record["cache_write_tokens"] == 10


def test_parse_subagent_session_with_missing_meta_json_leaves_agent_fields_none():
    path = (
        FIXTURES / "subagent_session_no_meta" / "subagents" / "agent-b0c0d0e0f0.jsonl"
    )
    records = parse_subagent_session(path)

    assert len(records) == 1
    assert records[0]["is_subagent"] is True
    assert records[0]["agent_type"] is None
    assert records[0]["agent_description"] is None
    assert records[0]["agent_id"] == "b0c0d0e0f0"
