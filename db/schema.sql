-- All tables in this schema use UUIDv4 TEXT primary keys, not autoincrement
-- integers -- keep new tables consistent with this.
CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY,
    external_id TEXT UNIQUE,
    source TEXT NOT NULL,
    session_id TEXT,
    session_name TEXT,
    model TEXT,
    timestamp TEXT NOT NULL,
    prompt_text TEXT,
    response_text TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_1h_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_5m_tokens INTEGER NOT NULL DEFAULT 0,
    is_estimated BOOLEAN NOT NULL,
    cost_usd REAL,
    is_subagent BOOLEAN NOT NULL DEFAULT 0,
    agent_type TEXT,
    agent_description TEXT
);

CREATE INDEX IF NOT EXISTS idx_records_timestamp ON records(timestamp);
CREATE INDEX IF NOT EXISTS idx_records_source ON records(source);
CREATE INDEX IF NOT EXISTS idx_records_session_id ON records(session_id);

CREATE TABLE IF NOT EXISTS tags (
    id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    span_start INTEGER NOT NULL,
    span_end INTEGER NOT NULL,
    used BOOLEAN NOT NULL,
    source TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tags_record_id ON tags(record_id);
