-- viet-text2sql-agent — self-built observability store.
--
-- Deliberately a single plain table rather than a self-hosted tracing platform: Langfuse's
-- self-host topology assumes Docker Compose (Postgres + ClickHouse + Redis + MinIO), which
-- this project's no-Docker constraint rules out. See docs/DECISIONS.md.
--
-- Written by the application role (NOT t2sql_ro). Read by the Streamlit "Traces" tab.

CREATE TABLE IF NOT EXISTS agent_traces (
    id          BIGSERIAL PRIMARY KEY,
    trace_id    TEXT        NOT NULL,
    step        INTEGER     NOT NULL DEFAULT 0,   -- ordinal of this call within the trace
    tool_name   TEXT        NOT NULL,
    arguments   JSONB       NOT NULL DEFAULT '{}'::jsonb,
    result      JSONB       NOT NULL DEFAULT '{}'::jsonb,
    latency_ms  INTEGER,
    token_count INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS agent_traces_trace_id_idx  ON agent_traces (trace_id, step);
CREATE INDEX IF NOT EXISTS agent_traces_created_at_idx ON agent_traces (created_at DESC);
CREATE INDEX IF NOT EXISTS agent_traces_tool_name_idx  ON agent_traces (tool_name);
