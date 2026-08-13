# Running Tokenria locally

Stages 1-4 are implemented (Claude Code ingestion, SQLite persistence, accounting view,
tagging view). This is how to run what exists today.

## 1. Set up the environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn tiktoken python-dotenv pytest ruff httpx
```

Note: don't use `pip install -e .` — this repo has multiple top-level packages (`app`, `db`,
`ingest`, ...) with no packaging config, so setuptools refuses an editable install. The plain
install above is what actually works; nothing here needs to be installed as a package, since
`main.py`/`pytest` are both run from the repo root.

## 2. Ingest your real Claude Code usage data

```bash
python -m ingest.claude_code_adapter
```

Parses every session under `~/.claude/projects/**/*.jsonl` and writes normalized rows into
`db/tokenria.db` (created automatically). Prints how many *new* rows were inserted. Safe to
re-run any time — already-ingested turns are skipped (deduped on `external_id`), so re-running
after using Claude Code more just picks up what's new.

## 3. Start the server

```bash
python main.py
```

Starts at **http://127.0.0.1:8000**. Bound to localhost only, deliberately — this is a local,
single-user tool with no auth, so it shouldn't accept connections from other machines.

- **http://127.0.0.1:8000/** — Accounting view: token/cost breakdown by day/week/month, stacked
  by structural category (new input / cache write / cache read / output), with a totals row and
  detail table.
- **http://127.0.0.1:8000/static/tagging.html** — Tagging view: pick a record, click through its
  response chunks (unmarked → used → discarded), save, see the adoption ratio update live.

Both pages link to each other via the nav bar at the top.

## 4. Run the tests / linter

```bash
pytest          # tests/test_claude_code_adapter.py, test_database.py, test_accounting_routes.py, test_tagging_routes.py
ruff check .    # lint
ruff format .   # format
```

## Notes for actually using it

- The tagging view only lists records that have a non-empty `response_text` — turns where a
  Claude Code session ended mid-tool-loop (no closing reply) are excluded, since there's nothing
  to tag.
- Cost (`cost_usd`) is only shown for models in `db/pricing.py`'s `PRICING` table
  (`claude-haiku-4-5`, `claude-sonnet-5`, `claude-opus-5`, `claude-fable-5`,
  `claude-sonnet-4-6`). Any model not in that table shows as unknown cost rather than a guessed
  number — that's deliberate, not a bug.
- If `db/tokenria.db` ever gets into a state you want to throw away, just delete the file —
  `python main.py` recreates an empty schema on startup, and re-running the ingest step in step 2
  repopulates it from your real Claude Code history.
- Stages 5-7 (generic API-response adapter, text-paste input, auto-annotation) aren't built yet —
  see `CLAUDE.md` and `stages/` for what's next.
